# intent: ALPHA-DECAY as a first-class primitive — estimate each funded track's EDGE HALF-LIFE and detect
# live-vs-funded DRIFT early, so capital is pulled BEFORE realized P&L turns negative (the existing rotation
# defund is reactive: it waits for the deflated-Sharpe snapshot to cross a floor). inputs: a realized per-period
# net-return series (derived from portfolio_snapshots) + the edge the track was funded on (its own funded
# baseline, or an explicit per-period backtest edge when one in matching units is supplied). outputs: a
# deterministic DriftVerdict per funded track (half_life, drift z-score, one-sided CUSUM change-point, defund +
# plain reason). invariants: fully deterministic + OUT of any LLM path (this is master/, the immovable core),
# seed-free, offline, anticipatory (fires while realized edge is still positive but trending to zero / materially
# below what it was funded on), and it only RECOMMENDS defunding — money still moves through the deterministic
# order path under the live toggle. Threshold defaults are policy constants (like rotation.py's min_dsr/kelly_cap),
# not strategy params, so the "no magic numbers in a spec" rule is untouched.

from __future__ import annotations

import math
from dataclasses import dataclass

from cosmu.knowledge.store import Store


@dataclass(frozen=True)
class EdgeDecay:
    """The intrinsic decay of a track's realized rolling edge — scale-free, anticipatory."""

    n: int
    current_edge: float            # fitted rolling edge at the latest point
    slope: float                   # OLS slope of rolling-edge vs period index (edge change per period)
    half_life: float | None        # periods for the current edge to halve at the current decay rate; None if not decaying
    periods_to_zero: float | None  # linear projection of periods until the edge hits zero; None if not decaying


@dataclass(frozen=True)
class DriftScore:
    """How far live results have drifted below the edge the track was funded on."""

    n: int
    realized_edge: float           # mean realized per-period net return
    reference_edge: float          # the edge it was funded on (funded baseline or explicit backtest edge)
    reference: str                 # "funded-baseline" | "backtest" — which reference was used (honest about units)
    z: float                       # standardized shortfall: (realized - reference)/SE; strongly negative = live << funded
    cusum: float                   # peak of the one-sided lower CUSUM (std units); large = persistent underperformance
    cusum_alarm: bool


@dataclass(frozen=True)
class DriftVerdict:
    ref_id: str
    defund: bool
    reason: str
    decay: EdgeDecay
    drift: DriftScore


# --- pure analytics (no I/O, deterministic) --------------------------------------------------------


def rolling_edge(series: list[float], *, window: int = 5) -> list[float]:
    """Smooth a noisy per-period return series into a rolling-mean edge trajectory whose downward slope is the
    alpha-decay signal. Series shorter than `window` collapses to a single expanding mean."""
    s = [float(x) for x in series]
    if not s:
        return []
    if len(s) < window:
        return [sum(s) / len(s)]
    return [sum(s[i - window + 1 : i + 1]) / window for i in range(window - 1, len(s))]


def fit_edge_decay(edge_series: list[float]) -> EdgeDecay:
    """OLS-fit the rolling edge against time. A negative slope with a positive current edge => the edge is
    decaying toward zero; report a linear periods-to-zero projection and the exponential-equivalent half-life at
    the current decay rate. A flat/rising series (or one already non-positive) => no finite half-life (None)."""
    s = [float(x) for x in edge_series]
    n = len(s)
    if n < 3:
        return EdgeDecay(n=n, current_edge=(s[-1] if s else 0.0), slope=0.0, half_life=None, periods_to_zero=None)
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(s) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, s))
    slope = sxy / sxx if sxx > 0 else 0.0
    current = (mean_y - slope * mean_x) + slope * (n - 1)
    if slope >= 0 or current <= 0:
        # rising, flat, or already non-positive — no finite decay half-life (the verdict handles non-positive edge)
        return EdgeDecay(n=n, current_edge=current, slope=slope, half_life=None, periods_to_zero=None)
    periods_to_zero = current / (-slope)
    half_life = math.log(2.0) * current / (-slope)
    return EdgeDecay(n=n, current_edge=current, slope=slope, half_life=half_life, periods_to_zero=periods_to_zero)


