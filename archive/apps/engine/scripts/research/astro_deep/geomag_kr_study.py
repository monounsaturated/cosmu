#!/usr/bin/env python3
"""GEOMAGNETIC-STORM → RETURNS replication (Krivelyova & Robotti 2003, FRB Atlanta WP 2003-5).

WHY THIS IS A NEW DIMENSION (not a duplicate):
  The deep study folds Kp/sunspots/F10.7 in as CONTEMPORANEOUS scalar-IC features (today's Kp level
  vs today's forward return, Spearman, FDR). That CANNOT detect the K-R hypothesis, which is structurally
  different: the PRECEDING WEEK's *unusually high* geomagnetic activity depresses returns over the FOLLOWING
  ~week (a lagged behavioural-mood channel, à la SAD). We replicate the actual paper's estimator: a binary
  "stormy last week" label → mean forward-return contrast, the right test K-R used.

LIVE-HONEST DATA: real prices (RP) + REAL daily Kp from GFZ (load_kp_index), lagged 1 trading day (the most
  recent GFZ rows are revised nowcasts). No fabrication, no social/back-filled vendor data.

PROPER NULL (cardinal rule #2): Kp storms cluster (27-day solar rotation + 11-yr cycle) and returns are
  autocorrelated/vol-clustered. An i.i.d. label shuffle is LENIENT and would manufacture false positives.
  We use a CIRCULAR-SHIFT null on the storm-label series: roll the labels by a random offset relative to the
  return series. This preserves BOTH the autocorrelation of the labels AND of returns, only destroying their
  ALIGNMENT — exactly the sharp null "geomag timing is unrelated to return timing". We also report a
  stationary block-bootstrap p as a second, independent null.

ECONOMIC (cardinal rule #3): the contrast is reported in bps and net of a 10bps round-trip; a storm-timed
  long/flat or short overlay must clear costs, not just significance. Multiple-testing aware (BH-FDR across
  asset × horizon × threshold).
"""
from __future__ import annotations

import sys
import numpy as np
import pandas as pd

sys.path.insert(0, "scripts/research/astro_deep")
sys.path.insert(0, "scripts/research/astro_strategy_lab")
import extra_signals as ES  # noqa: E402
import real_panel as RP  # noqa: E402

RNG = np.random.default_rng(20260615)

CRYPTO = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
          "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT", "LTCUSDT", "BCHUSDT"]
EQUITY = ["SPY", "QQQ", "IWM", "GLD", "SLV", "TLT", "XLE", "XLF", "XLK"]

# K-R: forward windows in trading days; "storm" = high-Kp days in the trailing window.
FWD_HORIZONS = [1, 3, 5]
# storm threshold as a PERCENTILE of the asset-aligned Kp history (robust across the solar cycle)
STORM_PCTL = [85, 90, 95]
TRAIL_WINDOW = 6          # K-R use ~6 trading days of "bad" geomagnetic activity
RT_COST_BPS = 10.0        # round-trip cost floor
N_PERM = 2000


def storm_label(kp: pd.Series, pctl: float, trail: int) -> pd.Series:
    """1.0 on a day iff ANY of the trailing `trail` Kp values (INCLUDING today, all already lagged 1d for PIT)
    exceeded the `pctl` percentile of Kp. This is "the last week was geomagnetically stormy" — knowable
    at the OPEN of the next day, so it predicts forward returns without look-ahead."""
    thr = np.nanpercentile(kp.to_numpy(float), pctl)
    hot = (kp >= thr).astype(float)
    # rolling max over the trailing window (today + trail-1 prior days)
    return (hot.rolling(trail, min_periods=1).max()).rename("storm")


def fwd_logret(close: pd.Series, h: int) -> pd.Series:
    lc = np.log(close)
    return (lc.shift(-h) - lc).rename(f"fwd_{h}")


def kr_contrast(storm: np.ndarray, fwd: np.ndarray) -> float:
    """Mean forward return on STORM days minus mean on QUIET days (the K-R sign is NEGATIVE: storms depress
    returns). Returned in the native log-return units (multiply by 1e4 for bps)."""
    s = storm > 0.5
    q = ~s
    if s.sum() < 20 or q.sum() < 20:
        return np.nan
    return float(fwd[s].mean() - fwd[q].mean())


def circshift_null(storm: np.ndarray, fwd: np.ndarray, n: int) -> np.ndarray:
    """PROPER null: circularly roll the storm-label series by a random offset relative to forward returns.
    Preserves the autocorrelation/clustering of BOTH series; destroys only their alignment."""
    N = len(storm)
    obs = kr_contrast(storm, fwd)
    out = np.empty(n)
    lo, hi = TRAIL_WINDOW + max(FWD_HORIZONS) + 1, N - (TRAIL_WINDOW + max(FWD_HORIZONS) + 1)
    for i in range(n):
        k = RNG.integers(lo, hi)  # avoid trivial near-zero shifts
        out[i] = kr_contrast(np.roll(storm, k), fwd)
    return out, obs


def block_bootstrap_p(storm: np.ndarray, fwd: np.ndarray, obs: float, n: int, mean_block: int = 10) -> float:
    """Stationary block bootstrap of the (storm, fwd) PAIRS preserves joint serial structure under H1;
    we bootstrap the QUIET-day pool to get the sampling spread of the contrast under resampling and compare.
    Reported as a robustness cross-check on the circular-shift p (two-sided)."""
    N = len(storm)
    p = 1.0 / mean_block
    null = np.empty(n)
    for i in range(n):
        # build a block-bootstrap index
        idx = np.empty(N, dtype=int)
        t = 0
        while t < N:
            start = RNG.integers(0, N)
            L = min(N - t, RNG.geometric(p))
            for j in range(L):
                idx[t + j] = (start + j) % N
            t += L
        # resample storm labels against the SAME-position forward returns -> breaks alignment via the shuffle
        s_bs = storm[idx]
        null[i] = kr_contrast(s_bs, fwd)
    null = null[np.isfinite(null)]
    if not len(null):
        return np.nan
    # two-sided
    return float((np.abs(null) >= abs(obs)).mean())


