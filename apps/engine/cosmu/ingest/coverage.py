# intent: the data-quality / VERIFY engine — turn the append-only point-in-time stores (alt_data + the
# bar cache) into a clear "what we have / what's stale / what's missing" coverage report; inputs: a store
# (read_all) + a set of expected series, and the on-disk bar cache; outputs: per source/symbol/metric row
# count, span, freshness, gap detection, and a look-ahead integrity check; invariants: PURE + offline (the
# clock is injected, never wall-time — deterministic in tests), read-only (never mutates a store), and the
# look-ahead check enforces the point-in-time law (a value is knowable no earlier than it is observed:
# available_at >= ts; available_at < ts is a leak).

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from cosmu.ingest.bars import bar_cache_path, read_cached_bars

# A series older than this (and older than 3× its own cadence) is flagged stale. A floor, not a hard rule:
# a daily series is stale after ~3 days; a fast 8h funding series after ~24h (3× cadence dominates).
DEFAULT_STALE_AFTER_SECONDS = 3 * 86400


@dataclass(frozen=True)
class SeriesCoverage:
    """One series' health: counts, span, freshness, gaps, and the look-ahead integrity result."""

    provider: str
    symbol: str
    metric: str
    kind: str  # "alt" | "bars"
    rows: int
    first_ts: datetime | None
    last_ts: datetime | None
    last_available_at: datetime | None
    freshness_seconds: float | None  # now - last_available_at (alt) / now - last_ts (bars)
    cadence_seconds: float | None  # median ts delta (None if < 2 rows)
    gaps: int  # number of inter-bar intervals wider than 1.5× cadence
    missing_buckets: int  # estimated count of absent buckets across all gaps
    max_gap_seconds: float | None
    lookahead_violations: int  # rows with available_at < ts (a point-in-time leak)
    status: str  # "missing" | "lookahead" | "stale" | "gappy" | "ok"

    @property
    def span_days(self) -> float:
        if self.first_ts is None or self.last_ts is None:
            return 0.0
        return (self.last_ts - self.first_ts).total_seconds() / 86400.0


@dataclass(frozen=True)
class CoverageReport:
    """The full coverage snapshot across every expected series, with text + machine-readable renderings."""

    generated_at: datetime
    series: list[SeriesCoverage] = field(default_factory=list)

    def summary(self) -> dict[str, int]:
        counts = {"ok": 0, "stale": 0, "gappy": 0, "missing": 0, "lookahead": 0}
        for s in self.series:
            counts[s.status] = counts.get(s.status, 0) + 1
        counts["total"] = len(self.series)
        return counts

    def by_status(self, status: str) -> list[SeriesCoverage]:
        return [s for s in self.series if s.status == status]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "summary": self.summary(),
            "series": [
                {
                    "provider": s.provider, "symbol": s.symbol, "metric": s.metric, "kind": s.kind,
                    "rows": s.rows, "status": s.status,
                    "first_ts": s.first_ts.isoformat() if s.first_ts else None,
                    "last_ts": s.last_ts.isoformat() if s.last_ts else None,
                    "span_days": round(s.span_days, 1),
                    "freshness_seconds": s.freshness_seconds,
                    "cadence_seconds": s.cadence_seconds,
                    "gaps": s.gaps, "missing_buckets": s.missing_buckets,
                    "max_gap_seconds": s.max_gap_seconds,
                    "lookahead_violations": s.lookahead_violations,
                }
                for s in self.series
            ],
        }

    def to_text(self) -> str:
        c = self.summary()
        lines = [
            "DATA COVERAGE — what we have / what's stale / what's missing",
            f"  as of {self.generated_at.isoformat()}",
            f"  {c['total']} series: {c['ok']} ok · {c['stale']} stale · {c['gappy']} gappy · "
            f"{c['missing']} missing · {c['lookahead']} look-ahead",
            "",
            f"  {'status':<9}{'provider':<16}{'symbol':<18}{'metric':<30}{'rows':>7}{'days':>7}  span / note",
        ]
        order = {"missing": 0, "lookahead": 1, "stale": 2, "gappy": 3, "ok": 4}
        for s in sorted(self.series, key=lambda x: (order.get(x.status, 9), x.provider, x.symbol, x.metric)):
            if s.first_ts and s.last_ts:
                note = f"{s.first_ts.date()} → {s.last_ts.date()}"
            else:
                note = "(no data)"
            if s.status == "lookahead":
                note += f"  ⚠ {s.lookahead_violations} available_at<ts"
            elif s.status == "gappy":
                note += f"  ⚠ {s.gaps} gaps / ~{s.missing_buckets} missing buckets"
            elif s.status == "stale" and s.freshness_seconds is not None:
                note += f"  ⚠ {s.freshness_seconds / 86400:.1f}d old"
            lines.append(
                f"  {s.status:<9}{s.provider:<16}{s.symbol:<18}{s.metric:<30}{s.rows:>7}{s.span_days:>7.0f}  {note}"
            )
        return "\n".join(lines)