def drift_score(
    realized: list[float],
    reference_edge: float,
    *,
    reference: str = "funded-baseline",
    slack_k: float = 0.5,
    cusum_h: float = 5.0,
) -> DriftScore:
    """Compare realized per-period returns to the edge the track was funded on. `z` is a one-sample shortfall
    statistic (negative = live below funded). `cusum` is a one-sided lower CUSUM change-point detector on the
    standardized shortfall — it accumulates only while realized stays > slack_k std below the reference and
    resets on recovery, so it flags a *sustained* downward shift fast, before cumulative P&L necessarily turns."""
    r = [float(x) for x in realized]
    n = len(r)
    ref = float(reference_edge)
    if n == 0:
        return DriftScore(0, 0.0, ref, reference, 0.0, 0.0, False)
    mean = sum(r) / n
    if n >= 2:
        var = sum((x - mean) ** 2 for x in r) / (n - 1)
        sigma = math.sqrt(var)
    else:
        sigma = 0.0
    # scale floor so a near-constant series (sigma≈0) still yields a finite, well-defined statistic
    sigma_floor = sigma if sigma > 1e-12 else (abs(ref) if abs(ref) > 1e-12 else 1.0)
    se = sigma_floor / math.sqrt(n)
    z = (mean - ref) / se if se > 0 else 0.0
    s = 0.0
    peak = 0.0
    for x in r:
        s = max(0.0, s + (ref - x) / sigma_floor - slack_k)  # grows when x is > slack_k std below the reference
        peak = max(peak, s)
    return DriftScore(n=n, realized_edge=mean, reference_edge=ref, reference=reference, z=z, cusum=peak, cusum_alarm=peak > cusum_h)


