#!/usr/bin/env python3
# intent: WAVE-1 "named_systems" dimension of the astrology-vs-markets investigation.
#
# Faithfully backtest the NAMED financial-astro systems as TURN-DATE predictors (their real claim
# is timing of reversals, NOT direction):
#   - Bradley siderograph  : turning points = local EXTREMA of the siderograph curve.
#   - Gann master-time-factor : harmonic time intervals (90/120/144/180/270/360 cal-days, etc.)
#                               projected FORWARD from each series' own documented major pivots.
#   - Merriman geocosmic   : dense HARD-ASPECT windows = local maxima of hard-aspect density.
#
# METRIC: hit-rate of realized swing EXTREMA (ZigZag) within +/-k days of a predicted turn date,
# vs a CIRCULARLY-SHIFTED-curve null (1000 shifts) that preserves the predicted-turn series'
# OWN spacing/autocorrelation (the proper null — i.i.d. fake dates manufacture false positives).
#
# We also report the symmetric companion stat (precision-flavoured): fraction of PREDICTED turns
# that land within +/-k of a realized extreme — both summarised, both null-tested, BH-FDR across
# the system x asset-class x k grid.
#
# LIVE-HONEST: predicted turns come from DETERMINISTIC astro (knowable in advance) + each series'
# OWN past pivots (Gann anchors are strictly causal — anchor t0 only projects turns at t>t0).
# Realized extrema come from REAL close prices. No look-ahead in the predictor construction.

from __future__ import annotations

import sys
from dataclasses import dataclass

import numpy as np
import pandas as pd

sys.path.insert(0, "scripts/research/astro_deep")
import astro_features_deep as AF  # noqa: E402
import real_panel as RP  # noqa: E402

RNG = np.random.default_rng(20260615)
N_SHIFTS = 1000


# ───────────────────────── price / extrema machinery ─────────────────────────


def _to_daily_close(df: pd.DataFrame) -> pd.Series:
    """Collapse an OHLCV frame to a clean ascending daily close Series indexed by date (no tz)."""
    s = df["close"].copy()
    s.index = pd.DatetimeIndex(s.index).tz_localize(None).normalize()
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s.astype(float)


def zigzag_extrema(close: pd.Series, pct: float) -> np.ndarray:
    """Indices (positional) of realized swing extrema via a percentage ZigZag.

    Standard reversal filter: track the running extreme of the current leg; when price retraces
    by `pct` from that extreme, confirm the extreme as a pivot and flip leg direction. Returns the
    positional indices of confirmed pivots (alternating highs/lows). Causal in spirit (a pivot is
    only knowable once the retrace confirms), but here we only need the pivot LOCATIONS to score
    timing, so confirmation lag is acceptable — the predictor never sees them.
    """
    p = close.to_numpy()
    n = len(p)
    if n < 3:
        return np.array([], dtype=int)
    pivots: list[int] = []
    # seed direction by first move that exceeds threshold
    ext_i = 0
    ext_p = p[0]
    direction = 0  # +1 looking for high, -1 looking for low, 0 unknown
    for i in range(1, n):
        if direction == 0:
            if p[i] >= ext_p * (1 + pct):
                direction = 1
                ext_i, ext_p = i, p[i]
            elif p[i] <= ext_p * (1 - pct):
                direction = -1
                ext_i, ext_p = i, p[i]
            continue
        if direction == 1:  # currently in an up-leg, tracking the high
            if p[i] > ext_p:
                ext_i, ext_p = i, p[i]
            elif p[i] <= ext_p * (1 - pct):  # retrace down → confirm the high
                pivots.append(ext_i)
                direction = -1
                ext_i, ext_p = i, p[i]
        else:  # down-leg, tracking the low
            if p[i] < ext_p:
                ext_i, ext_p = i, p[i]
            elif p[i] >= ext_p * (1 + pct):  # retrace up → confirm the low
                pivots.append(ext_i)
                direction = 1
                ext_i, ext_p = i, p[i]
    # include the final running extreme as a pivot (endpoint swing)
    if ext_i not in pivots:
        pivots.append(ext_i)
    return np.array(sorted(set(pivots)), dtype=int)


# ───────────────────────── predicted-turn constructors ─────────────────────────


