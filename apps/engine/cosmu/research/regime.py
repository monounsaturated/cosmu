# intent: a NO-REPAINT, stationary-feature market-regime classifier done RIGHT — per the quant critiques the
# retail "hedge-fund Markov" hype gets wrong (HANDOFF §8, the #1 validated lever). The four disciplines the hype
# skips, all enforced here:
#   (a) STRIDE-SAMPLE non-overlapping windows for the transition matrix. Each label is computed from a trailing
#       `window`-bar window, so adjacent DAILY labels share window-1 bars → their transitions are dominated by
#       window-autocorrelation, NOT real regime persistence, and inflate the diagonal. `transition_matrix`
#       samples states every `stride` (= window by default) bars so the counted transitions use DISJOINT windows.
#   (b) NEVER REPAINT. Every label at bar t is computed from bars[0..t] ONLY (trailing mean/sd, a left-to-right
#       hysteresis state machine) — so appending future bars can NEVER change a past label. The repainting trap
#       (within-sample z over the whole series, as `slow_social_regime` does) makes an indicator look great
#       offline and fail live; `regime_states` is invariant under appended future bars (test_regime asserts it).
#   (c) STATIONARY features only — trailing log-return DRIFT and realized VOL, never raw price level.
#   (d) The output regime series is meant to be GATED through the honest purged-holdout + BH-FDR Gate
#       (research/regime_cohort.py). Treat it as a GATING / FEATURE layer, NOT a novel edge: it is essentially
#       regime-momentum, which the deploy-lane TAA (GEM / VAA / GTAA) already captures.
#
# Output convention: states ∈ {-1 bear, 0 sideways, +1 bull}. `regime_points` maps them to an AltDataPoint
# series valued {0.0, 0.5, 1.0} (bear/sideways/bull) for the size-tilt overlay, with `available_at` LAGGED one
# bar so a bar's exposure is sized from STRICTLY PRIOR regime reads (no same-bar look-ahead) — stricter than the
# same-bar social overlay. ZERO LLM on this path; deterministic for fixed bars + config.

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import timedelta

from cosmu.data.market import Bar
from cosmu.data.providers._types import AltDataPoint

BEAR, SIDEWAYS, BULL = -1, 0, 1


@dataclass(frozen=True)
class RegimeConfig:
    """All-trailing, no-repaint regime parameters. `window` is the trailing horizon for the stationary features
    (drift + vol); `enter_z` / `exit_z` are the hysteresis band on the trailing return/vol z (a trailing
    Sharpe-like ratio); `min_dwell` floors how long a state is held (low turnover); `stride` is the transition-
    matrix sampling stride (None → `window`, i.e. non-overlapping windows)."""

    window: int = 30
    enter_z: float = 0.5
    exit_z: float = 0.15
    min_dwell: int = 10
    stride: int | None = None

    @property
    def warmup(self) -> int:
        # need `window` log-returns → window+1 bars before the first defined label.
        return self.window + 1

    @property
    def sample_stride(self) -> int:
        return self.stride if self.stride is not None else self.window


@dataclass(frozen=True)
class RegimeState:
    ts: object              # the bar timestamp this label is "as of close of"
    available_at: object    # when the label is USABLE (lagged one bar — strictly prior to the bar it sizes)
    state: int              # -1 bear · 0 sideways · +1 bull
    z: float                # the trailing return/vol z that drove it (diagnostic)


def _log_returns(bars: list[Bar]) -> list[float]:
    out: list[float] = []
    for i in range(1, len(bars)):
        p0, p1 = float(bars[i - 1].close), float(bars[i].close)
        out.append(math.log(p1 / p0) if p0 > 0 and p1 > 0 else 0.0)
    return out


def _trailing_z(rets: list[float], end: int, window: int) -> float | None:
    """Trailing return/vol z over rets[end-window:end] (a trailing Sharpe-like ratio). CAUSAL: uses only
    returns up to index `end` (exclusive). None until a full window of returns exists."""
    if end < window:
        return None
    win = rets[end - window:end]
    mean = sum(win) / window
    var = sum((x - mean) ** 2 for x in win) / window
    sd = math.sqrt(var)
    if sd <= 0:
        return 0.0
    return mean / sd


