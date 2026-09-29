"""WAVE-1 SPECTRAL ATTACK on the astrology->markets question.

Lomb-Scargle periodogram of LOG-RETURNS (and |ret|, ret^2 as the vol channel) per asset + a pooled
stack. Test for EXCESS POWER at the EXACT astronomical periods vs a PROPER colored-noise null:
  - AR(1) surrogates (preserve lag-1 autocorrelation)
  - phase-randomized FFT surrogates (preserve the FULL power spectrum / autocorrelation exactly)
Both preserve the return/vol autocorrelation so a peak only "survives" if it is ABOVE the colored
background, not merely above white noise. Bonferroni over the astronomical frequencies tested.

No astropy: use scipy.signal.lombscargle (Press & Rybicki normalization), which accepts uneven samples
(equities have market-closure gaps -> genuinely uneven; crypto is daily-continuous).
"""
from __future__ import annotations

import sys
import warnings

import numpy as np
import pandas as pd
from scipy.signal import lombscargle

warnings.filterwarnings("ignore")
sys.path.insert(0, "scripts/research/astro_deep")
import real_panel as RP  # noqa: E402

RNG = np.random.default_rng(20260615)

# Exact astronomical periods (days). Synodic/sidereal/draconic/anomalistic month + planet synodics.
ASTRO_PERIODS = {
    "synodic_month": 29.530589,
    "sidereal_month": 27.321661,
    "draconic_month": 27.212221,
    "anomalistic_month": 27.554550,
    "tropical_month": 27.321582,
    "lunar_fortnight": 14.765295,  # half-synodic (spring/neap-tide analogue)
    "mercury_synodic": 115.8775,
    "venus_synodic": 583.92,
    "mars_synodic": 779.94,
    # multi-year (only meaningful where history >= a couple cycles; flagged at report time):
    "jupiter_synodic": 398.88,
    "saturn_synodic": 378.09,
    "lunar_year": 354.367,  # 12 synodic months (calendar-ish)
    "solar_year": 365.2422,  # seasonal control (NON-astrological; expected real in some assets)
}


def log_returns(close: pd.Series) -> pd.Series:
    return np.log(close).diff().dropna()


def _ls_power(t_days: np.ndarray, y: np.ndarray, ang_freqs: np.ndarray) -> np.ndarray:
    """Press-Rybicki normalized LS power at the given angular frequencies. y is mean-subtracted."""
    yc = y - y.mean()
    var = yc.var()
    if var <= 0:
        return np.zeros_like(ang_freqs)
    # scipy lombscargle wants precenter handled by us; normalize by variance for cross-series comparability
    p = lombscargle(t_days.astype(float), yc.astype(float), ang_freqs, precenter=False, normalize=False)
    return p / var


def _ar1_surrogate(y: np.ndarray) -> np.ndarray:
    """AR(1) surrogate preserving lag-1 autocorr and variance; gaussian innovations."""
    n = len(y)
    yc = y - y.mean()
    if n < 3:
        return yc.copy()
    phi = float(np.corrcoef(yc[:-1], yc[1:])[0, 1])
    phi = np.clip(phi, -0.98, 0.98)
    if not np.isfinite(phi):
        phi = 0.0
    sig = np.sqrt(max(yc.var() * (1 - phi**2), 1e-18))
    out = np.empty(n)
    out[0] = RNG.normal(0, np.sqrt(max(yc.var(), 1e-18)))
    eps = RNG.normal(0, sig, n)
    for i in range(1, n):
        out[i] = phi * out[i - 1] + eps[i]
    return out


def _phase_surrogate(y: np.ndarray) -> np.ndarray:
    """Phase-randomized FFT surrogate: preserves the amplitude spectrum (=> autocorrelation) exactly,
    randomizes phases. The gold-standard colored-noise null for 'is this spectral peak real?'."""
    yc = y - y.mean()
    n = len(yc)
    F = np.fft.rfft(yc)
    mag = np.abs(F)
    # random phases, keep DC real, conjugate-symmetry handled by irfft
    ph = RNG.uniform(0, 2 * np.pi, len(F))
    ph[0] = 0.0
    if n % 2 == 0:
        ph[-1] = 0.0  # Nyquist real
    Fs = mag * np.exp(1j * ph)
    return np.fft.irfft(Fs, n=n)