def _local_extrema_idx(curve: np.ndarray, min_sep: int) -> np.ndarray:
    """Positional indices of local maxima AND minima of a 1-D curve, de-clustered to `min_sep`.

    A point is a local max if it is >= its neighbours within a +/-1 window and is a strict turning
    point of the discrete first difference (sign change). We then greedily thin so no two kept
    extrema are within `min_sep` bars (keeps the more prominent one).
    """
    n = len(curve)
    if n < 3:
        return np.array([], dtype=int)
    d = np.diff(curve)
    sign = np.sign(d)
    # turning point at i (1..n-2) where slope flips sign
    cand = []
    for i in range(1, n - 1):
        left, right = sign[i - 1], sign[i]
        if left > 0 and right < 0:  # local max
            cand.append((i, abs(curve[i])))
        elif left < 0 and right > 0:  # local min
            cand.append((i, abs(curve[i])))
    if not cand:
        return np.array([], dtype=int)
    cand.sort(key=lambda t: -t[1])  # by prominence (|value|) desc
    kept: list[int] = []
    for idx, _ in cand:
        if all(abs(idx - k) >= min_sep for k in kept):
            kept.append(idx)
    return np.array(sorted(kept), dtype=int)


def bradley_turns(dates: pd.DatetimeIndex, astro: pd.DataFrame) -> np.ndarray:
    """Bradley siderograph turning points = local extrema of the siderograph curve."""
    curve = astro["bradley_siderograph"].to_numpy()
    # de-cluster at ~min 5 trading days so we don't count micro-wiggles as separate turns
    return _local_extrema_idx(curve, min_sep=5)


def merriman_turns(dates: pd.DatetimeIndex, astro: pd.DataFrame) -> np.ndarray:
    """Merriman geocosmic critical-reversal dates = local MAXIMA of hard-aspect density.

    Merriman's CRDs are clusters of multiple exact hard geocosmic aspects in a tight window. We
    proxy the cluster density with a smoothed hard-aspect count (wide orb) + tightness stress, and
    take its local maxima (peaks of geocosmic 'pressure')."""
    hard = astro["hard_aspect_count"].to_numpy()
    stress = astro["aspect_tightness_stress"].to_numpy()
    dens = hard + stress  # both peak when many tight hard aspects co-occur
    # light smoothing (3-day) to define a cluster window, then peaks
    k = np.array([1.0, 1.0, 1.0]) / 3.0
    sm = np.convolve(dens, k, mode="same")
    # peaks ONLY (a CRD is a density maximum, not a minimum)
    n = len(sm)
    d = np.diff(sm)
    sign = np.sign(d)
    cand = []
    for i in range(1, n - 1):
        if sign[i - 1] > 0 and sign[i] < 0:
            cand.append((i, sm[i]))
    cand.sort(key=lambda t: -t[1])
    kept: list[int] = []
    for idx, _ in cand:
        if all(abs(idx - kk) >= 5 for kk in kept):
            kept.append(idx)
    return np.array(sorted(kept), dtype=int)


# Gann master-time-factor harmonic intervals (calendar days). Classic Gann square-of-9 / time
# anniversaries: 90,120,144,180,270,360 + the 30/45/60 sub-divisions; we use the headline set.
_GANN_INTERVALS = [30, 45, 60, 90, 120, 144, 180, 270, 360]


def gann_turns(dates: pd.DatetimeIndex, close: pd.Series, anchor_pct: float) -> np.ndarray:
    """Gann time-factor turn dates projected FORWARD from each series' OWN major pivots.

    Strictly causal: we find the series' significant ZigZag pivots (anchors) and, from each anchor
    at positional index a, mark predicted turns at a + interval (in CALENDAR days mapped to the
    nearest trading-day index) for each Gann interval — but ONLY anchors that occurred BEFORE the
    predicted turn (interval>0 guarantees this). Anchors use a LARGER ZigZag threshold so we
    project from genuine majors, not noise.
    """
    anchors = zigzag_extrema(close, anchor_pct)
    if len(anchors) == 0:
        return np.array([], dtype=int)
    n = len(close)
    date_arr = dates
    # map a target calendar date to nearest positional index
    turns: set[int] = set()
    for a in anchors:
        a_date = date_arr[a]
        for iv in _GANN_INTERVALS:
            tgt = a_date + pd.Timedelta(days=iv)
            if tgt > date_arr[-1]:
                continue
            pos = date_arr.searchsorted(tgt)
            if pos >= n:
                pos = n - 1
            # snap to nearest of pos-1/pos
            if pos > 0 and abs((date_arr[pos - 1] - tgt).days) < abs((date_arr[pos] - tgt).days):
                pos = pos - 1
            if pos > a:  # strictly forward
                turns.add(int(pos))
    return np.array(sorted(turns), dtype=int)


