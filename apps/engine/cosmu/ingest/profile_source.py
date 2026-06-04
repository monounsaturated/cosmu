# intent: DATA-TRUST AUDIT for a NEW alt-data source — auto-profile its full point-in-time history (coverage ·
# gaps · staleness · look-ahead · PIT-lag honesty · revision safety) into a single GO / REVIEW / NO-GO verdict, so
# an untrusted feed is vetted BEFORE it is wired into the feature registry and allowed to influence a gate. inputs:
# the source's full AltDataPoint history (read_all) + a declared availability lag (from its as-of semantics) + the
# now-clock + tunable thresholds; outputs: a deterministic SourceProfile (per-check results + overall verdict +
# plain reasons). invariants: PURE + offline + deterministic (the clock is injected, never wall-time) + read-only
# (never mutates a store) + REVIEW-ONLY (it only RECOMMENDS go/no-go; a human still wires the source). It composes
# ingest/coverage.py — it does NOT re-implement gap/staleness/look-ahead detection. A point-in-time leak
# (available_at < ts) or a source that CLAIMS data sooner than its declared release lag is a hard NO-GO: a feed the
# gate cannot trust point-in-time must never become a feature.

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from cosmu.ingest.coverage import SeriesCoverage, series_coverage

# Audit thresholds — policy constants for vetting a NEW feed (NOT strategy params: this never enters a spec, so
# the "no magic numbers in a spec" rule is untouched). A feed must clear depth to have earned an out-of-sample
# opinion, must not be mostly holes, must be fresh, and must be point-in-time honest.
MIN_ROWS = 60                       # too few observations → can't judge an edge out-of-sample yet
MIN_SPAN_DAYS = 30.0                # too short a history → no regime coverage
MAX_GAP_RATIO = 0.10                # missing_buckets / expected buckets above this → too holey to trust
PIT_LAG_TOLERANCE = 0.5             # observed median lag below this fraction of the declared lag → PIT red flag


@dataclass(frozen=True)
class CheckResult:
    """One audit check's outcome. `severity` ranks how a failure bites: 'hard' forces NO-GO, 'soft' forces
    REVIEW, 'info' never blocks. `passed` is the check's own pass/fail; the verdict is rolled up from these."""

    name: str
    passed: bool
    severity: str  # "hard" | "soft" | "info"
    detail: str


@dataclass(frozen=True)
class SourceProfile:
    """The data-trust verdict for one (provider, symbol, metric): the underlying coverage, the PIT-lag analytics,
    every audit check, and the rolled-up GO / REVIEW / NO-GO with plain reasons."""

    provider: str
    symbol: str
    metric: str
    verdict: str  # "GO" | "REVIEW" | "NO-GO"
    coverage: SeriesCoverage
    declared_lag_seconds: float | None
    observed_median_lag_seconds: float | None
    revision_count: int
    checks: tuple[CheckResult, ...]
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "symbol": self.symbol,
            "metric": self.metric,
            "verdict": self.verdict,
            "declared_lag_seconds": self.declared_lag_seconds,
            "observed_median_lag_seconds": self.observed_median_lag_seconds,
            "revision_count": self.revision_count,
            "coverage": {
                "rows": self.coverage.rows,
                "span_days": round(self.coverage.span_days, 1),
                "status": self.coverage.status,
                "gaps": self.coverage.gaps,
                "missing_buckets": self.coverage.missing_buckets,
                "lookahead_violations": self.coverage.lookahead_violations,
                "freshness_seconds": self.coverage.freshness_seconds,
                "cadence_seconds": self.coverage.cadence_seconds,
            },
            "checks": [
                {"name": c.name, "passed": c.passed, "severity": c.severity, "detail": c.detail}
                for c in self.checks
            ],
            "reasons": list(self.reasons),
        }

    def to_text(self) -> str:
        lines = [
            f"DATA-TRUST AUDIT — {self.provider} / {self.symbol} / {self.metric}",
            f"  VERDICT: {self.verdict}",
            "",
        ]
        for c in self.checks:
            mark = "✓" if c.passed else ("✗" if c.severity == "hard" else "⚠")
            lines.append(f"  {mark} {c.name:<18}[{c.severity}]  {c.detail}")
        if self.reasons:
            lines.append("")
            lines.append("  why: " + "; ".join(self.reasons))
        return "\n".join(lines)


