#!/usr/bin/env python3
# intent: read-only data-coverage bottleneck report — for each asset class and source, show rows/symbols
# present, date span, gaps, and staleness (most-recent vs now), pulling from the configured store + the local
# bar cache; degrades gracefully when empty (prints "EMPTY" honestly, never fabricates); a --json flag emits
# machine-readable output; offline-safe (no live network; reads only from the local stores). This is the
# "data bottleneck" diagnostic: which symbols have bars, which alt series are populated, and how far back
# each goes.
#
# Run (from the repo root):
#   PYTHONPATH=apps/engine python3 scripts/data_coverage.py
#   PYTHONPATH=apps/engine python3 scripts/data_coverage.py --symbols BTCUSDT,ETHUSDT
#   PYTHONPATH=apps/engine python3 scripts/data_coverage.py --json
#   PYTHONPATH=apps/engine python3 scripts/data_coverage.py --no-bars

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Allow `python3 scripts/data_coverage.py` without an explicit PYTHONPATH.
_ENGINE = Path(__file__).resolve().parents[1] / "apps" / "engine"
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _fmt_days(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    return f"{seconds / 86400:.0f}d"


def _fmt_freshness(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    d = seconds / 86400
    if d < 1:
        return f"{seconds / 3600:.1f}h ago"
    return f"{d:.1f}d ago"


def _symbols_from_arg(arg: str) -> list[str]:
    """Parse --symbols (comma-separated) or fall back to the perp universe."""
    if arg:
        return [s.strip() for s in arg.split(",") if s.strip()]
    from cosmu.data.universe import perp_universe

    return perp_universe()


# ---------------------------------------------------------------------------
# Per-source rollup: aggregate the per-(provider,symbol,metric) SeriesCoverage
# rows into a human-readable group summary


def _rollup_by_source(series: list[Any]) -> dict[str, dict[str, Any]]:
    """Group SeriesCoverage rows into source-level rollup keyed by provider.
    Returns {provider: {rows_total, symbols_with_data, symbols_empty, span_days_max,
    freshness_seconds_min, gaps_total, status_counts, metrics_covered}}."""
    from collections import defaultdict

    groups: dict[str, list[Any]] = defaultdict(list)
    for s in series:
        groups[s.provider].append(s)

    out: dict[str, dict[str, Any]] = {}
    for provider, items in sorted(groups.items()):
        rows_total = sum(i.rows for i in items)
        symbols_with_data = len({i.symbol for i in items if i.rows > 0})
        symbols_empty = len({i.symbol for i in items if i.rows == 0})
        metrics_covered = sorted({i.metric for i in items if i.rows > 0})

        span_days_max = max((i.span_days for i in items if i.rows > 0), default=0.0)

        fresh_vals = [i.freshness_seconds for i in items if i.freshness_seconds is not None and i.rows > 0]
        freshness_min = min(fresh_vals) if fresh_vals else None  # best (most recent) freshness

        gaps_total = sum(i.gaps for i in items)
        missing_buckets = sum(i.missing_buckets for i in items)

        status_counts: dict[str, int] = {}
        for i in items:
            status_counts[i.status] = status_counts.get(i.status, 0) + 1

        first_ts = min((i.first_ts for i in items if i.first_ts is not None), default=None)
        last_ts = max((i.last_ts for i in items if i.last_ts is not None), default=None)

        out[provider] = {
            "rows_total": rows_total,
            "symbols_with_data": symbols_with_data,
            "symbols_empty": symbols_empty,
            "metrics_covered": metrics_covered,
            "span_days_max": round(span_days_max, 1),
            "freshness_seconds_min": freshness_min,
            "gaps_total": gaps_total,
            "missing_buckets": missing_buckets,
            "status_counts": status_counts,
            "first_ts": first_ts.isoformat() if first_ts else None,
            "last_ts": last_ts.isoformat() if last_ts else None,
        }
    return out


def _rollup_bars(series: list[Any]) -> dict[str, Any]:
    """Roll up bar-kind series into a summary by (venue, timeframe) then by venue."""
    from collections import defaultdict

    by_venue_tf: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for s in series:
        tf = s.metric.split(":", 1)[1] if ":" in s.metric else s.metric
        by_venue_tf[(s.provider, tf)].append(s)

    out: dict[str, Any] = {}
    for (venue, tf), items in sorted(by_venue_tf.items()):
        key = f"{venue}/{tf}"
        populated = [i for i in items if i.rows > 0]
        empty = [i for i in items if i.rows == 0]
        span_max = max((i.span_days for i in populated), default=0.0)
        fresh_vals = [i.freshness_seconds for i in populated if i.freshness_seconds is not None]
        freshness_min = min(fresh_vals) if fresh_vals else None
        gaps_total = sum(i.gaps for i in populated)
        status_counts: dict[str, int] = {}
        for i in items:
            status_counts[i.status] = status_counts.get(i.status, 0) + 1

        first_ts = min((i.first_ts for i in populated if i.first_ts), default=None)
        last_ts = max((i.last_ts for i in populated if i.last_ts), default=None)

        out[key] = {
            "venue": venue,
            "timeframe": tf,
            "symbols_with_data": len(populated),
            "symbols_empty": len(empty),
            "symbols_populated": sorted(i.symbol for i in populated),
            "rows_total": sum(i.rows for i in populated),
            "span_days_max": round(span_max, 1),
            "freshness_seconds_min": freshness_min,
            "gaps_total": gaps_total,
            "status_counts": status_counts,
            "first_ts": first_ts.isoformat() if first_ts else None,
            "last_ts": last_ts.isoformat() if last_ts else None,
        }
    return out


# ---------------------------------------------------------------------------
# Text rendering


def _render_text(
    alt_rollup: dict[str, dict[str, Any]],
    bar_rollup: dict[str, Any],
    now: datetime,
    symbols: list[str],
    raw_report: Any,
) -> str:
    lines: list[str] = []
    summary = raw_report.summary()
    lines += [
        "DATA COVERAGE REPORT — data bottleneck diagnostic",
        f"  generated {now.isoformat()}",
        f"  symbols ({len(symbols)}): {', '.join(symbols[:8])}{'...' if len(symbols) > 8 else ''}",
        f"  series total {summary['total']}: "
        f"{summary['ok']} ok  {summary['stale']} stale  "
        f"{summary['gappy']} gappy  {summary['missing']} missing  "
        f"{summary['lookahead']} look-ahead",
        "",
    ]

    # --- BARS section ---
    lines.append("BAR CACHE  (on-disk OHLCV, venue/timeframe)")
    lines.append(f"  {'venue/tf':<22}{'populated':>10}{'empty':>7}{'rows':>10}{'span':>8}{'freshness':>14}  status")
    if not bar_rollup:
        lines.append("  EMPTY — no bar cache present")
    else:
        for key, r in sorted(bar_rollup.items()):
            pop = r["symbols_with_data"]
            emp = r["symbols_empty"]
            rows = r["rows_total"]
            span = _fmt_days(r["span_days_max"] * 86400) if r["span_days_max"] else "EMPTY"
            fresh = _fmt_freshness(r["freshness_seconds_min"])
            sc = r["status_counts"]
            status_str = "  ".join(f"{st}:{n}" for st, n in sorted(sc.items()))
            lines.append(f"  {key:<22}{pop:>10}{emp:>7}{rows:>10}{span:>8}{fresh:>14}  {status_str}")
    lines.append("")

    # --- ALT DATA section ---
    lines.append("ALT DATA  (provider, by source)")
    lines.append(f"  {'provider':<18}{'syms_ok':>8}{'syms_empty':>11}{'rows':>10}{'span':>8}{'freshness':>14}  metrics_covered")
    if not alt_rollup:
        lines.append("  EMPTY — no alt-data store present")
    else:
        for provider, r in alt_rollup.items():
            ok = r["symbols_with_data"]
            emp = r["symbols_empty"]
            rows = r["rows_total"]
            span = _fmt_days(r["span_days_max"] * 86400) if r["span_days_max"] else "EMPTY"
            fresh = _fmt_freshness(r["freshness_seconds_min"])
            metrics = ", ".join(r["metrics_covered"][:4]) + ("..." if len(r["metrics_covered"]) > 4 else "")
            if ok == 0:
                metrics = "EMPTY"
            lines.append(f"  {provider:<18}{ok:>8}{emp:>11}{rows:>10}{span:>8}{fresh:>14}  {metrics}")

    lines.append("")

    # --- MISSING / STALE highlights ---
    missing = raw_report.by_status("missing")
    stale = raw_report.by_status("stale")
    lookahead = raw_report.by_status("lookahead")
    if missing:
        lines.append(f"MISSING ({len(missing)} series)  — run backfill to populate")
        for s in sorted(missing, key=lambda x: (x.provider, x.symbol, x.metric))[:20]:
            lines.append(f"  {s.provider:<16}{s.symbol:<20}{s.metric}")
        if len(missing) > 20:
            lines.append(f"  ... and {len(missing) - 20} more")
        lines.append("")
    if stale:
        lines.append(f"STALE ({len(stale)} series)  — consider update/re-fetch")
        for s in sorted(stale, key=lambda x: x.freshness_seconds or 0, reverse=True)[:10]:
            fresh = _fmt_freshness(s.freshness_seconds)
            lines.append(f"  {s.provider:<16}{s.symbol:<20}{s.metric:<30}  last seen {fresh}")
        if len(stale) > 10:
            lines.append(f"  ... and {len(stale) - 10} more")
        lines.append("")
    if lookahead:
        lines.append(f"LOOK-AHEAD VIOLATIONS ({len(lookahead)} series)  — point-in-time breach")
        for s in lookahead[:10]:
            lines.append(f"  {s.provider:<16}{s.symbol:<20}{s.metric}  {s.lookahead_violations} rows")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON rendering


def _render_json(
    alt_rollup: dict[str, dict[str, Any]],
    bar_rollup: dict[str, Any],
    now: datetime,
    symbols: list[str],
    raw_report: Any,
) -> str:
    doc = {
        "generated_at": now.isoformat(),
        "symbols": symbols,
        "summary": raw_report.summary(),
        "bars": bar_rollup,
        "alt_data": alt_rollup,
        "series_detail": raw_report.to_dict()["series"],
    }
    return json.dumps(doc, indent=2)


# ---------------------------------------------------------------------------
# Store + manager wiring


def _build_manager(
    *,
    market_data_dir: str | None,
    panel_dir: str | None,
    store: Any = None,
    clock: Any = None,
) -> Any:
    """Build a DataManager wired to the local stores.  `store` and `clock` are
    injectable for tests; omit both for the live (production-local) path."""
    from cosmu.ingest.manage import DEFAULT_MARKET_DATA_DIR, DEFAULT_PANEL_DIR, DataManager

    return DataManager(
        store=store,  # None = lazy default (Postgres or JSONL)
        market_data_dir=market_data_dir or DEFAULT_MARKET_DATA_DIR,
        panel_dir=panel_dir or DEFAULT_PANEL_DIR,
        clock=clock or _now,
    )


# ---------------------------------------------------------------------------
# Main


def run_coverage(
    symbols: list[str],
    *,
    timeframes: tuple[str, ...] | None = None,
    include_bars: bool = True,
    include_panels: bool = False,
    market_data_dir: str | None = None,
    panel_dir: str | None = None,
    store: Any = None,
    clock: Any = None,
    as_json: bool = False,
) -> str:
    """Compute and render the coverage report.  All parameters are injectable for
    tests (pass `store`, `clock`).  Returns the formatted string."""
    from cosmu.ingest.catalog import DEFAULT_BAR_TIMEFRAMES

    tfs = timeframes or DEFAULT_BAR_TIMEFRAMES
    mgr = _build_manager(
        market_data_dir=market_data_dir,
        panel_dir=panel_dir,
        store=store,
        clock=clock,
    )
    report = mgr.verify(
        symbols,
        timeframes=tfs,
        include_bars=include_bars,
        include_panels=include_panels,
    )

    now = (clock or _now)()
    alt_series = [s for s in report.series if s.kind == "alt"]
    bar_series = [s for s in report.series if s.kind == "bars"]

    alt_rollup = _rollup_by_source(alt_series)
    bar_rollup = _rollup_bars(bar_series)

    if as_json:
        return _render_json(alt_rollup, bar_rollup, now, symbols, report)
    return _render_text(alt_rollup, bar_rollup, now, symbols, report)


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="data-coverage",
        description="Read-only data bottleneck report — rows/symbols/span/gaps/staleness per source.",
    )
    parser.add_argument("--symbols", default="", help="comma-separated symbols (default: perp universe)")
    parser.add_argument("--timeframe", default="", help="comma-separated timeframes (default: 1d,4h,1h)")
    parser.add_argument("--no-bars", action="store_true", help="skip bar-cache coverage")
    parser.add_argument("--panels", action="store_true", help="include ML-panel coverage")
    parser.add_argument("--json", action="store_true", dest="as_json", help="emit JSON instead of text")
    parser.add_argument(
        "--market-data-dir", default="", help="override market-data dir (default: .cosmu/market_data)"
    )
    args = parser.parse_args(argv)

    symbols = _symbols_from_arg(args.symbols)
    tfs_raw = [t.strip() for t in args.timeframe.split(",") if t.strip()] if args.timeframe else None

    output = run_coverage(
        symbols,
        timeframes=tuple(tfs_raw) if tfs_raw else None,
        include_bars=not args.no_bars,
        include_panels=args.panels,
        market_data_dir=args.market_data_dir or None,
        as_json=args.as_json,
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