def _gap_stats(timestamps: list[datetime]) -> tuple[float | None, int, int, float | None]:
    """From ascending unique ts → (cadence_seconds, gaps, missing_buckets, max_gap_seconds). The cadence is
    the MEDIAN consecutive delta (robust to a few wide holes); a gap is any interval > 1.5× cadence, and
    missing_buckets estimates how many buckets fell out across all gaps. < 2 points → no cadence."""
    if len(timestamps) < 2:
        return None, 0, 0, None
    deltas = [
        (timestamps[i] - timestamps[i - 1]).total_seconds()
        for i in range(1, len(timestamps))
        if (timestamps[i] - timestamps[i - 1]).total_seconds() > 0
    ]
    if not deltas:
        return None, 0, 0, None
    cadence = statistics.median(deltas)
    gaps = 0
    missing = 0
    for d in deltas:
        if cadence > 0 and d > 1.5 * cadence:
            gaps += 1
            missing += max(0, round(d / cadence) - 1)
    return cadence, gaps, missing, max(deltas)


def _status(rows: int, lookahead: int, freshness: float | None, cadence: float | None, gaps: int, stale_after: int) -> str:
    """Status precedence: missing > look-ahead leak > stale > gappy > ok. Stale floors at `stale_after` but
    also trips at 3× the series' own cadence, so a fast series isn't judged by a slow series' threshold."""
    if rows == 0:
        return "missing"
    if lookahead > 0:
        return "lookahead"
    if freshness is not None:
        threshold = max(stale_after, 3 * cadence) if cadence else stale_after
        if freshness > threshold:
            return "stale"
    if gaps > 0:
        return "gappy"
    return "ok"


def series_coverage(
    points: list[Any],  # list[AltDataPoint] — has .ts, .available_at, .value
    *,
    provider: str,
    symbol: str,
    metric: str,
    now: datetime,
    kind: str = "alt",
    stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
) -> SeriesCoverage:
    """Health of one alt series from its full point-in-time history (collapse revisions to latest-per-ts so
    the row count is genuine observations, not the revision trail). Look-ahead check: any row whose
    `available_at` precedes its `ts` is a leak (the value would be 'known' before it was observed)."""
    # Collapse revisions: keep the newest available_at per ts (mirrors read_asof's latest-wins).
    latest_by_ts: dict[datetime, Any] = {}
    lookahead = 0
    for p in points:
        if p.available_at < p.ts:
            lookahead += 1
        prev = latest_by_ts.get(p.ts)
        if prev is None or p.available_at >= prev.available_at:
            latest_by_ts[p.ts] = p
    observations = sorted(latest_by_ts.values(), key=lambda x: x.ts)
    rows = len(observations)
    first_ts = observations[0].ts if observations else None
    last_ts = observations[-1].ts if observations else None
    last_avail = max((o.available_at for o in observations), default=None)
    freshness = (now - last_avail).total_seconds() if last_avail else None
    cadence, gaps, missing, max_gap = _gap_stats([o.ts for o in observations])
    status = _status(rows, lookahead, freshness, cadence, gaps, stale_after_seconds)
    return SeriesCoverage(
        provider=provider, symbol=symbol, metric=metric, kind=kind, rows=rows,
        first_ts=first_ts, last_ts=last_ts, last_available_at=last_avail,
        freshness_seconds=freshness, cadence_seconds=cadence, gaps=gaps,
        missing_buckets=missing, max_gap_seconds=max_gap, lookahead_violations=lookahead, status=status,
    )


