# intent: turn the RAW LunarCrush social series (social_volume / galaxy_score), whose absolute scale drifts
# ~160x over 2020-26, into SCALE-STABLE, point-in-time NORMALIZED features so a fitted threshold can actually
# bind — the fix the phase0-social-signal §4 caveat proved is required (a level floor on a 160x-growing series
# is always-true and tests nothing). inputs: the per-symbol bar series + a raw social AltDataProvider; outputs:
# a symbol -> feature -> {bar.ts.isoformat(): value} alt-join (the shape run_strategy_backtest consumes).
#
# Derived features (all WITHIN-ASSET, all point-in-time — every derived point's available_at is inherited from
# the latest RAW point it consumes, so the backtest's as-of join never sees a value before we'd have known it):
#   social_volume_accel  — ln(v_t / v_{t-1}) of social_volume: the *change* (a fresh attention jump). The probe
#                          finds this LEADS price (+) at k=1-3 (t up to +10.8), opposite to the LEVEL.
#   social_attention_z   — trailing z-score of social_volume LEVEL over _Z_WINDOW days. The probe finds the
#                          level LEADS price (-) at the swing horizon, though only marginally on the full sample
#                          — a weak "is the crowd already piled in" altitude guard (its own disconfirmer may kill it).
#   social_excess_attention_z — trailing z of ln(social_volume) - ln(dollar_volume): crowd loudness RELATIVE to
#                          money traded. The probe finds HIGH excess attention LEADS price UP at k=7 (decile
#                          spread +1.8%, t=+5.77) — a robust, non-obvious ~1-week continuation, opposite to the
#                          short-horizon noise. Relative-to-volume is the seam the absolute-volume specs missed.
#   galaxy_score_z       — trailing z-score of galaxy_score LEVEL. The probe finds top-decile galaxy precedes
#                          DEEPER forward drawdowns (t=-2.6..-4.1) with NO extra upside (runups equal hi vs lo)
#                          — an asymmetric downside tag, spot-legal only as an avoidance/exit filter.
#   btc_social_accel     — BTCUSDT's social_volume_accel BROADCAST to every symbol. The probe finds a BTC social
#                          spike LEADS the mean-ALT return (r=+0.066 at k=1) — cross-asset attention contagion.
#
# invariants: ZERO LLM, deterministic; _Z_WINDOW is a pinned transform parameter (NOT a trade threshold — the
# specs' z floors/ceilings stay fitted ParamRefs); a symbol/metric with no raw history simply yields no derived
# points (the feature reads None — honest absence, never fabricated).

from __future__ import annotations

import math
from collections import deque

from cosmu.data.altdata import AltDataPoint, AltDataProvider
from cosmu.data.backtest import align_asof
from cosmu.data.market import Bar

# Trailing window (days) for the within-asset z-score normalization. Pinned transform parameter, bumped with the
# transform version — NOT a fitted trade threshold. ~6 weeks: long enough to define "elevated vs typical", short
# enough to track the slow regime drift in the social scale.
_Z_WINDOW = 30
_Z_MIN = 10  # need at least this many trailing points before a z-score is defined (else the feature reads None)
SOCIAL_NORM_VERSION = "social-norm-v1"

