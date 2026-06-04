# intent: a faithful, clean-room Python port of the "ML Liquidity Zone Classifier [PhenLabs]" Pine indicator as
# a COMPUTED DATA SOURCE (see base.py). Its number is a KNN classifier confidence in [0, 100]: the share of the
# k nearest historical bars (in a 3-feature space — volume spike, higher-timeframe alignment, candle
# displacement) whose outcome was a > N*ATR move over the next `eval_window` bars. So the confidence is a
# point-in-time predicted probability that THIS bar precedes a large move — exactly the kind of number we can
# correlate against forward |return| to see if it means anything. inputs: list[Bar] + params; outputs:
# IndicatorResult (confidence + components + zone events); invariants: causal/non-repainting (the training
# labels use only outcomes already known at the current bar — the original runs on barstate.isconfirmed),
# deterministic, offline. NOTE: the Pine source is MPL-2.0; this is an original expression of its LOGIC in
# Cosmu's typed format, not a copy of its code. The Gate, not this port, decides if the signal has an edge.

from __future__ import annotations

import math
import statistics

from cosmu.data.market import Bar
from cosmu.research.pine_indicators.base import (
    CorrelationReport,
    IndicatorResult,
    correlate,
    forward_abs_return,
)

name = "ml_liquidity_zone"

# Defaults lifted verbatim from the published inputs. These are tuning knobs for a research data source, NOT
# magic numbers on a money path (this module never sizes a trade — the Gate does, downstream, if it ever earns
# its place). Kept as a dict so the port stays a pure function of (bars, params).
DEFAULTS: dict[str, float] = {
    "knn_k": 5,
    "lookback": 100,
    "htf_mult": 12.0,
    "atr_len": 14,
    "vol_len": 20,
    "ob_atr_mult": 1.5,
    "volume_mult": 1.5,
    "vol_peak_len": 20,
    "pivot_len": 5,
    "zone_tolerance": 0.1,
    "eval_window": 10,
    "eval_atr_mult": 1.0,
}