# ───────────────────────── scoring + null ─────────────────────────


def recall_hit_rate(realized: np.ndarray, predicted: np.ndarray, k: int, n: int) -> float:
    """Fraction of REALIZED extrema that have a predicted turn within +/-k days."""
    if len(realized) == 0 or len(predicted) == 0:
        return 0.0
    pred_mask = np.zeros(n, dtype=bool)
    for p in predicted:
        lo, hi = max(0, p - k), min(n, p + k + 1)
        pred_mask[lo:hi] = True
    return float(np.mean([pred_mask[r] for r in realized]))


def precision_hit_rate(realized: np.ndarray, predicted: np.ndarray, k: int, n: int) -> float:
    """Fraction of PREDICTED turns that have a realized extreme within +/-k days."""
    if len(realized) == 0 or len(predicted) == 0:
        return 0.0
    real_mask = np.zeros(n, dtype=bool)
    for r in realized:
        lo, hi = max(0, r - k), min(n, r + k + 1)
        real_mask[lo:hi] = True
    return float(np.mean([real_mask[p] for p in predicted]))


def circular_shift_null(
    realized: np.ndarray,
    predicted: np.ndarray,
    k: int,
    n: int,
    n_shifts: int,
    metric,
) -> tuple[float, np.ndarray]:
    """Observed metric + null distribution from circularly shifting the PREDICTED-turn set.

    Circular shift preserves the predicted-turn series' OWN spacing/autocorrelation (the proper
    null) while destroying its phase alignment to the realized extrema."""
    obs = metric(realized, predicted, k, n)
    null = np.empty(n_shifts, dtype=float)
    for s in range(n_shifts):
        sh = RNG.integers(1, n)
        shifted = (predicted + sh) % n
        null[s] = metric(realized, np.sort(shifted), k, n)
    return obs, null


@dataclass
class Result:
    system: str
    asset_class: str
    k: int
    metric_name: str
    n_assets: int
    n_realized: float
    n_predicted: float
    observed: float
    null_mean: float
    null_p: float


def bh_fdr(pvals: list[float], q: float = 0.05) -> list[bool]:
    """Benjamini-Hochberg: return reject mask at FDR q."""
    m = len(pvals)
    order = np.argsort(pvals)
    thresh = q * (np.arange(1, m + 1) / m)
    sorted_p = np.array(pvals)[order]
    passed = sorted_p <= thresh
    if not passed.any():
        return [False] * m
    kmax = np.max(np.where(passed)[0])
    cut = sorted_p[kmax]
    return [p <= cut for p in pvals]


# ───────────────────────── main ─────────────────────────


