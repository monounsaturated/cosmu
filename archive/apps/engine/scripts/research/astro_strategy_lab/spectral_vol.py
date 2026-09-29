#!/usr/bin/env python3
# DIMENSION "spectral_volatility": is there ANY astronomically-periodic structure in crypto/equity VOLATILITY
# (|log-return| and 5-day realized vol) that survives a surrogate null which PRESERVES the vol autocorrelation?
#
# Why this is the right, hard test (and why prior attempts were weak):
#   - Volatility is strongly autocorrelated (vol clustering). A Lomb-Scargle peak at the lunar period is therefore
#     NOT evidence of a lunar cycle by itself — a red-noise / clustered series produces broadband low-freq power
#     and spurious peaks. An i.i.d. fake-date null UNDER-estimates that, so it manufactured a false positive before.
#   - The correct null = IAAFT surrogates: randomize phases but ITERATIVELY restore the exact amplitude distribution,
#     so each surrogate has (a) the SAME power spectrum (=> same autocorrelation, same vol-clustering) and
#     (b) the SAME marginal distribution (=> same heavy tails) as the real vol series — only the deterministic
#     phase relationship to the calendar is destroyed. If real power at the lunar period exceeds the surrogate
#     ensemble, that is a genuine calendar-locked periodicity. If not, the "peak" is just clustering.
#
# Astronomical periods probed (days): synodic lunar 29.53, sidereal lunar 27.32, anomalistic 27.55, draconic 27.21,
#   lunar fortnight 14.77 (spring/neap), Mercury synodic 115.88, Venus synodic 583.92, solar/seasonal 365.25,
#   half-year 182.6, week 7 (control: SHOULD show in crypto? no — 7d trading-week artifact only in equities),
#   and a dense scan 2..400 d for context.
#
# Real prices (RP), deterministic calendar. IAAFT null. BH-FDR across (asset x period x vol-measure).
# "Nothing survives" is the expected and acceptable result.

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
from scipy.signal import lombscargle  # noqa: E402

import real_panel as RP  # noqa: E402

# ── astronomical periods of interest (days) ──────────────────────────────────────────────────────
ASTRO_PERIODS = {
    "lunar_synodic_29.53": 29.530589,
    "lunar_sidereal_27.32": 27.321661,
    "lunar_anomalistic_27.55": 27.554550,
    "lunar_draconic_27.21": 27.212221,
    "lunar_fortnight_14.77": 14.765295,   # spring/neap tide (synodic/2)
    "mercury_synodic_115.9": 115.8775,
    "venus_synodic_584": 583.92,
    "mars_synodic_780": 779.94,
    "solar_year_365": 365.2422,
    "half_year_182.6": 182.6211,
    "week_7": 7.0,                          # control: trading-week artifact (equities), not astronomical
}
# lunar band to scan densely for a local peak
LUNAR_BAND = (26.0, 30.5)


def iaaft_surrogate(x: np.ndarray, rng: np.random.Generator, n_iter: int = 100) -> np.ndarray:
    """Iterative Amplitude Adjusted Fourier Transform surrogate.
    Preserves (to convergence) BOTH the power spectrum and the amplitude distribution of x.
    Destroys deterministic phase / calendar-locking. The correct null for periodicity in
    autocorrelated, heavy-tailed series (vol)."""
    n = len(x)
    x_sorted = np.sort(x)
    amp = np.abs(np.fft.rfft(x))                     # target Fourier amplitudes
    # init: random permutation
    s = rng.permutation(x)
    for _ in range(n_iter):
        # 1) impose the target power spectrum
        S = np.fft.rfft(s)
        phases = np.angle(S)
        s = np.fft.irfft(amp * np.exp(1j * phases), n=n)
        # 2) impose the target amplitude distribution (rank-remap)
        ranks = np.argsort(np.argsort(s))
        s = x_sorted[ranks]
    return s


def ls_power(t: np.ndarray, y: np.ndarray, periods: np.ndarray) -> np.ndarray:
    """Normalized Lomb-Scargle power at the given periods. t in days (can be irregular)."""
    y = y - np.mean(y)
    ang_freqs = 2.0 * np.pi / periods
    pgram = lombscargle(t.astype(float), y.astype(float), ang_freqs, normalize=True)
    return pgram


def realized_measures(df: pd.DataFrame) -> dict[str, pd.Series]:
    """Two vol measures on a calendar index: |log-return| and 5-day realized vol."""
    r = np.log(df["close"]).diff()
    abs_r = r.abs()
    rv5 = r.rolling(5, min_periods=3).std()
    return {"abs_logret": abs_r, "rv5": rv5}