def compute(bars: list[Bar], **overrides: float) -> IndicatorResult:
    """Compute the classifier confidence series (+ component features and zone events) over `bars`.

    Output series (all bar-aligned, None during warm-up):
      - confidence       : KNN confidence [0, 100] on EVERY bar once the training set is warm (the headline).
      - zone_confidence  : confidence only on bars where a liquidity zone is detected (matches the chart).
      - zone_flag        : 1.0 when a zone (order block / equal H-L / volume node) is detected, else 0.0.
      - f1_volume        : normalized volume-spike feature [0, 1].
      - f2_htf_align     : higher-timeframe alignment feature [0, 1] (closer to an HTF level => higher).
      - f3_displacement  : candle-body displacement feature [0, 1].
      - htf_bias         : +1 / -1 / 0 from the last closed higher-timeframe candle.
    """
    p = {**DEFAULTS, **overrides}
    k = max(1, int(p["knn_k"]))
    lookback = max(10, int(p["lookback"]))
    atr_len = max(1, int(p["atr_len"]))
    vol_len = max(1, int(p["vol_len"]))
    vol_peak_len = max(1, int(p["vol_peak_len"]))
    pivot_len = max(1, int(p["pivot_len"]))
    eval_window = max(1, int(p["eval_window"]))
    htf_n = max(2, int(round(p["htf_mult"])))

    n = len(bars)
    empty = {key: [] for key in _SERIES_KEYS}
    if n == 0:
        return IndicatorResult(series=empty, primary="confidence")

    opens = [float(b.open) for b in bars]
    highs = [float(b.high) for b in bars]
    lows = [float(b.low) for b in bars]
    closes = [float(b.close) for b in bars]
    volumes = [float(b.volume) for b in bars]

    # --- price-derived series (all causal) ---
    atr = _rma(_true_range(highs, lows, closes), atr_len)  # ATR in PRICE units (Pine ta.atr), not normalized.
    vol_avg = _sma(volumes, vol_len)
    vol_hi = _rolling_max(volumes, vol_peak_len)
    ph = _pivot_high(highs, pivot_len, pivot_len)
    pl = _pivot_low(lows, pivot_len, pivot_len)
    htf_o, htf_h, htf_l, htf_c = _htf_levels(opens, highs, lows, closes, htf_n)

    # --- the three KNN features, per bar ---
    f1 = [None] * n  # volume spike
    f2 = [None] * n  # HTF alignment
    f3 = [None] * n  # displacement
    htf_bias: list[float | None] = [None] * n
    big = 1e10
    for i in range(n):
        va = vol_avg[i]
        f1[i] = min((volumes[i] / va) / 3.0, 1.0) if (va is not None and va > 0) else min((1.0) / 3.0, 1.0)
        a = atr[i]
        f3[i] = min((abs(closes[i] - opens[i]) / a) / 3.0, 1.0) if (a is not None and a > 0) else 0.0
        levels = [abs(closes[i] - lv) for lv in (htf_h[i], htf_l[i], htf_c[i], htf_o[i]) if lv is not None]
        nearest = min(levels) if levels else big
        if a is not None and a > 0 and nearest < big:
            f2[i] = 1.0 - min((nearest / a) / 3.0, 1.0)
        else:
            f2[i] = 0.5
        if htf_c[i] is not None and htf_o[i] is not None:
            htf_bias[i] = 1.0 if htf_c[i] > htf_o[i] else (-1.0 if htf_c[i] < htf_o[i] else 0.0)

    # --- KNN training set maintenance + classification (single causal forward pass) ---
    train_f1: list[float] = []
    train_f2: list[float] = []
    train_f3: list[float] = []
    train_y: list[float] = []
    confidence: list[float | None] = [None] * n
    warm = eval_window + atr_len + vol_len
    eval_atr_mult = float(p["eval_atr_mult"])
    for i in range(n):
        # 1) Build the labelled sample for the bar `eval_window` ago — its outcome is now known (non-repainting).
        if i > warm:
            t = i - eval_window
            at = atr[t]
            if f1[t] is not None and f2[t] is not None and f3[t] is not None and at is not None and at > 0:
                label = 1.0 if abs(closes[i] - closes[t]) > at * eval_atr_mult else 0.0
                train_f1.append(f1[t])
                train_f2.append(f2[t])
                train_f3.append(f3[t])
                train_y.append(label)
                if len(train_y) > lookback:
                    train_f1.pop(0)
                    train_f2.pop(0)
                    train_f3.pop(0)
                    train_y.pop(0)
        # 2) Classify the current bar against the (outcome-known-only) training set.
        if train_y and f1[i] is not None and f2[i] is not None and f3[i] is not None:
            confidence[i] = _knn_confidence(f1[i], f2[i], f3[i], k, train_f1, train_f2, train_f3, train_y)

    # --- zone detection (faithful to the published logic) — produces zone_flag + zone_confidence ---
    zone_flag: list[float | None] = [0.0] * n
    zone_confidence: list[float | None] = [None] * n
    last_ph: float | None = None
    last_pl: float | None = None
    ob_atr_mult = float(p["ob_atr_mult"])
    volume_mult = float(p["volume_mult"])
    zone_tolerance = float(p["zone_tolerance"])
    for i in range(n):
        a = atr[i]
        tol = (a if a is not None else 0.0) * zone_tolerance
        eq_high = eq_low = False
        if ph[i] is not None:
            if last_ph is not None and tol > 0 and abs(ph[i] - last_ph) <= tol:
                eq_high = True
            last_ph = ph[i]
        if pl[i] is not None:
            if last_pl is not None and tol > 0 and abs(pl[i] - last_pl) <= tol:
                eq_low = True
            last_pl = pl[i]
        bull_ob = bear_ob = False
        if a is not None and i >= 1:
            strong_up = (closes[i] - opens[i]) > ob_atr_mult * a
            strong_down = (opens[i] - closes[i]) > ob_atr_mult * a
            bull_ob = strong_up and closes[i - 1] < opens[i - 1]
            bear_ob = strong_down and closes[i - 1] > opens[i - 1]
        vol_node = (
            vol_avg[i] is not None
            and vol_hi[i] is not None
            and volumes[i] > volume_mult * vol_avg[i]
            and volumes[i] >= vol_hi[i]
        )
        if eq_high or eq_low or bull_ob or bear_ob or vol_node:
            zone_flag[i] = 1.0
            zone_confidence[i] = confidence[i]

    series = {
        "confidence": confidence,
        "zone_confidence": zone_confidence,
        "zone_flag": zone_flag,
        "f1_volume": f1,
        "f2_htf_align": f2,
        "f3_displacement": f3,
        "htf_bias": htf_bias,
    }
    return IndicatorResult(series=series, primary="confidence")


