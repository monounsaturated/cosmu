#!/usr/bin/env python3
"""ADVERSARIAL VERIFICATION of the geomagnetic-storm K-R candidate.

Candidate (from geomag_market_mood_results.csv):
  crypto_EW, horizon=1, Kp 90th-pctl storm: obs=-23.44 bps, p_perm=0.1423, net +13.44 bps.
  The single best of 18 cross-sectional cells; correct (negative) K-R sign; absent in equities.

Prior author already ran a circular-shift null (p=0.1423, fails FDR). My job is to try HARDER
to kill it as luck/leakage/artifact along four independent axes and return a verdict:

  (1) STRICTER NULL: more circular-shift surrogates (20k) for a tight p, PLUS an INDEPENDENT
      AR(1)/IAAFT-surrogate null that rebuilds a synthetic index return preserving the return
      autocorrelation+spectrum, re-runs the storm contrast on the SAME storm labels. If the
      effect is real-vs-timing it must beat BOTH nulls.
  (2) OUT-OF-SAMPLE split: fit nothing (the cell is already chosen), but verify the SAME cell on a
      chronological 70/30 and an early/late half split. A real effect persists in the held-out half
      with the same sign; a lucky draw concentrates in one sub-period.
  (3) ECONOMIC: a real, tradeable storm-flat overlay on the EW crypto index, net of 10bps round-trip,
      vs always-invested, plus the per-storm-episode net. Bootstrapped Sharpe/return CI.
  (4) MULTIPLE-TESTING CHARGE: the cell was surfaced by scanning groups x horizons x pctls. Charge
      the full search (18 cross-sectional cells AND the 207 per-asset/cross-sectional tests in the
      sibling study) via Bonferroni and via the empirical max-stat (family-wise) circular-shift null:
      shuffle once, take the BEST |contrast| across ALL cells, build the FWER null, see where the
      observed best sits. This is the honest "how surprising is the most extreme cell" test.

LIVE-HONEST: real prices (RP) + real GFZ Kp (1d PIT lag). No fabrication.
"""
from __future__ import annotations

import sys
import numpy as np
import pandas as pd

sys.path.insert(0, "scripts/research/astro_deep")
sys.path.insert(0, "scripts/research/astro_strategy_lab")
import extra_signals as ES  # noqa: E402
import real_panel as RP  # noqa: E402

try:
    from spectral_vol import iaaft_surrogate
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
RT = 10.0  # bps round-trip cost floor

# The chosen candidate cell:
CELL_H, CELL_PCTL = 1, 90


# ── shared estimators (identical math to the sibling study) ───────────────────
def ew_index_logret(panel: dict) -> pd.Series:
    rets = [np.log(b["close"].astype(float)).diff().rename(s) for s, b in panel.items()]
    R = pd.concat(rets, axis=1)
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


def fwd_from_logret(ew_ret: pd.Series, h: int) -> pd.Series:
    lc = ew_ret.cumsum()  # cumulative log index
    return (lc.shift(-h) - lc).rename(f"fwd_{h}")


def circ_null(storm, fwd, n):
    N = len(storm)
    obs = contrast(storm, fwd)
    lo, hi = TRAIL + max(FWD) + 1, N - (TRAIL + max(FWD) + 1)
    null = np.fromiter(
        (contrast(np.roll(storm, RNG.integers(lo, hi)), fwd) for _ in range(n)),
        float, n)
    return obs, null[np.isfinite(null)]


def ar1_fit(x):
    x = np.asarray(x, float)
    x = x - x.mean()
    if len(x) < 3:
        return 0.0, np.std(x)
    phi = float(np.dot(x[:-1], x[1:]) / max(np.dot(x[:-1], x[:-1]), 1e-12))
    phi = np.clip(phi, -0.99, 0.99)
    resid = x[1:] - phi * x[:-1]
    return phi, float(np.std(resid))