# --- btc_social_regime (the LOW-TURNOVER risk-on overlay) -------------------------------------------------
# A SLOW market-wide risk-on/off regime derived from BTC's social_volume_accel. The point is LOW TURNOVER: a
# handful of regime flips per year, so it TILTS a slow base book's exposure rather than firing daily trades.
#   1. SMOOTH: an EWMA of BTC social_volume_accel over _REGIME_EWMA_DAYS (W=20–40d) — the slow attention trend.
#   2. NORMALIZE: a within-sample z of that smoothed series (mean/sd over the whole sample) so the +0.5/-0.5
#      hysteresis bands are scale-free. (Within-SAMPLE, not trailing: this is a regime LABEL the overlay tilts
#      by, computed once over the run window — it is NOT a per-bar trade threshold that must be strictly PIT
#      trailing. The disconfirmers below guard against the look-ahead this could otherwise smuggle in.)
#   3. HYSTERESIS + MIN-DWELL: turn ON when z crosses above +_REGIME_ON_Z, OFF when it crosses below
#      -_REGIME_OFF_Z, and hold each state at least _REGIME_MIN_DWELL_DAYS before it may flip again. This is
#      what makes the regime flip only a few times a year (turnover ≪ a daily trigger).
# The regime value is in {0,1} (a [0,1] clamp by construction); the overlay maps it to an exposure tilt
# lo+(hi-lo)*regime in research/rerun_cohort.py. available_at is inherited from the smoothed accel point, so
# the regime is point-in-time honest the same way every other social derivation is.
_REGIME_EWMA_DAYS = 30          # W (20–40d): the slow smoothing window for BTC social_volume_accel
_REGIME_ON_Z = 0.5              # enter risk-ON when the within-sample z crosses above +this
_REGIME_OFF_Z = 0.5             # fall risk-OFF when the within-sample z crosses below -this
_REGIME_MIN_DWELL_DAYS = 20     # hold each ON/OFF state at least this many days before another flip is allowed
_REGIME_Z_MIN = 10              # need this many smoothed points before the within-sample z is defined


def _accel(points: list[AltDataPoint]) -> list[AltDataPoint]:
    """ln(v_t / v_{t-1}) — point-in-time: available_at inherited from the LATER point (known when t closes)."""
    out: list[AltDataPoint] = []
    for prev, cur in zip(points, points[1:], strict=False):
        if prev.value > 0 and cur.value > 0:
            out.append(AltDataPoint(ts=cur.ts, available_at=cur.available_at,
                                    value=math.log(cur.value / prev.value)))
    return out


def _rolling_z(points: list[AltDataPoint]) -> list[AltDataPoint]:
    """Trailing z-score of the LEVEL over a _Z_WINDOW window using ONLY points up to and including t (no
    look-ahead — every input point in the window has available_at <= the current point's available_at)."""
    out: list[AltDataPoint] = []
    win: deque[float] = deque(maxlen=_Z_WINDOW)
    for p in points:
        win.append(p.value)
        if len(win) >= _Z_MIN:
            mean = sum(win) / len(win)
            var = sum((x - mean) ** 2 for x in win) / len(win)
            sd = math.sqrt(var)
            if sd > 0:
                out.append(AltDataPoint(ts=p.ts, available_at=p.available_at, value=(p.value - mean) / sd))
    return out


def _ewma(points: list[AltDataPoint], span_days: int) -> list[AltDataPoint]:
    """Exponential moving average over `points` with the standard span→alpha = 2/(span+1). Causal (each output
    consumes only points up to and including t), so available_at is inherited from the current point — no
    look-ahead. The slow smoother that turns the noisy daily social_volume_accel into a regime trend."""
    if not points:
        return []
    alpha = 2.0 / (max(1, span_days) + 1.0)
    out: list[AltDataPoint] = []
    ema: float | None = None
    for p in points:
        ema = p.value if ema is None else alpha * p.value + (1.0 - alpha) * ema
        out.append(AltDataPoint(ts=p.ts, available_at=p.available_at, value=ema))
    return out


def slow_social_regime(
    accel: list[AltDataPoint],
    *,
    ewma_days: int = _REGIME_EWMA_DAYS,
    on_z: float = _REGIME_ON_Z,
    off_z: float = _REGIME_OFF_Z,
    min_dwell_days: int = _REGIME_MIN_DWELL_DAYS,
) -> list[AltDataPoint]:
    """The LOW-TURNOVER risk-on/off regime ∈ {0,1} derived from a social_volume_accel series (BTC's).

    Pipeline: EWMA(span=ewma_days) → within-sample z → hysteresis (ON when z>+on_z, OFF when z<-off_z) with a
    min-dwell of `min_dwell_days` per state. Returns one regime point per smoothed accel point that has a
    defined z, with available_at inherited from the smoothed point (point-in-time on availability). By
    construction this flips only a handful of times per year — it is a SLOW exposure tilt, never a daily trade.

    The z is WITHIN-SAMPLE (mean/sd over the whole run window), not trailing: the regime is a label the overlay
    tilts exposure by, computed once over the run — the pre-registered disconfirmers (a BTC-PRICE regime of
    equal turnover, a within-regime time-shuffle placebo, and the flat-exposure baseline) are what guard against
    any edge this within-sample normalization could manufacture."""
    smoothed = _ewma(accel, ewma_days)
    if len(smoothed) < _REGIME_Z_MIN:
        return []
    vals = [p.value for p in smoothed]
    mean = sum(vals) / len(vals)
    var = sum((x - mean) ** 2 for x in vals) / len(vals)
    sd = math.sqrt(var)
    if sd <= 0:
        return []
    out: list[AltDataPoint] = []
    state = 0          # current regime: 0 = risk-off, 1 = risk-on
    dwell = min_dwell_days  # allow the first flip immediately (start neutral-off, flip on first ON cross)
    for p in smoothed:
        z = (p.value - mean) / sd
        if dwell >= min_dwell_days:
            if state == 0 and z > on_z:
                state, dwell = 1, 0
            elif state == 1 and z < -off_z:
                state, dwell = 0, 0
        dwell += 1
        out.append(AltDataPoint(ts=p.ts, available_at=p.available_at, value=float(state)))
    return out


