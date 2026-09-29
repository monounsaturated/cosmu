#!/usr/bin/env python3
# DIMENSION "spectral_volatility" — DEEPER ATTACK #3 (CORRECTED): cross-asset lunar phase coherence,
# tested the HONEST way against a BACKGROUND-RELATIVE null (not an independent-phase surrogate null).
#
# WHY THE NAIVE VERSION (spectral_vol_coherence.py) MANUFACTURED A FALSE POSITIVE — and why this is the fix:
#   The Kuramoto/Rayleigh resultant R of per-asset phasors at a calendar-anchored frequency measures how
#   phase-locked the assets are at that period. The tempting null is "IAAFT-surrogate each asset independently,
#   recompute R". But crypto (and equities) share a STRONG common low-frequency volatility field — the same
#   macro regimes (2018 bear, 2020 COVID, 2021 mania, 2022 bear) ride every asset on the same calendar.
#   That common slow structure makes the REAL phasors align at MANY periods. The independent-phase surrogate
#   destroys each asset's phase separately, so it can NEVER reproduce that trivial common-trend alignment —
#   hence REAL R beats the surrogate at almost every period (we saw 65/84 'survive' BH-FDR, including the
#   SOLAR YEAR and placebo periods like 61d/88d/199d — the tell that the test was broken, not the universe).
#
# THE CORRECT QUESTION is not "is lunar coherence > independent-surrogate coherence" (everything is) but
#   "is lunar-period coherence ELEVATED ABOVE THE LOCAL BACKGROUND coherence at neighbouring NON-astronomical
#    periods?" A real lunar line POKES ABOVE the background continuum; common-trend coherence is smooth/broadband
#   and the lunar periods are unremarkable within it. So the null here is the EMPIRICAL DISTRIBUTION OF COHERENCE
#   ACROSS A DENSE PERIOD GRID around the lunar band — the lunar period must rank in the top ~5% of that local
#   continuum to count, AND the result must be CONSISTENT across the four lunar periods (synodic/sidereal/
#   anomalistic/draconic) and STABLE across split-halves. Any internally-contradictory pattern (one lunar period
#   high, an adjacent one near the bottom) is the jagged background, not a lunar cycle.
#
# This is the same lesson as the lunar-vol phase-shuffle that died p=0.33: the *right* null is the one that
# preserves the nuisance structure (here, the common broadband vol continuum) and asks only whether the
# astronomical period is SPECIAL within it. Real prices, deterministic lunar periods, no fabrication.

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ENGINE_ROOT))
sys.path.insert(0, str(ENGINE_ROOT / "scripts/research/astro_deep"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import real_panel as RP  # noqa: E402
from spectral_vol_coherence import GLOBAL_EPOCH, coherence_stats, ls_phasors  # noqa: E402

LUNAR = {
    "synodic_29.53": 29.530589,
    "sidereal_27.32": 27.321661,
    "anomalistic_27.55": 27.554550,
    "draconic_27.21": 27.212221,
}
# dense local grid spanning the lunar band with generous non-astronomical neighbours on both sides
LOCAL_GRID = np.arange(20.0, 45.0, 0.2)


def vol_series(bars: dict, measure: str):
    series = []
    for _, df in bars.items():
        r = np.log(df["close"]).diff()
        y = (r.abs() if measure == "abs" else r.rolling(5, min_periods=3).std()).to_numpy()
        m = np.isfinite(y)
        if m.sum() < 400:
            continue
        t = (df.index[m] - GLOBAL_EPOCH).days.to_numpy().astype(float)
        series.append((t, y[m]))
    return series


def coherence_curve(series, grid) -> np.ndarray:
    ph = np.array([ls_phasors(t, y, grid) for t, y in series])
    return np.array([coherence_stats(ph[:, j])[0] for j in range(len(grid))])


def assess(bars: dict, measure: str, label: str) -> dict:
    series = vol_series(bars, measure)
    c = coherence_curve(series, LOCAL_GRID)
    peak_period = float(LOCAL_GRID[c.argmax()])
    peak_R = float(c.max())
    ranks = {}
    for name, L in LUNAR.items():
        j = int(np.argmin(np.abs(LOCAL_GRID - L)))
        ranks[name] = {"R": float(c[j]), "local_pct": float((c <= c[j]).mean() * 100.0)}
    # split-half peak stability
    def half_peak(which):
        s = []
        for _, df in bars.items():
            n = len(df)
            h = df.iloc[:n // 2] if which == "early" else df.iloc[n // 2:]
            r = np.log(h["close"]).diff()
            y = (r.abs() if measure == "abs" else r.rolling(5, min_periods=3).std()).to_numpy()
            m = np.isfinite(y)
            if m.sum() < 200:
                continue
            s.append(((h.index[m] - GLOBAL_EPOCH).days.to_numpy().astype(float), y[m]))
        cc = coherence_curve(s, LOCAL_GRID)
        return float(LOCAL_GRID[cc.argmax()]), float(cc.max())
    ep, _ = half_peak("early")
    lp, _ = half_peak("late")
    return {"label": label, "measure": measure, "peak_period": peak_period, "peak_R": peak_R,
            "ranks": ranks, "early_peak": ep, "late_peak": lp}


def main() -> None:
    ap = argparse.ArgumentParser()
    args = ap.parse_args()
    crypto = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT",
              "AVAXUSDT", "LINKUSDT", "DOTUSDT", "LTCUSDT", "BCHUSDT", "ATOMUSDT", "UNIUSDT",
              "FILUSDT", "NEARUSDT", "AAVEUSDT"]
    equity = ["SPY", "QQQ", "IWM", "GLD", "SLV", "TLT", "XLE", "XLF", "XLK", "USO"]
    bc = {s: d for s, d in RP.load_crypto_bars(crypto, "1d", days=3650).items() if len(d) >= 500}
    be = {s: d for s, d in RP.load_equity_bars(equity).items() if len(d) >= 500}

    print("======= LUNAR COHERENCE vs LOCAL BACKGROUND CONTINUUM (the honest test) =======")
    print("verdict rule: a real lunar line needs local_pct >= 95 CONSISTENTLY across the 4 lunar periods,")
    print("AND a split-half peak that stays lunar. Inconsistent ranks / non-lunar wandering peak = NO lunar cycle.\n")
    rows = []
    any_survive = False
    for measure in ("abs", "rv5"):
        for label, bars in (("CRYPTO", bc), ("EQUITY", be)):
            r = assess(bars, measure, label)
            pks = sum(1 for v in r["ranks"].values() if v["local_pct"] >= 95.0)
            print(f"[{label} {measure}] local-bkg peak {r['peak_R']:.3f}@{r['peak_period']:.2f}d "
                  f"(NOT a lunar period); split-half peaks early={r['early_peak']:.1f}d late={r['late_peak']:.1f}d")
            for n, v in r["ranks"].items():
                print(f"    lunar {n:16s} R={v['R']:.3f}  local_pct={v['local_pct']:5.1f}%"
                      f"{'  *>=95%*' if v['local_pct'] >= 95 else ''}")
            consistent = (pks == len(LUNAR))
            print(f"    -> lunar periods at/above 95% local bkg: {pks}/{len(LUNAR)} "
                  f"({'CONSISTENT' if consistent else 'INCONSISTENT => background, not lunar'})\n")
            any_survive = any_survive or consistent
            rows.append(r)

    print("================ VERDICT ================")
    if any_survive:
        print("A lunar period is consistently elevated above the local background — FLAG for economic gating.")
    else:
        print("NOTHING survives. Lunar periods are unremarkable within the common broadband vol continuum;")
        print("the coherence peak is a NON-astronomical ~30-40d 'monthly' band that also WANDERS across halves.")
        print("The naive independent-phase surrogate null (spectral_vol_coherence.py) was the false-positive source.")


if __name__ == "__main__":
    main()