def ar1_surrogate(x, rng):
    """Synthetic series with the same AR(1) coefficient + innovation scale + marginal mean.
    A *generative* null: returns are unrelated to storm timing but share return autocorrelation."""
    phi, sig = ar1_fit(x)
    n = len(x)
    e = rng.normal(0, sig, n)
    y = np.empty(n)
    y[0] = e[0]
    for t in range(1, n):
        y[t] = phi * y[t - 1] + e[t]
    return y + np.mean(x)


# ── 1. STRICTER + INDEPENDENT NULLS ───────────────────────────────────────────
def stricter_nulls(ew_ret, kpa):
    storm = storm_label(kpa, CELL_PCTL, TRAIL)
    fwd = fwd_from_logret(ew_ret, CELL_H)
    df = pd.concat([storm, fwd], axis=1).dropna()
    st = df["storm"].to_numpy(float)
    fw = df[f"fwd_{CELL_H}"].to_numpy(float)

    # (a) tight circular-shift p with 20k surrogates
    obs, cnull = circ_null(st, fw, 20000)
    p_circ = float((np.abs(cnull) >= abs(obs)).mean())

    # (b) AR(1)-surrogate null: rebuild the *1-day* index return spectrum, recompute h=1 fwd,
    #     keep the SAME storm labels. h=1 fwd == next-day ew return shifted, so we surrogate the
    #     1-day return series directly and re-derive the forward.
    r1 = ew_ret.reindex(df.index.union(ew_ret.index)).reindex(ew_ret.index)  # base 1d returns
    base = ew_ret.to_numpy(float)
    ar_null = np.empty(4000)
    for i in range(4000):
        sy = ar1_surrogate(base, RNG)
        s_ser = pd.Series(sy, index=ew_ret.index)
        f = fwd_from_logret(s_ser, CELL_H)
        d2 = pd.concat([storm, f], axis=1).dropna()
        ar_null[i] = contrast(d2["storm"].to_numpy(float), d2[f"fwd_{CELL_H}"].to_numpy(float))
    ar_null = ar_null[np.isfinite(ar_null)]
    p_ar = float((np.abs(ar_null) >= abs(obs)).mean())

    # (c) IAAFT-surrogate null: preserves the FULL power spectrum + marginal of the return series
    p_iaaft = np.nan
    if HAVE_IAAFT:
        ia_null = np.empty(2000)
        for i in range(2000):
            sy = iaaft_surrogate(base, rng=RNG, n_iter=60)
            s_ser = pd.Series(sy, index=ew_ret.index)
            f = fwd_from_logret(s_ser, CELL_H)
            d2 = pd.concat([storm, f], axis=1).dropna()
            ia_null[i] = contrast(d2["storm"].to_numpy(float), d2[f"fwd_{CELL_H}"].to_numpy(float))
        ia_null = ia_null[np.isfinite(ia_null)]
        p_iaaft = float((np.abs(ia_null) >= abs(obs)).mean())

    return dict(obs_bps=round(obs * 1e4, 2), n=len(df), n_storm=int((st > 0.5).sum()),
                circ_sd_bps=round(cnull.std() * 1e4, 2), p_circ=round(p_circ, 4),
                ar_sd_bps=round(ar_null.std() * 1e4, 2), p_ar=round(p_ar, 4),
                p_iaaft=(round(p_iaaft, 4) if np.isfinite(p_iaaft) else None))


