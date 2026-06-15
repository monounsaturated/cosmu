#!/usr/bin/env python3
# SECOND ATTACK for the spectral-volatility dimension: a DENSE-BAND peak scan.
# The point-test (spectral_vol.py) only checks power at the EXACT lunar frequency. A real-but-detuned lunar
# effect, or one slightly shifted by the discrete daily grid, could peak a fraction of a day off and be missed.
# Here we test the strongest statistic: the MAX Lomb-Scargle power anywhere in the lunar band [26, 30.5] d,
# vs the same MAX-in-band statistic from IAAFT surrogates. This is the band's "is there ANY periodicity here"
# test and is the most generous-to-the-hypothesis fair test (it gives the effect its best shot while still
# controlling for the multiplicity of looking across the band, because the surrogate max-stat absorbs it).
#
# Also pools |log-return| ACROSS assets at the bar level (a true common lunar driver should add coherently),
# and reports the band-localized peak period if one beats the null.

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
from spectral_vol import iaaft_surrogate  # noqa: E402

LUNAR_BAND = (26.0, 30.5)
N_GRID = 120  # period resolution within the band


def band_periods() -> np.ndarray:
    return np.linspace(LUNAR_BAND[0], LUNAR_BAND[1], N_GRID)


def ls_band(t: np.ndarray, y: np.ndarray, periods: np.ndarray) -> np.ndarray:
    y = y - np.mean(y)
    return lombscargle(t.astype(float), y.astype(float), 2 * np.pi / periods, normalize=True)


def max_in_band_test(t: np.ndarray, y: np.ndarray, n_surr: int, rng) -> dict:
    periods = band_periods()
    real = ls_band(t, y, periods)
    real_max = real.max()
    real_peak_period = float(periods[real.argmax()])
    surr_max = np.empty(n_surr)
    for i in range(n_surr):
        s = iaaft_surrogate(y, rng)
        surr_max[i] = ls_band(t, s, periods).max()
    p = (1.0 + (surr_max >= real_max).sum()) / (n_surr + 1.0)
    return {"real_max_power": float(real_max), "peak_period": real_peak_period,
            "surr_max_p95": float(np.percentile(surr_max, 95)), "p_one_sided": float(p)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--surr", type=int, default=600)
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)

    crypto = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT",
              "AVAXUSDT", "LINKUSDT", "DOTUSDT", "LTCUSDT", "BCHUSDT", "ATOMUSDT", "UNIUSDT",
              "FILUSDT", "NEARUSDT", "AAVEUSDT"]
    equity = ["SPY", "QQQ", "IWM", "GLD", "SLV", "TLT", "XLE", "XLF", "XLK", "USO"]
    print(f"[load] {len(crypto)} crypto + {len(equity)} equity; band {LUNAR_BAND} d, {args.surr} surr", flush=True)
    bars = RP.load_crypto_bars(crypto, "1d", days=3650)
    bars.update(RP.load_equity_bars(equity))
    bars = {s: b for s, b in bars.items() if len(b) >= 500}

    rows = []
    for k, (sym, df) in enumerate(bars.items(), 1):
        r = np.log(df["close"]).diff()
        y = r.abs().to_numpy()
        t = (df.index - df.index[0]).days.to_numpy().astype(float)
        mask = np.isfinite(y)
        res = max_in_band_test(t[mask], y[mask], args.surr, rng)
        res.update({"symbol": sym, "measure": "abs_logret"})
        rows.append(res)
        print(f"  [{k}/{len(bars)}] {sym}  p={res['p_one_sided']:.3f}  peak={res['peak_period']:.2f}d", flush=True)

    res = pd.DataFrame(rows)
    res.to_csv("/tmp/spectral_band_results.csv", index=False)
    print("\n========= MAX-IN-LUNAR-BAND vs IAAFT (per asset) =========")
    print(res.sort_values("p_one_sided")[
        ["symbol", "real_max_power", "surr_max_p95", "peak_period", "p_one_sided"]].to_string(index=False))
    n_hit = int((res.p_one_sided < 0.05).sum())
    print(f"\n#assets with band-peak p<0.05 (nominal): {n_hit}/{len(res)}  (expected ~{0.05*len(res):.1f} by chance)")
    # are the peak periods CONSISTENT near a true lunar period? (real effect => clustered; artifact => scattered)
    print(f"peak-period spread: mean={res.peak_period.mean():.2f} std={res.peak_period.std():.2f} "
          f"(real lunar would cluster ~27-29.5; wide scatter = no common cycle)")
    print("saved: /tmp/spectral_band_results.csv")


if __name__ == "__main__":
    main()