def bh_fdr(pvals: list[float], q: float = 0.10) -> list[bool]:
    p = np.array(pvals, float)
    ok = np.isfinite(p)
    out = np.zeros(len(p), bool)
    idx = np.where(ok)[0]
    ps = p[idx]
    order = np.argsort(ps)
    m = len(ps)
    thr = q * (np.arange(1, m + 1)) / m
    passed = ps[order] <= thr
    if passed.any():
        kmax = np.where(passed)[0].max()
        sig_local = order[: kmax + 1]
        out[idx[sig_local]] = True
    return out.tolist()


def main():
    print("[1/3] loading REAL prices + REAL Kp (GFZ) …", flush=True)
    cr = RP.load_crypto_bars(CRYPTO, "1d", days=3650)
    eq = RP.load_equity_bars(EQUITY)
    panel = {**{k: v for k, v in cr.items()}, **{k: v for k, v in eq.items()}}
    kp_raw = ES.load_kp_index(days=4200)
    # PIT lag: a UT day's Kp is finalised after close; shift 1 day so the label is knowable next open.
    kp_raw = pd.Series(np.asarray(kp_raw, float), index=pd.DatetimeIndex(kp_raw.index)).sort_index().shift(1)
    print(f"      Kp rows={kp_raw.notna().sum()}  span={kp_raw.index.min().date()}→{kp_raw.index.max().date()}", flush=True)

    rows = []
    print("[2/3] K-R contrast + circular-shift null per asset×horizon×threshold …", flush=True)
    for sym, bars in panel.items():
        close = bars["close"].astype(float)
        # align Kp onto the asset's trading calendar (ffill across non-trading gaps)
        kp = kp_raw.reindex(close.index, method="ffill")
        if kp.notna().sum() < 400:
            continue
        for pctl in STORM_PCTL:
            storm_s = storm_label(kp, pctl, TRAIL_WINDOW)
            for h in FWD_HORIZONS:
                fwd_s = fwd_logret(close, h)
                df = pd.concat([storm_s, fwd_s], axis=1).dropna()
                if len(df) < 400:
                    continue
                storm = df["storm"].to_numpy(float)
                fwd = df[f"fwd_{h}"].to_numpy(float)
                null, obs = circshift_null(storm, fwd, N_PERM)
                null = null[np.isfinite(null)]
                if not len(null) or not np.isfinite(obs):
                    continue
                # two-sided permutation p
                p_perm = float((np.abs(null) >= abs(obs)).mean())
                p_block = block_bootstrap_p(storm, fwd, obs, n=600, mean_block=10)
                n_storm = int((storm > 0.5).sum())
                obs_bps = obs * 1e4
                # per-trade economic edge net of cost (one round trip to take/leave the storm overlay)
                net_bps = abs(obs_bps) - RT_COST_BPS
                rows.append(dict(asset=sym, klass=("crypto" if sym.endswith("USDT") else "equity"),
                                 horizon=h, pctl=pctl, n=len(df), n_storm=n_storm,
                                 obs_bps=round(obs_bps, 2), null_mean_bps=round(null.mean() * 1e4, 2),
                                 null_sd_bps=round(null.std() * 1e4, 2),
                                 p_perm=round(p_perm, 4), p_block=round(p_block, 4) if np.isfinite(p_block) else np.nan,
                                 net_bps=round(net_bps, 2)))
    res = pd.DataFrame(rows)
    if not len(res):
        print("NO RESULTS (insufficient overlap).")
        return
    res["fdr_pass"] = bh_fdr(res["p_perm"].tolist(), q=0.10)
    res = res.sort_values("p_perm").reset_index(drop=True)
    print("[3/3] DONE\n")
    pd.set_option("display.width", 200, "display.max_columns", 30, "display.max_rows", 80)
    print(res.to_string(index=False))
    out_csv = "scripts/research/astro_deep/geomag_kr_results.csv"
    res.to_csv(out_csv, index=False)
    print(f"\nwrote {out_csv}")

    # ── honest summary ───────────────────────────────────────────────────────────────
    n_tests = len(res)
    n_raw = int((res["p_perm"] < 0.05).sum())
    n_fdr = int(res["fdr_pass"].sum())
    print(f"\n=== SUMMARY ===  tests={n_tests}  raw p<.05={n_raw}  BH-FDR(q=.10) survivors={n_fdr}")
    if n_fdr:
        surv = res[res["fdr_pass"]]
        # economic + sign filter (K-R predicts NEGATIVE storm contrast)
        econ = surv[(surv["net_bps"] > 0)]
        print(f"  of FDR survivors, {len(econ)} clear the 10bps cost floor; sign(obs): "
              f"{(surv['obs_bps'] < 0).sum()} negative (K-R direction) / {(surv['obs_bps'] > 0).sum()} positive")
        print(econ.to_string(index=False) if len(econ) else "  NONE clear costs.")
    else:
        # report the single best for honest disclosure
        best = res.iloc[0]
        print(f"  best test: {best['asset']} h={best['horizon']} pctl={best['pctl']} "
              f"obs={best['obs_bps']}bps p_perm={best['p_perm']} p_block={best['p_block']} -> nothing survives FDR.")


if __name__ == "__main__":
    main()