def analyze(bars: list[Bar], *, horizon: int | None = None, **overrides: float) -> tuple[IndicatorResult, CorrelationReport, int]:
    """Compute the indicator AND cross-analyze its confidence vs the FORWARD absolute return — the honest test
    of whether the classifier's number predicts the large moves it claims to. Returns (result, report, horizon).
    The horizon defaults to `eval_window` (the same window the classifier was trained to predict)."""
    result = compute(bars, **overrides)
    p = {**DEFAULTS, **overrides}
    h = int(horizon if horizon is not None else p["eval_window"])
    report = correlate(result.series["confidence"], forward_abs_return(bars, h))
    return result, report, h


_SERIES_KEYS = (
    "confidence",
    "zone_confidence",
    "zone_flag",
    "f1_volume",
    "f2_htf_align",
    "f3_displacement",
    "htf_bias",
)


# ---------------------------------------------------------------- causal series primitives


def _true_range(highs: list[float], lows: list[float], closes: list[float]) -> list[float]:
    tr = [highs[0] - lows[0]] if highs else []
    for i in range(1, len(closes)):
        tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    return tr


def _rma(values: list[float], length: int) -> list[float | None]:
    """Wilder's running moving average (Pine `ta.rma`, the basis of `ta.atr`). Causal, recursive."""
    out: list[float | None] = [None] * len(values)
    if len(values) < length:
        return out
    seed = statistics.fmean(values[:length])
    out[length - 1] = seed
    prev = seed
    for i in range(length, len(values)):
        prev = (prev * (length - 1) + values[i]) / length
        out[i] = prev
    return out