def analyze_series(
    t_days: np.ndarray,
    y: np.ndarray,
    periods: dict[str, float],
    n_surr: int = 1000,
    surr: str = "phase",
) -> dict[str, dict]:
    """Return per-period {obs_power, surr_p95, surr_p99, p_one_sided}. p = frac surrogates >= obs."""
    ang = np.atleast_1d(2 * np.pi / np.array(list(periods.values()), dtype=float))
    obs = np.atleast_1d(_ls_power(t_days, y, ang))
    surr_fn = _phase_surrogate if surr == "phase" else _ar1_surrogate
    # surrogate keeps the SAME sample times t_days (preserves the uneven-sampling window function)
    surr_powers = np.empty((n_surr, len(ang)))
    for k in range(n_surr):
        ys = surr_fn(y)
        surr_powers[k] = np.atleast_1d(_ls_power(t_days, ys, ang))
    out = {}
    for i, name in enumerate(periods):
        col = surr_powers[:, i]
        p = (np.sum(col >= obs[i]) + 1) / (n_surr + 1)  # +1 = unbiased one-sided p
        out[name] = {
            "period_d": float(list(periods.values())[i]),
            "obs_power": float(obs[i]),
            "surr_p95": float(np.percentile(col, 95)),
            "surr_p99": float(np.percentile(col, 99)),
            "p_one_sided": float(p),
        }
    return out


def run(channel: str = "ret", n_surr: int = 1000, surr: str = "phase"):
    crypto = [
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "LTCUSDT", "ADAUSDT",
        "DOGEUSDT", "LINKUSDT", "BCHUSDT", "ATOMUSDT",
    ]
    equity = ["SPY", "QQQ", "IWM", "GLD", "SLV", "TLT", "XLE", "XLF", "USO"]
    cb = RP.load_crypto_bars(crypto, "1d", days=3650)
    eb = RP.load_equity_bars(equity, limit=4000)
    bars = {**cb, **eb}

    periods = ASTRO_PERIODS
    nfreq = len(periods)
    bonf = 0.05 / nfreq  # Bonferroni threshold

    print(f"# channel={channel} surrogate={surr} n_surr={n_surr} | Bonferroni alpha={bonf:.5f} over {nfreq} freqs")
    print(f"{'ASSET':10s} {'PERIOD':18s} {'days':>8s} {'obs/p95':>8s} {'p':>7s} {'flag'}")

    pooled_t, pooled_y = [], []
    survivors = []
    per_asset_results = {}
    for sym, df in bars.items():
        if len(df) < 400:
            continue
        r = log_returns(df["close"])
        # epoch days from first timestamp (handles equity intraday-stamp -> use date)
        t = (r.index.view("int64") / 86_400e9)
        t = t - t[0]
        if channel == "ret":
            y = r.values
        elif channel == "absret":
            y = np.abs(r.values)
        elif channel == "sqret":
            y = (r.values) ** 2
        else:
            raise ValueError(channel)
        res = analyze_series(t, y, periods, n_surr=n_surr, surr=surr)
        per_asset_results[sym] = res
        # pool standardized series on a common daily grid for the stack
        pooled_t.append(t)
        pooled_y.append((y - np.mean(y)) / (np.std(y) + 1e-18))
        for name, d in res.items():
            ratio = d["obs_power"] / (d["surr_p95"] + 1e-18)
            sig = ""
            if d["p_one_sided"] < bonf:
                sig = "** BONF"
                survivors.append((sym, name, d))
            elif d["p_one_sided"] < 0.05:
                sig = "* nom"
            if sig:
                print(f"{sym:10s} {name:18s} {d['period_d']:8.2f} {ratio:8.2f} {d['p_one_sided']:7.4f} {sig}")

    # pooled stack: concatenate all standardized series with their own time axes (a big uneven sample).
    Tp = np.concatenate(pooled_t)
    Yp = np.concatenate(pooled_y)
    order = np.argsort(Tp)
    Tp, Yp = Tp[order], Yp[order]
    pooled = analyze_series(Tp, Yp, periods, n_surr=n_surr, surr=surr)
    print("\n# POOLED STACK (all assets, standardized)")
    for name, d in pooled.items():
        ratio = d["obs_power"] / (d["surr_p95"] + 1e-18)
        sig = "** BONF" if d["p_one_sided"] < bonf else ("* nom" if d["p_one_sided"] < 0.05 else "")
        print(f"{'POOLED':10s} {name:18s} {d['period_d']:8.2f} {ratio:8.2f} {d['p_one_sided']:7.4f} {sig}")
        if d["p_one_sided"] < bonf:
            survivors.append(("POOLED", name, d))

    print(f"\n# SURVIVORS (Bonferroni): {len(survivors)}")
    n_assets = len([s for s, df in bars.items() if len(df) >= 400])
    n_tests = (n_assets + 1) * nfreq  # +1 pooled
    print(f"# total tests this channel = {n_tests} ; expected false BONF at 0.05/{nfreq} per asset ~ {n_tests*bonf:.2f}")
    return survivors, per_asset_results, pooled


if __name__ == "__main__":
    ch = sys.argv[1] if len(sys.argv) > 1 else "ret"
    sr = sys.argv[2] if len(sys.argv) > 2 else "phase"
    ns = int(sys.argv[3]) if len(sys.argv) > 3 else 1000
    run(channel=ch, n_surr=ns, surr=sr)