def analyze_symbol(sym: str, df: pd.DataFrame, n_surr: int, rng: np.random.Generator) -> list[dict]:
    """For one asset: LS power at each astro period for each vol measure, vs IAAFT surrogate ensemble."""
    out = []
    measures = realized_measures(df)
    # regular integer-day time axis from the calendar (gaps preserved as missing => we use observed-index t)
    # Lomb-Scargle handles irregular sampling; t = days since first bar at each OBSERVED bar.
    t_all = (df.index - df.index[0]).days.to_numpy().astype(float)
    period_names = list(ASTRO_PERIODS.keys())
    period_vals = np.array([ASTRO_PERIODS[k] for k in period_names])

    for mname, ser in measures.items():
        y = ser.to_numpy()
        mask = np.isfinite(y)
        t = t_all[mask]
        yv = y[mask]
        if len(yv) < 400:
            continue
        real_pow = ls_power(t, yv, period_vals)
        # IAAFT surrogates: built on the (contiguous-in-rank) vol values; LS recomputed on SAME t axis.
        surr_pow = np.empty((n_surr, len(period_vals)))
        for i in range(n_surr):
            s = iaaft_surrogate(yv, rng)
            surr_pow[i] = ls_power(t, s, period_vals)
        # one-sided p: fraction of surrogates with power >= real (add-one smoothing)
        p = (1.0 + (surr_pow >= real_pow[None, :]).sum(axis=0)) / (n_surr + 1.0)
        surr_mean = surr_pow.mean(axis=0)
        surr_p95 = np.percentile(surr_pow, 95, axis=0)
        for j, pn in enumerate(period_names):
            out.append({
                "symbol": sym, "measure": mname, "period": pn,
                "period_days": float(period_vals[j]),
                "real_power": float(real_pow[j]),
                "surr_mean": float(surr_mean[j]),
                "surr_p95": float(surr_p95[j]),
                "excess": float(real_pow[j] - surr_mean[j]),
                "p_one_sided": float(p[j]),
                "n": int(len(yv)),
            })
    return out


def bh_fdr(pvals: np.ndarray, q: float = 0.10) -> np.ndarray:
    """Benjamini-Hochberg: return boolean survive-mask at FDR=q."""
    n = len(pvals)
    order = np.argsort(pvals)
    ranked = pvals[order]
    thresh = q * (np.arange(1, n + 1) / n)
    below = ranked <= thresh
    if not below.any():
        return np.zeros(n, bool)
    kmax = np.max(np.where(below)[0])
    crit = ranked[kmax]
    return pvals <= crit


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--surr", type=int, default=500)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--quick", action="store_true", help="fewer symbols/surrogates for a smoke test")
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)

    crypto = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT",
              "AVAXUSDT", "LINKUSDT", "DOTUSDT", "LTCUSDT", "BCHUSDT", "ATOMUSDT", "UNIUSDT",
              "FILUSDT", "NEARUSDT", "AAVEUSDT"]
    equity = ["SPY", "QQQ", "IWM", "GLD", "SLV", "TLT", "XLE", "XLF", "XLK", "USO"]
    if args.quick:
        crypto, equity, args.surr = crypto[:3], equity[:2], min(args.surr, 80)

    print(f"[load] {len(crypto)} crypto + {len(equity)} equity, {args.surr} IAAFT surrogates", flush=True)
    bars = RP.load_crypto_bars(crypto, "1d", days=3650)
    bars.update(RP.load_equity_bars(equity))
    bars = {s: b for s, b in bars.items() if len(b) >= 500}

    rows = []
    for k, (sym, df) in enumerate(bars.items(), 1):
        rows.extend(analyze_symbol(sym, df, args.surr, rng))
        print(f"  [{k}/{len(bars)}] {sym} done", flush=True)

    res = pd.DataFrame(rows)
    res.to_csv("/tmp/spectral_vol_results.csv", index=False)

    # ── verdict ──────────────────────────────────────────────────────────────────────────────────
    print("\n================ SPECTRAL VOLATILITY vs IAAFT NULL ================")
    print(f"total tests: {len(res)}  (assets x measures x periods)")

    # 7d control sanity check (expect crypto NO, equities maybe weak trading-week)
    ctrl = res[res.period == "week_7"]
    print(f"\n[control] 7-day period  median p (crypto) = {ctrl[ctrl.symbol.str.endswith('USDT')].p_one_sided.median():.3f}"
          f"  (equity) = {ctrl[~ctrl.symbol.str.endswith('USDT')].p_one_sided.median():.3f}")

    # BH-FDR across ALL tests
    surv = bh_fdr(res.p_one_sided.to_numpy(), q=0.10)
    res["fdr_survive"] = surv
    n_surv = int(surv.sum())
    print(f"\n[BH-FDR q=0.10] survivors across all {len(res)} tests: {n_surv}")
    if n_surv:
        print(res[res.fdr_survive].sort_values("p_one_sided")[
            ["symbol", "measure", "period", "real_power", "surr_p95", "excess", "p_one_sided"]].to_string(index=False))

    # Focus: lunar band, pooled across assets — how many beat surrogate p95 nominally?
    print("\n[lunar focus] per astro period: #assets with p<0.05 (nominal) / total, min p, median p")
    for pn in ASTRO_PERIODS:
        sub = res[res.period == pn]
        n_hit = int((sub.p_one_sided < 0.05).sum())
        print(f"  {pn:26s}  hits@0.05={n_hit:3d}/{len(sub):3d}  minp={sub.p_one_sided.min():.4f}  medp={sub.p_one_sided.median():.3f}")

    # Lunar-synodic specifically, per asset (the ONE place a weak effect might hide)
    syn = res[res.period == "lunar_synodic_29.53"].sort_values("p_one_sided")
    print("\n[lunar synodic 29.53d] best 8 assets by p:")
    print(syn.head(8)[["symbol", "measure", "real_power", "surr_p95", "excess", "p_one_sided"]].to_string(index=False))

    print("\nsaved: /tmp/spectral_vol_results.csv")


if __name__ == "__main__":
    main()