def _excess_attention_z(vol: list[AltDataPoint], bars: list[Bar]) -> list[AltDataPoint]:
    """Within-asset trailing z of EXCESS ATTENTION = ln(social_volume) - ln(dollar_volume): how loud the crowd
    is RELATIVE to the money actually trading. Point-in-time: a social point at ts=d (available d+1) is paired
    with the SAME-day bar's dollar volume (close*volume, known at that day's close, available by d+1), so the
    ratio is fully known when the social point becomes available. The rolling z then uses only trailing ratios."""
    dvol_by_day: dict[str, float] = {}
    for b in bars:
        day = b.ts.date().isoformat()
        dv = float(b.close) * float(b.volume)
        if dv > 0:
            dvol_by_day[day] = dv
    ratio: list[AltDataPoint] = []
    for p in vol:
        dv = dvol_by_day.get(p.ts.date().isoformat())
        if dv and p.value > 0:
            ratio.append(AltDataPoint(ts=p.ts, available_at=p.available_at,
                                      value=math.log(p.value) - math.log(dv)))
    return _rolling_z(ratio)


def derive_social_alt(
    market: dict[str, list[Bar]], provider: AltDataProvider
) -> dict[str, dict[str, dict[str, float]]]:
    """Build the PIT NORMALIZED social alt-join: symbol -> {feature: {bar.ts.isoformat(): value}}.

    Mirrors social_signal_cohort._social_alt but emits the derived (scale-stable) features instead of raw levels,
    so a fitted threshold genuinely binds. BTC's acceleration is broadcast to every symbol as btc_social_accel,
    and BTC's SLOW risk-on/off regime as btc_social_regime (the low-turnover overlay)."""
    # BTC acceleration series, derived once and broadcast (the contagion signal is BTC's, read by every alt).
    btc_bars = market.get("BTCUSDT")
    btc_accel: list[AltDataPoint] = []
    btc_regime: list[AltDataPoint] = []
    if btc_bars:
        btc_vol = provider.fetch_series("BTCUSDT", "social_volume", limit=len(btc_bars) + 2400)
        btc_accel = _accel(btc_vol)
        btc_regime = slow_social_regime(btc_accel)  # the slow, hysteresis+dwell risk-on/off regime ∈ {0,1}

    out: dict[str, dict[str, dict[str, float]]] = {}
    for symbol, bars in market.items():
        vol = provider.fetch_series(symbol, "social_volume", limit=len(bars) + 2400)
        gal = provider.fetch_series(symbol, "galaxy_score", limit=len(bars) + 2400)
        feats: dict[str, dict[str, float]] = {}
        for name, derived in (
            ("social_volume_accel", _accel(vol)),
            ("social_attention_z", _rolling_z(vol)),
            ("social_excess_attention_z", _excess_attention_z(vol, bars)),
            ("galaxy_score_z", _rolling_z(gal)),
            ("btc_social_accel", btc_accel),
            ("btc_social_regime", btc_regime),
        ):
            joined = align_asof(derived, bars)
            if joined:
                feats[name] = joined
        if feats:
            out[symbol] = feats
    return out
