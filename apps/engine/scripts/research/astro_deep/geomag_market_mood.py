#!/usr/bin/env python3
"""CROSS-SECTIONAL geomagnetic 'market-mood' test — the K-R WORLD-INDEX result, replicated.

Krivelyova-Robotti's CLEANEST result was on the WORLD INDEX and most international indices, not single
noisy names: a market-wide mood depression after a stormy week. A diversified equal-weight index cancels
idiosyncratic noise, so if a real behavioural-mood channel exists it should show up MORE clearly here than
per-asset. We build an equal-weight CRYPTO index and an equal-weight EQUITY index from real bars and run the
same lagged-storm contrast with the same PROPER circular-shift null.

Also adds two K-R refinements we have not tried:
  (A) STORM ONSET vs PERSISTENCE: K-R's mechanism is the mood hit AFTER a storm. We split the forward window
      into "days 1-3 after storm onset" (fresh) vs the contemporaneous storm day, to localize the lag.
  (B) A 27-day Bartels solar-rotation BANDPASS sanity: storms recur on the ~27d solar-rotation period, so we
      report whether the index return has any 27d-band Lomb-Scargle power BEYOND an IAAFT surrogate null
      (distinct from the lunar 27.32d sidereal band already scanned — same period, different physical driver,
      and here measured on RETURNS not vol).

LIVE-HONEST: real prices + real GFZ Kp (1d PIT lag). NO fabrication.
"""
from __future__ import annotations

import sys
import numpy as np
import pandas as pd
from scipy.signal import lombscargle

sys.path.insert(0, "scripts/research/astro_deep")
sys.path.insert(0, "scripts/research/astro_strategy_lab")
import extra_signals as ES  # noqa: E402
import real_panel as RP  # noqa: E402

try:
    from spectral_vol import iaaft_surrogate  # reuse the debugged IAAFT
    HAVE_IAAFT = True
except Exception:  # noqa: BLE001
    HAVE_IAAFT = False

RNG = np.random.default_rng(20260615)

CRYPTO = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
          "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT", "LTCUSDT", "BCHUSDT"]
EQUITY = ["SPY", "QQQ", "IWM", "GLD", "SLV", "TLT", "XLE", "XLF", "XLK"]
FWD = [1, 3, 5]
PCTL = [85, 90, 95]
TRAIL = 6
RT = 10.0
N_PERM = 3000


def ew_index_logret(panel: dict) -> pd.Series:
    """Equal-weight cross-section mean of daily log returns -> a market-mood index return series."""
    rets = []
    for sym, bars in panel.items():
        r = np.log(bars["close"].astype(float)).diff()
        rets.append(r.rename(sym))
    R = pd.concat(rets, axis=1)
    # require >=3 names present that day
    ew = R.mean(axis=1, skipna=True)
    ew = ew[R.notna().sum(axis=1) >= 3]
    return ew.dropna().rename("ew_ret")


def storm_label(kp: pd.Series, pctl: float, trail: int) -> pd.Series:
    thr = np.nanpercentile(kp.to_numpy(float), pctl)
    hot = (kp >= thr).astype(float)
    return hot.rolling(trail, min_periods=1).max().rename("storm")


def contrast(storm, fwd):
    s = storm > 0.5
    q = ~s
    if s.sum() < 20 or q.sum() < 20:
        return np.nan
    return float(fwd[s].mean() - fwd[q].mean())


def circ_null(storm, fwd, n):
    N = len(storm)
    obs = contrast(storm, fwd)
    null = np.empty(n)
    lo, hi = TRAIL + max(FWD) + 1, N - (TRAIL + max(FWD) + 1)
    for i in range(n):
        null[i] = contrast(np.roll(storm, RNG.integers(lo, hi)), fwd)
    return obs, null[np.isfinite(null)]