def _lag_seconds(points: list[Any]) -> list[float]:
    """Availability lag (available_at − ts) in seconds for every raw point — the empirical 'how long after the
    observation did we actually know it' distribution. Negative entries are point-in-time leaks."""
    return [(p.available_at - p.ts).total_seconds() for p in points]


def _gap_ratio(cov: SeriesCoverage) -> float | None:
    """missing_buckets / (observed + missing) — the fraction of the expected grid that is absent. None when the
    cadence is undefined (< 2 rows)."""
    if cov.cadence_seconds is None or cov.rows < 2:
        return None
    expected = cov.rows + cov.missing_buckets
    return cov.missing_buckets / expected if expected > 0 else 0.0


def profile_points(
    points: list[Any],  # list[AltDataPoint] — .ts, .available_at, .value
    *,
    provider: str,
    symbol: str,
    metric: str,
    now: datetime,
    declared_lag_seconds: float | None = None,
    min_rows: int = MIN_ROWS,
    min_span_days: float = MIN_SPAN_DAYS,
    max_gap_ratio: float = MAX_GAP_RATIO,
    pit_lag_tolerance: float = PIT_LAG_TOLERANCE,
) -> SourceProfile:
    """Profile one source's full point-in-time history into a GO / REVIEW / NO-GO data-trust verdict. Composes
    coverage.series_coverage for rows/span/freshness/gaps/look-ahead, then adds the two checks coverage can't make
    about a NEW feed: (1) PIT-LAG HONESTY — if the feed DECLARES a release lag (e.g. next-day) but its observed
    median availability lag is far smaller, the ingest is stamping availability too early and a look-ahead leak is
    waiting to happen → hard NO-GO; (2) REVISION SAFETY — many silent same-ts revisions mean the vendor rewrites
    history, which is only safe behind the append-only PIT store → REVIEW. A real look-ahead violation, an empty
    feed, or a dishonest PIT lag is a hard NO-GO; shallow/holey/stale/heavily-revised is REVIEW; otherwise GO."""
    cov = series_coverage(points, provider=provider, symbol=symbol, metric=metric, now=now)
    lags = _lag_seconds(points)
    median_lag = statistics.median(lags) if lags else None
    # Revisions = raw points beyond one-per-ts (the vendor re-stated a timestamp we already had).
    revision_count = len(points) - len({p.ts for p in points})

    checks: list[CheckResult] = []

    # 1) Coverage depth — enough observations + long enough history to have an out-of-sample opinion.
    deep = cov.rows >= min_rows and cov.span_days >= min_span_days
    checks.append(CheckResult(
        "coverage_depth", deep, "soft",
        f"{cov.rows} rows over {cov.span_days:.0f}d (need ≥ {min_rows} rows, ≥ {min_span_days:.0f}d)",
    ))

    # 2) Gaps — not mostly holes.
    ratio = _gap_ratio(cov)
    gaps_ok = ratio is None or ratio <= max_gap_ratio
    checks.append(CheckResult(
        "gaps", gaps_ok, "soft",
        f"{cov.gaps} gaps / ~{cov.missing_buckets} missing buckets"
        + (f" ({ratio:.0%} of grid)" if ratio is not None else " (cadence undefined)"),
    ))

    # 3) Staleness — the freshest point is recent (coverage.status already encodes the 3d / 3×cadence floor).
    fresh = cov.status != "stale"
    fresh_detail = (
        f"{cov.freshness_seconds / 86400:.1f}d since last availability" if cov.freshness_seconds is not None else "no data"
    )
    checks.append(CheckResult("staleness", fresh, "soft", fresh_detail))

    # 4) Look-ahead — HARD. Any available_at < ts is a point-in-time leak the gate must never see.
    no_leak = cov.lookahead_violations == 0
    checks.append(CheckResult(
        "look_ahead", no_leak, "hard",
        f"{cov.lookahead_violations} rows with available_at < ts" if not no_leak else "no available_at < ts",
    ))

    # 5) PIT-lag honesty — HARD. A feed that DECLARES a release lag but is stamped available much sooner is a
    # latent look-ahead leak (it will let a backtest read values before they were really published).
    if declared_lag_seconds is not None and declared_lag_seconds > 0 and median_lag is not None:
        honest = median_lag >= pit_lag_tolerance * declared_lag_seconds
        checks.append(CheckResult(
            "pit_lag", honest, "hard",
            f"observed median lag {median_lag / 3600:.1f}h vs declared {declared_lag_seconds / 3600:.1f}h"
            + ("" if honest else " — stamped available SOONER than its declared release (leak risk)"),
        ))
    else:
        checks.append(CheckResult(
            "pit_lag", True, "info",
            "no declared release lag to check (availability == observation, or not supplied)"
            if median_lag is not None else "no data",
        ))

    # 6) Revision safety — many silent same-ts revisions mean the vendor rewrites history.
    revisions_ok = revision_count <= max(1, cov.rows // 10)
    checks.append(CheckResult(
        "revision_safety", revisions_ok, "soft",
        f"{revision_count} same-ts revisions (vendor restates history)"
        + ("" if revisions_ok else " — only safe behind the append-only PIT store"),
    ))

    # Roll up: any hard failure → NO-GO; else any soft failure → REVIEW; else GO. An empty feed is NO-GO.
    hard_fails = [c for c in checks if not c.passed and c.severity == "hard"]
    soft_fails = [c for c in checks if not c.passed and c.severity == "soft"]
    if cov.rows == 0:
        verdict = "NO-GO"
        reasons = ("no data — nothing to trust",)
    elif hard_fails:
        verdict = "NO-GO"
        reasons = tuple(c.detail for c in hard_fails)
    elif soft_fails:
        verdict = "REVIEW"
        reasons = tuple(c.detail for c in soft_fails)
    else:
        verdict = "GO"
        reasons = ("clean: deep, fresh, dense, point-in-time honest",)

    return SourceProfile(
        provider=provider, symbol=symbol, metric=metric, verdict=verdict, coverage=cov,
        declared_lag_seconds=declared_lag_seconds, observed_median_lag_seconds=median_lag,
        revision_count=revision_count, checks=tuple(checks), reasons=reasons,
    )


def profile_source(
    store: Any,  # AltDataStore | PgAltDataStore — must expose read_all(provider, symbol, metric)
    provider: str,
    symbol: str,
    metric: str,
    *,
    now: datetime,
    declared_lag_seconds: float | None = None,
    **thresholds: Any,
) -> SourceProfile:
    """Read one source's full point-in-time history from the store and profile it. A store the feed has no rows
    for comes back NO-GO ('no data') — the audit names the hole, it does not silently pass an empty feed."""
    try:
        points = store.read_all(provider, symbol, metric)
    except Exception:  # noqa: BLE001 — a store read failure must not crash the audit; report it as no data
        points = []
    return profile_points(
        points, provider=provider, symbol=symbol, metric=metric, now=now,
        declared_lag_seconds=declared_lag_seconds, **thresholds,
    )


# --- CLI (review-only; prints the go/no-go, wires nothing) -----------------------------------------


def _main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    from pathlib import Path

    from cosmu.data.altdata import AltDataStore
    from cosmu.knowledge.store import utcnow

    parser = argparse.ArgumentParser(
        description="Data-trust audit for a new alt-source: coverage · gaps · staleness · look-ahead · PIT-lag → "
        "GO / REVIEW / NO-GO. Review-only; wires nothing into the feature registry."
    )
    parser.add_argument("provider")
    parser.add_argument("symbol")
    parser.add_argument("metric")
    parser.add_argument("--altdata-root", default=".cosmu/altdata", help="AltDataStore root (default .cosmu/altdata)")
    parser.add_argument("--declared-lag-hours", type=float, default=None, help="declared release lag in hours (from the source's as-of semantics)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)

    store = AltDataStore(Path(args.altdata_root))
    declared = args.declared_lag_hours * 3600 if args.declared_lag_hours is not None else None
    profile = profile_source(store, args.provider, args.symbol, args.metric, now=utcnow(), declared_lag_seconds=declared)
    print(json.dumps(profile.to_dict(), indent=2) if args.json else profile.to_text())
    # Exit non-zero on NO-GO so the audit can gate a script/CI step without parsing stdout.
    return 0 if profile.verdict != "NO-GO" else 1


if __name__ == "__main__":
    raise SystemExit(_main())
