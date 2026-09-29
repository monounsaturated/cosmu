# intent: a REUSABLE disconfirmer harness — the standard "prove the IC isn't an artefact" tools any new
# feature / signal must survive BEFORE the deterministic Gate ever sees it. Two nulls, both pure + offline:
#   (1) shuffle null  — permute a feature's VALUES in time (keep every PIT stamp + the whole return path);
#       under this null the timing relationship is destroyed, so a measured IC MUST collapse toward 0. A
#       feature whose IC SURVIVES the shuffle has a real alignment to forward returns; one whose IC sits
#       inside the shuffled band is noise (BlindTrade: IC 0.015 → 0.0004 under shuffle).
#   (2) symbol-anonymization null — strip SYMBOL IDENTITY by demeaning each symbol's feature AND forward
#       return within-symbol, then pool. A cross-sectional IC that comes from a memorized per-symbol PRIOR
#       (a constant level that happens to rank-correlate with that symbol's drift) vanishes; a transferable
#       within-symbol timing signal survives. This is the IC analog of the LLM ticker-memorization test
#       (Sarkar & Vafa): an edge that dies when the ticker is masked was never a signal.
#
# Invariants: PURE (no I/O, no DB, no settings) — operates on AltDataPoint lists + Bar lists already read
# point-in-time; reuses align_asof (available_at <= bar.ts, zero look-ahead) and spearman_ic (the SAME IC the
# correlation scan + Gate machinery use — never a second hand-rolled correlation). PROPOSE-ONLY: surviving a
# disconfirmer is NECESSARY, never sufficient — the Gate alone disposes. These nulls catch the spurious /
# memorized class; the align_asof PIT audit (test_leakage_tripwire_pit) catches look-ahead.

from __future__ import annotations

import random
from dataclasses import dataclass, field

from cosmu.data.backtest import align_asof
from cosmu.data.market import Bar
from cosmu.data.providers._types import AltDataPoint
from cosmu.research.correlation_scan import spearman_ic


def forward_returns(bars: list[Bar], horizon: int) -> dict[str, float]:
    """ts.isoformat() -> the forward return close_t -> close_{t+horizon} (strictly FUTURE; no look-ahead).

    Byte-identical semantics to correlation_scan._forward_returns — the harness scores the SAME forward
    target the scan + Gate score, so a disconfirmer verdict transfers directly."""
    out: dict[str, float] = {}
    for i in range(len(bars) - horizon):
        p0, p1 = float(bars[i].close), float(bars[i + horizon].close)
        if p0 > 0:
            out[bars[i].ts.isoformat()] = (p1 / p0) - 1.0
    return out


def _paired(joined: dict[str, float], fwd: dict[str, float]) -> tuple[list[float], list[float]]:
    """The (feature_t, forward_return_t) pairs on the bars where BOTH exist, in a deterministic key order."""
    keys = sorted(set(joined) & set(fwd))
    return [joined[k] for k in keys], [fwd[k] for k in keys]


def pit_ic(points: list[AltDataPoint], bars: list[Bar], horizon: int) -> tuple[float, int]:
    """Point-in-time IC: align the feature onto the bars (available_at <= bar.ts) and Spearman-correlate the
    KNOWN-AT-t value against the strictly-future return t->t+horizon. Returns (ic, n_obs). Fail-closed (0, n)
    when degenerate — never a fabricated correlation."""
    joined = align_asof(points, bars)
    fwd = forward_returns(bars, horizon)
    xs, ys = _paired(joined, fwd)
    ic, _p, n = spearman_ic(xs, ys)
    return ic, n


def _shuffle_values(points: list[AltDataPoint], rng: random.Random) -> list[AltDataPoint]:
    """A fresh series with the VALUES permuted across time; every (ts, available_at) stamp untouched, so the
    PIT join still works and the value landing on each bar is a random draw from the SAME marginal."""
    values = [p.value for p in points]
    rng.shuffle(values)
    return [AltDataPoint(ts=p.ts, available_at=p.available_at, value=v) for p, v in zip(points, values, strict=True)]


@dataclass(frozen=True)
class ShuffleNullResult:
    real_ic: float
    n_obs: int
    trials: int
    null_mean_abs: float          # mean |IC| under the shuffle null (collapses toward 0 for a real signal)
    null_p95_abs: float           # 95th percentile of |IC| under the null — the noise band
    p_value: float                # empirical two-sided: P(|null IC| >= |real IC|)
    survives: bool                # real IC is outside the null band (p < alpha) — a genuine alignment
    null_ics: list[float] = field(default_factory=list, repr=False)

    @property
    def collapsed(self) -> bool:
        """The null ICs collapsed toward 0 relative to the real IC (descriptive companion to `survives`)."""
        return abs(self.real_ic) > 2.0 * self.null_mean_abs