def bar_coverage(
    bars: list[Any],  # list[Bar] — has .ts
    *,
    venue: str,
    symbol: str,
    timeframe: str,
    now: datetime,
    stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
) -> SeriesCoverage:
    """Health of one cached bar series. Bars carry no `available_at` (a closed bar IS known at its close),
    so there is no look-ahead axis; freshness is measured against the last bar's close time."""
    ts = sorted({b.ts for b in bars})
    rows = len(ts)
    first_ts = ts[0] if ts else None
    last_ts = ts[-1] if ts else None
    freshness = (now - last_ts).total_seconds() if last_ts else None
    cadence, gaps, missing, max_gap = _gap_stats(ts)
    status = _status(rows, 0, freshness, cadence, gaps, stale_after_seconds)
    return SeriesCoverage(
        provider=venue, symbol=symbol, metric=f"bars:{timeframe}", kind="bars", rows=rows,
        first_ts=first_ts, last_ts=last_ts, last_available_at=last_ts,
        freshness_seconds=freshness, cadence_seconds=cadence, gaps=gaps,
        missing_buckets=missing, max_gap_seconds=max_gap, lookahead_violations=0, status=status,
    )


def build_alt_coverage(
    store: Any,  # AltDataStore | PgAltDataStore — must expose read_all(provider, symbol, metric)
    specs: list[tuple[str, str, str]],  # (provider, symbol, metric)
    *,
    now: datetime,
    stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
) -> list[SeriesCoverage]:
    """Read each expected (provider, symbol, metric) from the store and score it. A series the store has no
    rows for comes back `missing` — that is the point: the report names the holes, not just the fills."""
    out: list[SeriesCoverage] = []
    for provider, symbol, metric in specs:
        try:
            points = store.read_all(provider, symbol, metric)
        except Exception:  # noqa: BLE001 — a store read failure must not abort the whole report
            points = []
        out.append(
            series_coverage(
                points, provider=provider, symbol=symbol, metric=metric,
                now=now, stale_after_seconds=stale_after_seconds,
            )
        )
    return out


def build_bar_coverage(
    market_data_dir: Path | str,
    specs: list[tuple[str, str, str]],  # (venue, symbol, timeframe)
    *,
    now: datetime,
    stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
) -> list[SeriesCoverage]:
    """Score each expected (venue, symbol, timeframe) bar series from its on-disk cache under
    `<market_data_dir>/<venue>/<symbol>_<tf>.json`. A missing cache file → a `missing` series."""
    out: list[SeriesCoverage] = []
    base = Path(market_data_dir)
    for venue, symbol, timeframe in specs:
        bars = read_cached_bars(bar_cache_path(base / venue, symbol, timeframe))
        out.append(
            bar_coverage(
                bars, venue=venue, symbol=symbol, timeframe=timeframe,
                now=now, stale_after_seconds=stale_after_seconds,
            )
        )
    return out


def build_panel_coverage(
    panel_dir: Path | str,
    specs: list[tuple[str, str]],  # (symbol, timeframe)
    *,
    now: datetime,
    stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
) -> list[SeriesCoverage]:
    """Score each expected (symbol, timeframe) ML panel from its on-disk store. A panel's rows carry a `ts` and
    `available_at` (== bar close), so the SAME PIT/freshness/gap machinery applies: an absent panel → `missing`,
    and the look-ahead check still holds (available_at >= ts). Reuses `series_coverage` — the panel is just a
    grid of standardized rows, judged like any other series."""
    from cosmu.ingest.ml_panel import read_ml_panel

    out: list[SeriesCoverage] = []
    for symbol, timeframe in specs:
        panel = read_ml_panel(panel_dir, symbol, timeframe)
        rows = panel.rows if panel else []
        out.append(
            series_coverage(
                rows, provider="ml_panel", symbol=symbol, metric=f"panel:{timeframe}",
                now=now, kind="panel", stale_after_seconds=stale_after_seconds,
            )
        )
    return out