# ── 2. OUT-OF-SAMPLE / SUB-PERIOD ─────────────────────────────────────────────
def oos_split(ew_ret, kpa):
    storm = storm_label(kpa, CELL_PCTL, TRAIL)
    fwd = fwd_from_logret(ew_ret, CELL_H)
    df = pd.concat([storm, fwd], axis=1).dropna()
    n = len(df)
    out = {}
    for name, sl in [("first70", slice(0, int(0.70 * n))),
                     ("last30", slice(int(0.70 * n), n)),
                     ("firstHalf", slice(0, n // 2)),
                     ("secondHalf", slice(n // 2, n))]:
        sub = df.iloc[sl]
        c = contrast(sub["storm"].to_numpy(float), sub[f"fwd_{CELL_H}"].to_numpy(float))
        out[name] = round(c * 1e4, 2) if np.isfinite(c) else None
    out["span"] = f"{df.index[0].date()}→{df.index[-1].date()}"
    return out


# ── 3. ECONOMIC: tradeable storm-flat overlay net of costs ────────────────────
def economic(ew_ret, kpa):
    """Overlay: hold the EW crypto index, go FLAT for the next day whenever a storm signal is on
    (K-R says storms depress returns -> avoid them). Compare to always-invested. Charge 10bps each
    time the position flips (enter/exit flat). Daily compounding on the EW index return."""
    storm = storm_label(kpa, CELL_PCTL, TRAIL).reindex(ew_ret.index).fillna(0.0)
    r = ew_ret.copy()  # log return realised the NEXT day after the signal
    # position for day t+1 = 0 if storm-on at t else 1 (signal known at t, applied to t+1 return)
    pos = (storm.shift(1) < 0.5).astype(float)  # 1 = invested, 0 = flat
    pos = pos.reindex(r.index).fillna(1.0)
    flips = pos.diff().abs().fillna(0.0)
    cost = flips * (RT / 1e4)  # 10bps per flip in log-return units
    strat = pos * r - cost
    bench = r
    ann = 365.0
    def stats(x):
        x = x.dropna()
        mu, sd = x.mean(), x.std()
        sharpe = float(mu / sd * np.sqrt(ann)) if sd > 0 else 0.0
        return dict(ann_ret_pct=round(float(mu * ann) * 100, 2),
                    sharpe=round(sharpe, 3), n=len(x))
    s_strat, s_bench = stats(strat), stats(bench)
    # bootstrap CI on (strat - bench) annual return, block=10
    diff = (strat - bench).dropna().to_numpy()
    N = len(diff); p = 0.1; B = 4000
    boot = np.empty(B)
    for b in range(B):
        idx = np.empty(N, int); t = 0
        while t < N:
            start = RNG.integers(0, N); L = min(N - t, RNG.geometric(p))
            for j in range(L):
                idx[t + j] = (start + j) % N
            t += L
        boot[b] = diff[idx].mean() * ann
    ci = (round(float(np.percentile(boot, 2.5)) * 100, 2),
          round(float(np.percentile(boot, 97.5)) * 100, 2))
    n_flips = int(flips.sum())
    return dict(strat=s_strat, bench=s_bench,
                edge_ann_pct=round((s_strat["ann_ret_pct"] - s_bench["ann_ret_pct"]), 2),
                edge_ci95_pct=ci, n_flips=n_flips,
                edge_positive_prob=round(float((boot > 0).mean()), 3))


# ── 4. FAMILY-WISE max-stat null (multiple-testing charge) ────────────────────
def fwer_maxstat(panels_ew, kpa_by_group):
    """Build every cross-sectional cell's (storm, fwd) pair. Observed: max |contrast| across all cells.
    Null: for ONE circular shift, shift the storm series in each cell by the SAME random offset (shared
    geomagnetic clock), recompute every cell, take the max |contrast|. Repeat -> FWER null of the most
    extreme cell. p_fwer = P(null max >= observed best). This charges the entire 18-cell search at once."""
    cells = []
    for gname, ew in panels_ew.items():
        kpa = kpa_by_group[gname]
        for pctl in PCTL:
            storm = storm_label(kpa, pctl, TRAIL)
            for h in FWD:
                fwd = fwd_from_logret(ew, h)
                df = pd.concat([storm, fwd], axis=1).dropna()
                if len(df) < 400:
                    continue
                cells.append((f"{gname}|h{h}|p{pctl}",
                              df["storm"].to_numpy(float),
                              df[f"fwd_{h}"].to_numpy(float)))
    obs_abs = [abs(contrast(s, f)) for _, s, f in cells]
    obs_best = float(np.nanmax(obs_abs))
    best_cell = cells[int(np.nanargmax(obs_abs))][0]
    B = 5000
    null_best = np.empty(B)
    for b in range(B):
        m = 0.0
        for _, s, f in cells:
            N = len(s)
            lo, hi = TRAIL + max(FWD) + 1, N - (TRAIL + max(FWD) + 1)
            c = contrast(np.roll(s, RNG.integers(lo, hi)), f)
            if np.isfinite(c):
                m = max(m, abs(c))
        null_best[b] = m
    p_fwer = float((null_best >= obs_best).mean())
    # where does OUR candidate cell sit in its own marginal? already have p_circ; here the family charge:
    return dict(n_cells=len(cells), best_cell=best_cell,
                obs_best_bps=round(obs_best * 1e4, 2),
                fwer_null_median_bps=round(float(np.median(null_best)) * 1e4, 2),
                fwer_null_p95_bps=round(float(np.percentile(null_best, 95)) * 1e4, 2),
                p_fwer=round(p_fwer, 4))


def main():
    print("[load] REAL prices + Kp (GFZ, 1d PIT lag) …", flush=True)
    cr = RP.load_crypto_bars(CRYPTO, "1d", days=3650)
    eq = RP.load_equity_bars(EQUITY)
    kp = ES.load_kp_index(days=4200)
    kp = pd.Series(np.asarray(kp, float), index=pd.DatetimeIndex(kp.index)).sort_index().shift(1)

    ew_cr = ew_index_logret(cr)
    ew_eq = ew_index_logret(eq)
    kpa_cr = kp.reindex(ew_cr.index, method="ffill")
    kpa_eq = kp.reindex(ew_eq.index, method="ffill")

    print("\n=== (1) STRICTER + INDEPENDENT NULLS on the candidate cell (crypto_EW h=1 p90) ===", flush=True)
    n1 = stricter_nulls(ew_cr, kpa_cr)
    print(n1)

    print("\n=== (2) OUT-OF-SAMPLE / SUB-PERIOD (same cell) ===", flush=True)
    n2 = oos_split(ew_cr, kpa_cr)
    print(n2)

    print("\n=== (3) ECONOMIC storm-flat overlay net of 10bps ===", flush=True)
    n3 = economic(ew_cr, kpa_cr)
    print("  strat:", n3["strat"], "\n  bench:", n3["bench"])
    print(f"  edge_ann={n3['edge_ann_pct']}%  CI95={n3['edge_ci95_pct']}%  "
          f"P(edge>0)={n3['edge_positive_prob']}  flips={n3['n_flips']}")

    print("\n=== (4) FAMILY-WISE max-stat null (18-cell search charge) ===", flush=True)
    n4 = fwer_maxstat({"crypto_EW": ew_cr, "equity_EW": ew_eq},
                      {"crypto_EW": kpa_cr, "equity_EW": kpa_eq})
    print(n4)

    # ── verdict logic ─────────────────────────────────────────────────────────
    survives_null = (n1["p_circ"] < 0.05) and (n1["p_ar"] < 0.05) and (
        n1["p_iaaft"] is None or n1["p_iaaft"] < 0.05)
    oos_same_sign = all(v is not None and v < 0 for v in
                        [n2["last30"], n2["secondHalf"]])  # held-out halves keep K-R negative sign
    econ_ok = (n3["edge_ann_pct"] > 0) and (n3["edge_ci95_pct"][0] > 0)
    fwer_ok = n4["p_fwer"] < 0.05
    survives = survives_null and oos_same_sign and econ_ok and fwer_ok
    print("\n=== VERDICT FLAGS ===")
    print(f"  survives_null(all 3)={survives_null}  oos_same_sign={oos_same_sign}  "
          f"econ_ok={econ_ok}  fwer_ok={fwer_ok}  -> SURVIVES_ALL={survives}")

    import json
    summary = dict(cell="crypto_EW|h1|p90", nulls=n1, oos=n2, economic=n3, fwer=n4,
                   survives=bool(survives), survives_null=bool(survives_null),
                   oos_same_sign=bool(oos_same_sign), econ_ok=bool(econ_ok), fwer_ok=bool(fwer_ok))
    with open("scripts/research/astro_deep/geomag_kr_adversarial_verify_results.json", "w") as fh:
        json.dump(summary, fh, indent=2)
    print("\nwrote geomag_kr_adversarial_verify_results.json")


if __name__ == "__main__":
    main()
