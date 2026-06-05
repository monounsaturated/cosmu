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
    so a fitted threshold genuinely binds. BTC's acceleration is broadcast to every symbol as btc_social_accel."""
    # BTC acceleration series, derived once and broadcast (the contagion signal is BTC's, read by every alt).
    btc_bars = market.get("BTCUSDT")
    btc_accel: list[AltDataPoint] = []
    if btc_bars:
        btc_vol = provider.fetch_series("BTCUSDT", "social_volume", limit=len(btc_bars) + 2400)
        btc_accel = _accel(btc_vol)

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
        ):
            joined = align_asof(derived, bars)
            if joined:
                feats[name] = joined
        if feats:
            out[symbol] = feats
    return out