def shuffle_null(
    points: list[AltDataPoint],
    bars: list[Bar],
    horizon: int,
    *,
    trials: int = 200,
    seed: int = 0,
    alpha: float = 0.05,
) -> ShuffleNullResult:
    """The shuffle / permutation null (item 2a of the leakage tripwire). Measure the real PIT IC, then permute
    the feature's values in time `trials` times and re-measure; a real signal's IC sits OUTSIDE the shuffled
    band, a spurious one sits INSIDE it. Deterministic (string-seeded RNG, matching the repo's fixture style).

    `survives=True` means the measured IC is unlikely under the shuffle null (empirical p < alpha) — the IC
    reflects a genuine feature->return alignment, not the IC machinery fabricating structure. It does NOT by
    itself prove the alignment is honest (look-ahead also survives shuffle — that is the align_asof PIT
    audit's job); it proves the IC is not a pure-noise / autocorrelation artefact."""
    real_ic, n = pit_ic(points, bars, horizon)
    null_ics: list[float] = []
    for t in range(trials):
        rng = random.Random(f"disconfirm-shuffle-{seed}-{t}")
        ic, _n = pit_ic(_shuffle_values(points, rng), bars, horizon)
        null_ics.append(ic)
    abs_nulls = sorted(abs(v) for v in null_ics)
    mean_abs = sum(abs_nulls) / len(abs_nulls) if abs_nulls else 0.0
    p95 = abs_nulls[min(len(abs_nulls) - 1, int(0.95 * len(abs_nulls)))] if abs_nulls else 0.0
    # Empirical two-sided p-value with the +1 add-one correction (never reports an impossible p=0).
    ge = sum(1 for v in abs_nulls if v >= abs(real_ic))
    p_value = (1 + ge) / (1 + len(abs_nulls)) if abs_nulls else 1.0
    return ShuffleNullResult(
        real_ic=real_ic, n_obs=n, trials=trials, null_mean_abs=round(mean_abs, 6),
        null_p95_abs=round(p95, 6), p_value=round(p_value, 6), survives=bool(p_value < alpha),
        null_ics=null_ics,
    )


@dataclass(frozen=True)
class SymbolAnonymizationResult:
    pooled_ic: float              # cross-sectional IC pooling every symbol's (feature_t, fwd_ret_t) raw
    within_ic: float              # IC after demeaning feature AND return WITHIN each symbol (identity masked)
    n_obs: int
    identity_share: float         # fraction of the pooled-IC magnitude that is symbol identity, in [0, 1]
    memorized: bool               # the edge is mostly a memorized per-symbol prior (dies when ticker masked)

    @property
    def survives(self) -> bool:
        """A transferable within-symbol signal survives anonymization (NOT a memorized prior)."""
        return not self.memorized


def symbol_anonymization_null(
    series_by_symbol: dict[str, list[AltDataPoint]],
    bars_by_symbol: dict[str, list[Bar]],
    horizon: int,
    *,
    memorized_frac: float = 0.5,
    min_pooled_abs: float = 0.02,
) -> SymbolAnonymizationResult:
    """The symbol-anonymization null (item 2b — ticker masking). Compare the raw POOLED cross-sectional IC to
    the WITHIN-SYMBOL IC (each symbol's feature and forward return demeaned by that symbol's own mean over the
    overlap, then pooled). Demeaning removes every constant per-symbol level — i.e. SYMBOL IDENTITY — leaving
    only within-symbol timing.

    A genuine timing signal keeps most of its IC after demeaning (`within_ic` ~ `pooled_ic`). An edge that is
    really a memorized per-symbol prior (a level that ranks with that symbol's drift) collapses to within_ic ~
    0 once identity is masked. `memorized=True` flags that case: |within_ic| < memorized_frac * |pooled_ic|
    while the pooled IC was materially non-zero. PIT throughout (align_asof + strictly-future returns)."""
    pooled_x: list[float] = []
    pooled_y: list[float] = []
    demean_x: list[float] = []
    demean_y: list[float] = []
    for symbol, points in series_by_symbol.items():
        bars = bars_by_symbol.get(symbol)
        if not bars:
            continue
        joined = align_asof(points, bars)
        fwd = forward_returns(bars, horizon)
        xs, ys = _paired(joined, fwd)
        if len(xs) < 2:
            continue
        pooled_x.extend(xs)
        pooled_y.extend(ys)
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        demean_x.extend(v - mx for v in xs)
        demean_y.extend(v - my for v in ys)
    pooled_ic, _p, n = spearman_ic(pooled_x, pooled_y)
    within_ic, _wp, _wn = spearman_ic(demean_x, demean_y)
    if abs(pooled_ic) < 1e-9:
        identity_share = 0.0
    else:
        identity_share = max(0.0, min(1.0, 1.0 - abs(within_ic) / abs(pooled_ic)))
    memorized = bool(
        abs(pooled_ic) >= min_pooled_abs and abs(within_ic) < memorized_frac * abs(pooled_ic)
    )
    return SymbolAnonymizationResult(
        pooled_ic=pooled_ic, within_ic=within_ic, n_obs=n,
        identity_share=round(identity_share, 6), memorized=memorized,
    )


__all__ = [
    "ShuffleNullResult",
    "SymbolAnonymizationResult",
    "forward_returns",
    "pit_ic",
    "shuffle_null",
    "symbol_anonymization_null",
]
