#!/usr/bin/env python3
"""SAD / DAYLIGHT-LENGTH effect (Kamstra, Kramer & Levi, AER 2003) on our universe.

WHY NEW: a deterministic, latitude-conditioned ANNUAL regressor (night-length, with a fall asymmetry) that
is NOT among our 108 astro features and was NEVER tested. The hypothesis: longer nights (fall/winter) →
heightened risk aversion (SAD) → a seasonal return pattern, strongest at high latitudes, 6mo out of phase
in the Southern Hemisphere. Equities trade on a single exchange latitude (KKL anchor it to the market's
city); crypto trades 24/7 globally so the SAD channel has NO single-latitude anchor — we test crypto only as
a FALSIFICATION control (it SHOULD be null if the channel is genuinely latitude-driven biology, not a
spurious annual artefact).

KKL SAD variable (Northern Hemisphere): SADt = (nightlen_t - 12) on the fall/winter days (autumn equinox →
spring equinox), 0 otherwise. Night length from the standard sunrise-equation at the exchange latitude.

PROPER NULL (cardinal rule #2): the SAD regressor is a pure 1-cycle/yr seasonal. An i.i.d. date shuffle is
LENIENT (it ignores that returns have their OWN weak annual structure + fat tails). We use a CIRCULAR-SHIFT
null on the SAD regressor by WHOLE-YEAR-agnostic offsets (≥30d, ≤ len-30d): this keeps the annual shape of
BOTH the regressor and the realized return seasonality, destroying only their PHASE alignment. That is the
sharp null "the SAD phase is unrelated to the return phase". Effect = OLS slope (Newey-West HAC t for
disclosure) + the null distribution of the slope under phase shifts. Economic: annualized bps of the
fall-vs-rest mean spread, net of a 10bps round-trip if traded as a seasonal long/flat overlay.
"""
from __future__ import annotations

import sys
import numpy as np
import pandas as pd

sys.path.insert(0, "scripts/research/astro_deep")
sys.path.insert(0, "scripts/research/astro_strategy_lab")
import real_panel as RP  # noqa: E402

RNG = np.random.default_rng(20260615)

# Exchange-city latitudes (deg N). Equities: NYSE/Nasdaq = New York 40.7N. ETFs trade there too.
EQUITY = {s: 40.71 for s in ["SPY", "QQQ", "IWM", "GLD", "SLV", "TLT", "XLE", "XLF", "XLK"]}
# Crypto: no single latitude -> falsification control at a representative mid-lat (40.7N) AND high-lat (60N).
CRYPTO = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"]
RT_COST_BPS = 10.0
N_PERM = 3000


def night_length_hours(doy: np.ndarray, lat_deg: float) -> np.ndarray:
    """Standard sunrise-equation night length (hours) for day-of-year `doy` at latitude `lat_deg`.
    Solar declination via the cosine approximation; daylength = 2/15 * arccos(-tan φ tan δ) in degrees."""
    lat = np.radians(lat_deg)
    decl = np.radians(-23.44) * np.cos(np.radians(360.0 / 365.0 * (doy + 10)))  # +10: solstice offset
    x = -np.tan(lat) * np.tan(decl)
    x = np.clip(x, -1.0, 1.0)
    day_hours = (2.0 / 15.0) * np.degrees(np.arccos(x))
    return 24.0 - day_hours


def sad_regressor(index: pd.DatetimeIndex, lat_deg: float) -> pd.Series:
    """KKL SAD: (nightlen - 12) during the fall/winter half (autumn equinox..spring equinox), else 0.
    Northern hemisphere convention (all our latitudes are N)."""
    doy = index.dayofyear.to_numpy()
    nl = night_length_hours(doy, lat_deg)
    # fall/winter = nights longer than the equinox 12h. This precisely captures Sep21->Mar20 in the N hemis.
    sad = np.where(nl > 12.0, nl - 12.0, 0.0)
    return pd.Series(sad, index=index, name="sad")


def ols_slope_t(y: np.ndarray, x: np.ndarray, hac_lag: int = 5):
    """OLS slope of y on x (with intercept) + Newey-West HAC t. Returns (slope, t)."""
    X = np.column_stack([np.ones_like(x), x])
    XtX = X.T @ X
    try:
        b = np.linalg.solve(XtX, X.T @ y)
    except np.linalg.LinAlgError:
        return np.nan, np.nan
    resid = y - X @ b
    n, k = X.shape
    # Newey-West HAC covariance
    S = (X * resid[:, None]).T @ (X * resid[:, None])
    for l in range(1, hac_lag + 1):
        w = 1.0 - l / (hac_lag + 1)
        u = (X[l:] * resid[l:, None])
        v = (X[:-l] * resid[:-l, None])
        G = u.T @ v
        S += w * (G + G.T)
    XtX_inv = np.linalg.inv(XtX)
    cov = XtX_inv @ S @ XtX_inv
    se = np.sqrt(np.diag(cov))
    t = b[1] / se[1] if se[1] > 0 else np.nan
    return float(b[1]), float(t)