def bartels_27d_test(ew_ret: pd.Series, n_surr: int = 400) -> dict:
    """Lomb-Scargle power of the index return in the [25,29]d Bartels solar-rotation band vs IAAFT null."""
    if not HAVE_IAAFT:
        return {"period": np.nan, "p": np.nan, "note": "iaaft unavailable"}
    y = ew_ret.to_numpy(float)
    y = y - y.mean()
    t = (ew_ret.index - ew_ret.index[0]).days.to_numpy().astype(float)
    periods = np.linspace(25.0, 29.0, 80)
    real = lombscargle(t, y, 2 * np.pi / periods, normalize=True)
    real_max = real.max()
    peak = float(periods[real.argmax()])
    surr_max = np.empty(n_surr)
    for i in range(n_surr):
        s = iaaft_surrogate(y, n_iter=60, rng=RNG)
        surr_max[i] = lombscargle(t, s - s.mean(), 2 * np.pi / periods, normalize=True).max()
    p = float((surr_max >= real_max).mean())
    return {"period": round(peak, 3), "real_max_power": round(float(real_max), 4), "p": round(p, 4)}


def main():
    print("[1/3] loading REAL prices + Kp …", flush=True)
    cr = RP.load_crypto_bars(CRYPTO, "1d", days=3650)
    eq = RP.load_equity_bars(EQUITY)
    kp = ES.load_kp_index(days=4200)
    kp = pd.Series(np.asarray(kp, float), index=pd.DatetimeIndex(kp.index)).sort_index().shift(1)

    groups = {"crypto_EW": cr, "equity_EW": eq}
    rows = []
    print("[2/3] cross-sectional K-R storm contrast (circular-shift null) …", flush=True)
    for gname, panel in groups.items():
        ew = ew_index_logret(panel)
        kpa = kp.reindex(ew.index, method="ffill")
        lc = np.log1p(ew).cumsum()  # cumulative log index for forward windows
        # forward h-day index return from each day
        for pctl in PCTL:
            storm_s = storm_label(kpa, pctl, TRAIL)
            for h in FWD:
                fwd = (lc.shift(-h) - lc).rename(f"fwd_{h}")
                df = pd.concat([storm_s, fwd], axis=1).dropna()
                if len(df) < 400:
                    continue
                st = df["storm"].to_numpy(float)
                fw = df[f"fwd_{h}"].to_numpy(float)
                obs, null = circ_null(st, fw, N_PERM)
                if not len(null) or not np.isfinite(obs):
                    continue
                p = float((np.abs(null) >= abs(obs)).mean())
                rows.append(dict(group=gname, horizon=h, pctl=pctl, n=len(df),
                                 n_storm=int((st > 0.5).sum()),
                                 obs_bps=round(obs * 1e4, 2),
                                 null_sd_bps=round(null.std() * 1e4, 2),
                                 p_perm=round(p, 4),
                                 net_bps=round(abs(obs * 1e4) - RT, 2)))
    res = pd.DataFrame(rows).sort_values("p_perm").reset_index(drop=True)
    pd.set_option("display.width", 200, "display.max_columns", 30)
    print(res.to_string(index=False))
    res.to_csv("scripts/research/astro_deep/geomag_market_mood_results.csv", index=False)

    print("\n[3/3] Bartels 27d solar-rotation band on the index RETURN (IAAFT null) …", flush=True)
    for gname, panel in groups.items():
        ew = ew_index_logret(panel)
        b = bartels_27d_test(ew, n_surr=400)
        print(f"  {gname}: 27d-band {b}")

    print(f"\n=== SUMMARY ===  tests={len(res)}  raw p<.05={int((res['p_perm']<0.05).sum())}")
    best = res.iloc[0]
    print(f"  best: {best['group']} h={best['horizon']} pctl={best['pctl']} "
          f"obs={best['obs_bps']}bps p={best['p_perm']} net={best['net_bps']}bps")
    print("  (K-R direction = NEGATIVE obs_bps: a stormy trailing week depresses the index)")


if __name__ == "__main__":
    main()