def _sma(values: list[float], length: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    for i in range(length - 1, len(values)):
        out[i] = statistics.fmean(values[i - length + 1 : i + 1])
    return out


def _rolling_max(values: list[float], length: int) -> list[float | None]:
    """Max over the last `length` bars INCLUDING the current one (Pine `ta.highest`)."""
    out: list[float | None] = [None] * len(values)
    for i in range(length - 1, len(values)):
        out[i] = max(values[i - length + 1 : i + 1])
    return out


def _pivot_high(highs: list[float], left: int, right: int) -> list[float | None]:
    """Pine `ta.pivothigh`: a pivot `right` bars back, confirmed at the current bar (value known only now).
    The pivot value is placed at the CONFIRM bar, so the series is causal."""
    out: list[float | None] = [None] * len(highs)
    for i in range(left + right, len(highs)):
        c = i - right
        window = highs[i - left - right : i + 1]
        if highs[c] == max(window) and highs[c] > max(highs[i - left - right : c] + highs[c + 1 : i + 1] or [float("-inf")]):
            out[i] = highs[c]
    return out


def _pivot_low(lows: list[float], left: int, right: int) -> list[float | None]:
    out: list[float | None] = [None] * len(lows)
    for i in range(left + right, len(lows)):
        c = i - right
        window = lows[i - left - right : i + 1]
        if lows[c] == min(window) and lows[c] < min(lows[i - left - right : c] + lows[c + 1 : i + 1] or [float("inf")]):
            out[i] = lows[c]
    return out


def _htf_levels(
    opens: list[float], highs: list[float], lows: list[float], closes: list[float], htf_n: int
) -> tuple[list[float | None], list[float | None], list[float | None], list[float | None]]:
    """Approximate higher-timeframe O/H/L/C by aggregating every `htf_n` bars into an HTF candle, and at each
    bar exposing only the LAST FULLY CLOSED HTF candle (mirrors the Pine `[1]` offset + lookahead_off, so no
    HTF repaint / look-ahead). Bars before the first closed HTF block get None (neutral)."""
    n = len(closes)
    htf_o: list[float | None] = [None] * n
    htf_h: list[float | None] = [None] * n
    htf_l: list[float | None] = [None] * n
    htf_c: list[float | None] = [None] * n
    nblocks = n // htf_n
    block_o = [opens[b * htf_n] for b in range(nblocks)]
    block_h = [max(highs[b * htf_n : (b + 1) * htf_n]) for b in range(nblocks)]
    block_l = [min(lows[b * htf_n : (b + 1) * htf_n]) for b in range(nblocks)]
    block_c = [closes[(b + 1) * htf_n - 1] for b in range(nblocks)]
    for i in range(n):
        block = i // htf_n
        if block >= 1:  # block-1 is fully closed strictly before bar i
            cb = block - 1
            htf_o[i], htf_h[i], htf_l[i], htf_c[i] = block_o[cb], block_h[cb], block_l[cb], block_c[cb]
    return htf_o, htf_h, htf_l, htf_c


def _knn_confidence(
    qf1: float,
    qf2: float,
    qf3: float,
    k: int,
    train_f1: list[float],
    train_f2: list[float],
    train_f3: list[float],
    train_y: list[float],
) -> float:
    """Confidence = share of the k nearest training samples (Euclidean over the 3-feature space) labelled
    'high probability', x100. Mirrors the published partial-selection-sort KNN."""
    n = len(train_y)
    dists = [
        math.sqrt((qf1 - train_f1[i]) ** 2 + (qf2 - train_f2[i]) ** 2 + (qf3 - train_f3[i]) ** 2)
        for i in range(n)
    ]
    k_eff = min(k, n)
    nearest = sorted(range(n), key=lambda i: dists[i])[:k_eff]
    votes = sum(int(train_y[i]) for i in nearest)
    return votes / float(k_eff) * 100.0


def _demo() -> None:
    """Display the live number + cross-analysis on deterministic fixture bars (offline). Run with
    `python -m cosmu.research.pine_indicators.ml_liquidity_zone`."""
    from cosmu.research.fixtures import edge_bearing_screen_market

    market = edge_bearing_screen_market(seed=3, n=600)
    print(f"=== {name} — computed data source ===")
    for symbol, bars in market.items():
        res, report, horizon = analyze(bars)
        latest = res.latest()
        computed = sum(1 for v in res.series["confidence"] if v is not None)
        zones = int(sum(res.series["zone_flag"]))
        pear = "n/a" if report.pearson is None else f"{report.pearson:+.3f}"
        spear = "n/a" if report.spearman is None else f"{report.spearman:+.3f}"
        lift = "n/a" if report.top_quartile_lift is None else f"{report.top_quartile_lift:+.1%}"
        latest_str = "n/a" if latest is None else f"{latest:5.1f}"
        print(
            f"{symbol:10s} confidence={latest_str}  bars={computed:4d}  zones={zones:3d}  "
            f"corr(vs |ret| {horizon}b): pearson={pear} spearman={spear} top-q-lift={lift}"
        )
    print(
        "\nconfidence = KNN predicted P(>N*ATR move in the next eval_window bars), point-in-time.\n"
        "near-zero correlation on synthetic bars is EXPECTED — run on real bars + route through the Gate\n"
        "before trusting it. as_altdata() exposes the series for a point-in-time feature join."
    )


if __name__ == "__main__":
    _demo()