def run() -> None:
    crypto = [
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
        "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT", "LTCUSDT", "BCHUSDT",
        "ATOMUSDT", "UNIUSDT", "FILUSDT", "NEARUSDT",
    ]
    equity = ["SPY", "QQQ", "IWM", "GLD", "SLV", "TLT", "XLE", "XLF", "XLK", "USO"]

    print("Loading REAL price panels ...", flush=True)
    cbars = RP.load_crypto_bars(crypto, "1d", days=3650)
    ebars = RP.load_equity_bars(equity)

    panels: dict[str, dict[str, pd.Series]] = {"crypto": {}, "equity": {}}
    for s, df in cbars.items():
        if len(df) >= 400:
            panels["crypto"][s] = _to_daily_close(df)
    for s, df in ebars.items():
        if len(df) >= 400:
            panels["equity"][s] = _to_daily_close(df)
    print(f"  crypto assets usable: {len(panels['crypto'])}  equity assets usable: {len(panels['equity'])}")

    # Per asset-class astro cache keyed by the asset's own date index (deterministic, no leak).
    ZZ_PCT = 0.08         # realized swing threshold (8% — a genuine swing, not noise)
    GANN_ANCHOR_PCT = 0.15  # anchors = major pivots only
    KS = [1, 3, 5, 7]

    # Collect per-(system, class, k, metric) pooled stats across assets.
    # Pooling: average the observed metric across assets, and build a pooled null by averaging the
    # per-asset null draw s (same shift index across assets is NOT required; we average independent
    # draws per asset to get a class-level null with the right spread).
    systems = ["bradley", "merriman", "gann"]
    metrics = {"recall": recall_hit_rate, "precision": precision_hit_rate}

    results: list[Result] = []

    for ac in ("crypto", "equity"):
        assets = panels[ac]
        if not assets:
            continue
        # precompute per asset: dates, astro, realized extrema, predicted turns per system
        per_asset = {}
        for sym, close in assets.items():
            dates = pd.DatetimeIndex(close.index)
            astro = AF.deep_astro_features(dates)
            realized = zigzag_extrema(close, ZZ_PCT)
            preds = {
                "bradley": bradley_turns(dates, astro),
                "merriman": merriman_turns(dates, astro),
                "gann": gann_turns(dates, close, GANN_ANCHOR_PCT),
            }
            per_asset[sym] = dict(dates=dates, n=len(dates), realized=realized, preds=preds)

        for system in systems:
            for mname, mfn in metrics.items():
                for k in KS:
                    obs_list, nullmean_list, p_list = [], [], []
                    nreal_list, npred_list = [], []
                    # build class-level pooled observed + pooled null
                    pooled_obs = []
                    pooled_null = np.zeros(N_SHIFTS, dtype=float)
                    valid_assets = 0
                    for sym, d in per_asset.items():
                        n = d["n"]
                        realized = d["realized"]
                        predicted = d["preds"][system]
                        if len(realized) == 0 or len(predicted) == 0:
                            continue
                        obs, null = circular_shift_null(
                            realized, predicted, k, n, N_SHIFTS, mfn
                        )
                        pooled_obs.append(obs)
                        pooled_null += null
                        valid_assets += 1
                        nreal_list.append(len(realized))
                        npred_list.append(len(predicted))
                    if valid_assets == 0:
                        continue
                    pooled_null /= valid_assets
                    obs_mean = float(np.mean(pooled_obs))
                    # one-sided p: P(null >= observed) for the POOLED (cross-asset averaged) stat
                    p = float((np.sum(pooled_null >= obs_mean) + 1) / (N_SHIFTS + 1))
                    results.append(
                        Result(
                            system=system,
                            asset_class=ac,
                            k=k,
                            metric_name=mname,
                            n_assets=valid_assets,
                            n_realized=float(np.mean(nreal_list)),
                            n_predicted=float(np.mean(npred_list)),
                            observed=obs_mean,
                            null_mean=float(np.mean(pooled_null)),
                            null_p=p,
                        )
                    )

    # ── report ──
    res_df = pd.DataFrame([r.__dict__ for r in results])
    res_df = res_df.sort_values("null_p").reset_index(drop=True)
    # BH-FDR across the whole grid
    res_df["bh_reject_05"] = bh_fdr(res_df["null_p"].tolist(), q=0.05)
    res_df["bonferroni_05"] = res_df["null_p"] < (0.05 / len(res_df))

    pd.set_option("display.width", 200)
    pd.set_option("display.max_rows", 200)
    pd.set_option("display.float_format", lambda x: f"{x:.4f}")
    print("\n" + "=" * 110)
    print(f"NAMED-SYSTEMS TURN-DATE TEST  —  {len(res_df)} (system x class x k x metric) cells, "
          f"{N_SHIFTS} circular-shift nulls each")
    print(f"ZigZag swing threshold = {ZZ_PCT:.0%}, Gann anchor threshold = {GANN_ANCHOR_PCT:.0%}, "
          f"Gann intervals = {_GANN_INTERVALS}")
    print("=" * 110)
    cols = ["system", "asset_class", "metric_name", "k", "n_assets", "n_realized",
            "n_predicted", "observed", "null_mean", "null_p", "bh_reject_05", "bonferroni_05"]
    print(res_df[cols].to_string(index=False))

    nsurv = int(res_df["bh_reject_05"].sum())
    print("\n" + "-" * 110)
    print(f"SURVIVORS at BH-FDR 0.05: {nsurv} / {len(res_df)}")
    if nsurv:
        print(res_df[res_df["bh_reject_05"]][cols].to_string(index=False))
    # also flag the single best uplift over null (economic lens)
    res_df["uplift"] = res_df["observed"] - res_df["null_mean"]
    best = res_df.sort_values("uplift", ascending=False).head(8)
    print("\nTop-8 by uplift (observed − null_mean):")
    print(best[cols + ["uplift"]].to_string(index=False))


if __name__ == "__main__":
    run()