def regime_states(bars: list[Bar], cfg: RegimeConfig = RegimeConfig()) -> list[RegimeState]:
    """Causal, NO-REPAINT 3-state regime labels. Each label at bar i is the trailing return/vol z over the prior
    `window` log-returns, fed through a left-to-right hysteresis + min-dwell state machine — so it depends ONLY
    on bars[0..i] and is invariant under any bars appended after i. `available_at` is lagged to the NEXT bar
    (strictly-prior sizing). Returns one RegimeState per bar from index `warmup` onward."""
    rets = _log_returns(bars)  # rets[j] is the return INTO bar j+1
    out: list[RegimeState] = []
    state = SIDEWAYS
    dwell = cfg.min_dwell  # allow the first transition immediately
    for i in range(cfg.warmup, len(bars)):
        # rets up to and including the return into bar i is rets[:i]; trailing window ends there (causal).
        z = _trailing_z(rets, i, cfg.window)
        if z is None:
            continue
        if dwell >= cfg.min_dwell:
            if state == SIDEWAYS:
                if z > cfg.enter_z:
                    state, dwell = BULL, 0
                elif z < -cfg.enter_z:
                    state, dwell = BEAR, 0
            elif state == BULL and z < cfg.exit_z:
                state, dwell = SIDEWAYS, 0
            elif state == BEAR and z > -cfg.exit_z:
                state, dwell = SIDEWAYS, 0
        dwell += 1
        ts = bars[i].ts
        avail = bars[i + 1].ts if i + 1 < len(bars) else bars[i].ts + timedelta(days=1)
        out.append(RegimeState(ts=ts, available_at=avail, state=state, z=round(z, 6)))
    return out


# bear → floor exposure, sideways → half, bull → full. Fed to the size-tilt overlay (size = LO + (HI-LO)*value).
_STATE_TO_TILT = {BEAR: 0.0, SIDEWAYS: 0.5, BULL: 1.0}


def regime_points(bars: list[Bar], cfg: RegimeConfig = RegimeConfig()) -> list[AltDataPoint]:
    """The no-repaint regime as an AltDataPoint series (value ∈ {0.0, 0.5, 1.0}) for the PIT size-tilt overlay.
    `available_at` is the lagged (next-bar) stamp, so the as-of join sizes each bar from a STRICTLY PRIOR read."""
    return [
        AltDataPoint(ts=s.ts, available_at=s.available_at, value=_STATE_TO_TILT[s.state])
        for s in regime_states(bars, cfg)
    ]


def transition_matrix(states: list[RegimeState], cfg: RegimeConfig = RegimeConfig()) -> list[list[float]]:
    """The 3×3 row-stochastic regime transition matrix (order: bear, sideways, bull), estimated from STRIDE-
    SAMPLED states so adjacent counted states use DISJOINT trailing windows — measuring REAL persistence, not the
    window-autocorrelation that overlapping daily labels would inflate the diagonal with. Empty rows fall back to
    a uniform row (no fabricated certainty)."""
    idx = {BEAR: 0, SIDEWAYS: 1, BULL: 2}
    sampled = states[:: cfg.sample_stride]
    counts = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
    for a, b in zip(sampled, sampled[1:], strict=False):
        counts[idx[a.state]][idx[b.state]] += 1
    matrix: list[list[float]] = []
    for row in counts:
        total = sum(row)
        matrix.append([c / total for c in row] if total else [1 / 3, 1 / 3, 1 / 3])
    return matrix


def regime_summary(bars: list[Bar], cfg: RegimeConfig = RegimeConfig()) -> dict[str, object]:
    """Diagnostic summary: state distribution, flips/year (turnover), and the stride-sampled persistence (mean
    diagonal of the transition matrix). For logging/DECISIONS — never a trading input."""
    states = regime_states(bars, cfg)
    if not states:
        return {"n": 0}
    dist = {"bear": 0, "sideways": 0, "bull": 0}
    name = {BEAR: "bear", SIDEWAYS: "sideways", BULL: "bull"}
    for s in states:
        dist[name[s.state]] += 1
    flips = sum(1 for a, b in zip(states, states[1:], strict=False) if a.state != b.state)
    days = (states[-1].ts - states[0].ts).days or 1
    tm = transition_matrix(states, cfg)
    persistence = (tm[0][0] + tm[1][1] + tm[2][2]) / 3.0
    return {
        "n": len(states),
        "distribution": dist,
        "flips_per_year": round(flips / (days / 365.25), 3),
        "stride_sampled_persistence": round(persistence, 4),
        "transition_matrix": [[round(x, 4) for x in row] for row in tm],
    }