def assess_drift(
    ref_id: str,
    realized: list[float],
    *,
    reference_edge: float | None = None,
    baseline_n: int = 5,
    rolling_window: int = 5,
    min_periods: int = 3,
    min_half_life: float = 4.0,
    z_floor: float = -2.0,
    slack_k: float = 0.5,
    cusum_h: float = 5.0,
) -> DriftVerdict:
    """Combine edge-decay + drift into one anticipatory defund verdict. Reference = the edge the track was funded
    on: an explicit per-period backtest edge if supplied (in matching units), else the track's own funded
    baseline (mean of its earliest returns) — the realized embodiment of what the backtest promised at funding.
    Defund if any of: realized edge has gone non-positive · half-life below the floor (dying fast) · live is
    z_floor σ below the reference · the CUSUM change-point fired (persistent underperformance)."""
    r = [float(x) for x in realized]
    decay = fit_edge_decay(rolling_edge(r, window=rolling_window))
    if len(r) < min_periods:
        empty = DriftScore(len(r), (sum(r) / len(r) if r else 0.0), 0.0, "funded-baseline", 0.0, 0.0, False)
        return DriftVerdict(ref_id, False, f"insufficient live history (need >= {min_periods} periods)", decay, empty)

    if reference_edge is not None:
        ref_val, ref_label = float(reference_edge), "backtest"
    else:
        head = r[: max(1, min(baseline_n, len(r) // 2))]
        ref_val, ref_label = (sum(head) / len(head)), "funded-baseline"
    drift = drift_score(r, ref_val, reference=ref_label, slack_k=slack_k, cusum_h=cusum_h)

    reasons: list[str] = []
    if decay.current_edge <= 0:
        reasons.append("realized edge has gone non-positive")
    if decay.half_life is not None and decay.half_life < min_half_life:
        reasons.append(f"edge half-life {decay.half_life:.1f} < {min_half_life:g} periods (decaying fast)")
    if drift.z < z_floor:
        reasons.append(f"live edge {drift.z:.1f}σ below {ref_label}")
    if drift.cusum_alarm:
        reasons.append(f"CUSUM {drift.cusum:.1f} > {cusum_h:g}: persistent underperformance vs {ref_label}")
    reason = "; ".join(reasons) if reasons else "edge healthy: no decay or drift detected"
    return DriftVerdict(ref_id, bool(reasons), reason, decay, drift)


# --- store readers (read-only; the realized series come from portfolio_snapshots) -----------------


def _returns_from_equity(equities: list[float]) -> list[float]:
    out: list[float] = []
    for prev, cur in zip(equities, equities[1:]):
        if prev > 0 and math.isfinite(prev) and math.isfinite(cur):
            out.append((cur - prev) / prev)
    return out


def aggregate_return_series(store: Store, *, limit: int = 500) -> list[float]:
    rows = store.rows(
        "SELECT equity FROM portfolio_snapshots WHERE scope = 'aggregate' AND ref_id = 'global' ORDER BY ts ASC LIMIT ?",
        (limit,),
    )
    return _returns_from_equity([float(r["equity"]) for r in rows])


def track_return_series(store: Store, version_id: str, *, limit: int = 500) -> list[float]:
    rows = store.rows(
        "SELECT equity FROM portfolio_snapshots WHERE scope = 'track' AND ref_id = ? ORDER BY ts ASC LIMIT ?",
        (version_id, limit),
    )
    return _returns_from_equity([float(r["equity"]) for r in rows])


def batch_track_return_series(store: Store, version_ids: list[str], *, limit: int = 500) -> dict[str, list[float]]:
    """Fetch portfolio_snapshots for ALL supplied version_ids in ONE query, then split by ref_id in Python.
    Eliminates the N+1 round-trips that caused /research/drift to take ~18s on prod Postgres (each
    track_return_series() call was a separate network RTT). Returns a dict mapping version_id → return series;
    absent ids map to an empty list (honest-empty; assess_drift handles short series gracefully)."""
    if not version_ids:
        return {}
    # Build a single IN clause.  SQLite uses '?' placeholders; the _Conn layer rewrites to '%s' for Postgres.
    placeholders = ", ".join("?" for _ in version_ids)
    rows = store.rows(
        f"SELECT ref_id, equity, ts FROM portfolio_snapshots "
        f"WHERE scope = 'track' AND ref_id IN ({placeholders}) "
        f"ORDER BY ref_id, ts ASC",
        tuple(version_ids),
    )
    # Group equity values per ref_id preserving ts-order (ORDER BY above keeps it).
    from collections import defaultdict
    grouped: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        grouped[r["ref_id"]].append(float(r["equity"]))
    # Apply per-track limit (rare: most tracks have far fewer than 500 snapshots).
    result: dict[str, list[float]] = {}
    for vid in version_ids:
        equities = grouped.get(vid, [])
        if limit and len(equities) > limit:
            equities = equities[-limit:]
        result[vid] = _returns_from_equity(equities)
    return result


def funded_track_ids(store: Store) -> list[str]:
    """Strategy versions that currently hold a non-zero sim/live position (the tracks capital can be pulled
    from). Read off the positions table so the monitor only judges tracks that are actually funded."""
    rows = store.rows(
        "SELECT DISTINCT strategy_version_id AS vid FROM positions "
        "WHERE strategy_version_id IS NOT NULL AND CAST(qty AS REAL) != 0"
    )
    return [r["vid"] for r in rows if r["vid"]]


def monitor_drift(store: Store, version_ids: list[str] | None = None, **thresholds) -> list[DriftVerdict]:
    """Assess every funded track's realized trajectory and AUDIT the result: emit a `drift_assessed` event per
    track and a `track_defunded` event when the anticipatory verdict says pull capital. Read-only on prices;
    the defund itself is applied by the allocator (rotation) — this only recommends, deterministically."""
    ids = version_ids if version_ids is not None else funded_track_ids(store)
    verdicts: list[DriftVerdict] = []
    for vid in ids:
        verdict = assess_drift(vid, track_return_series(store, vid), **thresholds)
        verdicts.append(verdict)
        store.append_event(
            actor="master",
            kind="drift_assessed",
            ref_type="strategy_version",
            ref_id=vid,
            payload={
                "defund": verdict.defund,
                "reason": verdict.reason,
                "half_life": verdict.decay.half_life,
                "periods_to_zero": verdict.decay.periods_to_zero,
                "realized_edge": verdict.drift.realized_edge,
                "reference_edge": verdict.drift.reference_edge,
                "reference": verdict.drift.reference,
                "z": verdict.drift.z,
                "cusum": verdict.drift.cusum,
                "n": verdict.drift.n,
            },
        )
        if verdict.defund:
            store.append_event(
                actor="master",
                kind="track_defunded",
                ref_type="strategy_version",
                ref_id=vid,
                payload={"reason": verdict.reason, "anticipatory": True},
            )
    return verdicts