def phase_shift_null(y: np.ndarray, sad: np.ndarray, n: int):
    """Circular-shift the SAD regressor relative to returns; recompute the OLS slope each time.
    Preserves the annual shape of both series, destroying only their phase alignment."""
    N = len(y)
    obs, _ = ols_slope_t(y, sad)
    null = np.empty(n)
    lo, hi = 30, N - 30
    for i in range(n):
        k = RNG.integers(lo, hi)
        null[i], _ = ols_slope_t(y, np.roll(sad, k))
    return obs, null[np.isfinite(null)]


def bh_fdr(pvals, q=0.10):
    p = np.array(pvals, float)
    out = np.zeros(len(p), bool)
    ok = np.where(np.isfinite(p))[0]
    ps = p[ok]
    order = np.argsort(ps)
    m = len(ps)
    thr = q * np.arange(1, m + 1) / m
    passed = ps[order] <= thr
    if passed.any():
        kmax = np.where(passed)[0].max()
        out[ok[order[: kmax + 1]]] = True
    return out.tolist()


def run_for(sym, bars, lat, klass):
    close = bars["close"].astype(float)
    r = np.log(close).diff().shift(-1)  # next-day log return (predict forward, no look-ahead)
    sad = sad_regressor(close.index, lat)
    df = pd.concat([r.rename("r"), sad], axis=1).dropna()
    if len(df) < 400:
        return None
    y = df["r"].to_numpy()
    x = df["sad"].to_numpy()
    slope, t = ols_slope_t(y, x)
    obs, null = phase_shift_null(y, x, N_PERM)
    if not len(null) or not np.isfinite(obs):
        return None
    p_perm = float((np.abs(null) >= abs(obs)).mean())
    # economic: fall/winter (sad>0) vs rest mean daily return, annualized to bps
    fall = y[x > 0]
    rest = y[x == 0]
    spread_daily = (fall.mean() - rest.mean()) if (len(fall) > 20 and len(rest) > 20) else np.nan
    ann_bps = spread_daily * 252 * 1e4 if np.isfinite(spread_daily) else np.nan
    return dict(asset=sym, klass=klass, lat=lat, n=len(df), n_fall=int((x > 0).sum()),
                slope=slope, hac_t=round(t, 2) if np.isfinite(t) else np.nan,
                obs_slope=obs, null_sd=round(null.std(), 8),
                p_perm=round(p_perm, 4), fall_vs_rest_ann_bps=round(ann_bps, 1) if np.isfinite(ann_bps) else np.nan)


def main():
    print("[1/2] loading REAL prices …", flush=True)
    eq = RP.load_equity_bars(list(EQUITY))
    cr = RP.load_crypto_bars(CRYPTO, "1d", days=3650)
    rows = []
    print("[2/2] SAD slope + phase-shift null …", flush=True)
    for sym, bars in eq.items():
        rr = run_for(sym, bars, EQUITY[sym], "equity")
        if rr:
            rows.append(rr)
    # crypto control at two latitudes (40.7 + 60) — should be null if the channel is real biology
    for sym, bars in cr.items():
        for lat, tag in ((40.71, "crypto@40N"), (60.0, "crypto@60N")):
            rr = run_for(sym, bars, lat, tag)
            if rr:
                rows.append(rr)
    res = pd.DataFrame(rows).sort_values("p_perm").reset_index(drop=True)
    res["fdr_pass"] = bh_fdr(res["p_perm"].tolist(), q=0.10)
    pd.set_option("display.width", 220, "display.max_columns", 30, "display.max_rows", 80)
    print(res.to_string(index=False))
    res.to_csv("scripts/research/astro_deep/sad_daylight_results.csv", index=False)
    n_eq = res[res["klass"] == "equity"]
    print(f"\n=== SUMMARY ===  tests={len(res)}  raw p<.05={int((res['p_perm']<0.05).sum())}  "
          f"FDR survivors={int(res['fdr_pass'].sum())}")
    print(f"  equities: raw p<.05 = {int((n_eq['p_perm']<0.05).sum())}/{len(n_eq)}  "
          f"(KKL predicts a POSITIVE slope: longer nights -> higher subsequent risk premium)")
    print(f"  wrote scripts/research/astro_deep/sad_daylight_results.csv")


if __name__ == "__main__":
    main()
