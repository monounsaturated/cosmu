#!/usr/bin/env python3
# DIMENSION "spectral_volatility" — DEEPER ATTACK #3: CROSS-ASSET PHASE COHERENCE at the lunar frequency.
#
# Why this goes BEYOND the two existing attacks (point-power at exact period; max-in-band per asset):
#   Per-asset Lomb-Scargle power can be inflated by red-noise/vol-clustering even after an IAAFT null
#   (a single asset's lone whiff — e.g. BTC synodic |r| nominal p=0.012 — is exactly the "lucky" case).
#   A GENUINE common lunar driver makes an ADDITIONAL, much harder prediction: every asset's volatility
#   must be phase-locked to the SAME absolute calendar phase of the Moon. Independent clustering artifacts
#   produce RANDOM relative phases across assets -> they cancel. A real cycle produces ALIGNED phases ->
#   they add coherently. So the decisive statistic is the cross-asset PHASE COHERENCE (Kuramoto / Rayleigh
#   resultant of the per-asset lunar phasors), measured against a COMMON absolute time origin so phases are
#   comparable across assets with different listing dates.
#
# Statistic:  for each asset a, compute the complex Lomb-Scargle phasor z_a = A_a * exp(i * phi_a) of the
#   vol series at the target frequency, where phi_a is referenced to a FIXED global epoch (2010-01-01).
#   Coherence statistics:
#     (1) R_unit  = | mean_a exp(i*phi_a) |              (pure phase alignment, Rayleigh resultant; amplitude-blind)
#     (2) R_ampw  = | sum_a A_a*exp(i*phi_a) | / sum_a A_a   (amplitude-weighted; lets strong-power assets vote more)
#   Both lie in [0,1]; ~0 = scattered phases (no common cycle), ~1 = perfectly phase-locked.
#
# NULL (the hard part, the lesson from before): IAAFT-surrogate EACH asset INDEPENDENTLY. Each surrogate
#   preserves that asset's own power spectrum (=> vol autocorrelation / clustering) and amplitude distribution
#   (=> heavy tails), and is re-anchored to the SAME real calendar timestamps. Because surrogate phases at the
#   lunar frequency are randomized independently per asset, the surrogate ensemble gives the exact distribution
#   of cross-asset coherence you'd see from red-noise vol with NO common calendar lock. Real coherence > null
#   ensemble => genuine common lunar periodicity. This null cannot be fooled by clustering OR by heavy tails.
#
# Tested for: lunar synodic 29.53, sidereal 27.32, anomalistic 27.55, draconic 27.21, fortnight 14.77,
#   solar 365.25; plus a dense lunar-band MAX-coherence scan (most generous fair test, multiplicity absorbed
#   by the surrogate max). Vol measures: |log-return| and 5-day realized vol. Groups: crypto, equity, ALL.
#   Run separately per group because a lunar driver, if real, need not be common across asset classes.
#
# Economic gate is downstream: even a surviving coherence must then beat ~10bps; but coherence is the
# necessary precondition a single-asset whiff can never satisfy. "Nothing survives" is the expected result.

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
from spectral_vol import iaaft_surrogate  # noqa: E402

# fixed global epoch so phases are comparable across assets with different start dates
GLOBAL_EPOCH = pd.Timestamp("2010-01-01")

ASTRO_PERIODS = {
    "lunar_synodic_29.53": 29.530589,
    "lunar_sidereal_27.32": 27.321661,
    "lunar_anomalistic_27.55": 27.554550,
    "lunar_draconic_27.21": 27.212221,
    "lunar_fortnight_14.77": 14.765295,
    "solar_year_365": 365.2422,
}
LUNAR_BAND = (26.0, 30.5)
N_BAND_GRID = 60
IAAFT_ITERS = 60  # converges to spectrum rel-err ~0.019 (vs 0.013 @100); phase randomization is what matters


def ls_phasors(t: np.ndarray, y: np.ndarray, periods: np.ndarray) -> np.ndarray:
    """Vectorized complex Lomb-Scargle-style phasors of y at MANY `periods`, referenced to t=0 (GLOBAL epoch).

    For each frequency w we fit, by least squares, y(t) ~ a*cos(w t) + b*sin(w t) (the mean of y is removed
    first, which orthogonalizes the intercept to good approximation over a long contiguous span). The 2x2
    normal-equation solve is done in closed form per frequency (no lstsq), so the whole period grid is a few
    vectorized matmuls. t is in DAYS SINCE THE GLOBAL EPOCH => phi is a true calendar phase comparable across
    assets with different listing dates. Returns array of A*exp(i*phi), one per period.

    Closed form for [Scc Scs; Scs Sss] [a;b] = [Syc; Sys]:
        det = Scc*Sss - Scs^2 ;  a = (Sss*Syc - Scs*Sys)/det ;  b = (Scc*Sys - Scs*Syc)/det
    """
    yc = y - y.mean()
    w = (2.0 * np.pi / periods)[:, None]          # (P,1)
    wt = w * t[None, :]                             # (P,N)
    C = np.cos(wt)                                  # (P,N)
    S = np.sin(wt)
    Scc = np.einsum("pn,pn->p", C, C)
    Sss = np.einsum("pn,pn->p", S, S)
    Scs = np.einsum("pn,pn->p", C, S)
    Syc = C @ yc                                    # (P,)
    Sys = S @ yc
    det = Scc * Sss - Scs * Scs
    det = np.where(np.abs(det) < 1e-12, np.nan, det)
    a = (Sss * Syc - Scs * Sys) / det
    b = (Scc * Sys - Scs * Syc) / det
    A = np.hypot(a, b)
    phi = np.arctan2(b, a)
    return A * np.exp(1j * phi)


def ls_phasor(t: np.ndarray, y: np.ndarray, period: float) -> complex:
    """Single-period convenience wrapper (used by validation)."""
    return complex(ls_phasors(t, y, np.array([period]))[0])


def coherence_stats(phasors: np.ndarray) -> tuple[float, float]:
    """From per-asset complex phasors return (R_unit, R_ampw)."""
    amps = np.abs(phasors)
    units = phasors / np.where(amps > 0, amps, 1.0)
    r_unit = np.abs(units.mean())
    r_ampw = np.abs(phasors.sum()) / amps.sum() if amps.sum() > 0 else 0.0
    return float(r_unit), float(r_ampw)


def build_series(bars: dict[str, pd.DataFrame], measure: str):
    """Return list of (t_days_since_epoch, y) per asset for the chosen vol measure."""
    series = []
    names = []
    for sym, df in bars.items():
        r = np.log(df["close"]).diff()
        if measure == "abs_logret":
            ser = r.abs()
        elif measure == "rv5":
            ser = r.rolling(5, min_periods=3).std()
        else:
            raise ValueError(measure)
        y = ser.to_numpy()
        mask = np.isfinite(y)
        if mask.sum() < 400:
            continue
        t = (df.index[mask] - GLOBAL_EPOCH).days.to_numpy().astype(float)
        series.append((t, y[mask]))
        names.append(sym)
    return names, series


def _coh_from_phasors(phasors_2d: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Vectorized coherence over a (n_assets, P) phasor matrix -> (R_unit[P], R_ampw[P])."""
    amps = np.abs(phasors_2d)
    units = phasors_2d / np.where(amps > 0, amps, 1.0)
    r_unit = np.abs(units.mean(axis=0))
    sa = amps.sum(axis=0)
    r_ampw = np.where(sa > 0, np.abs(phasors_2d.sum(axis=0)) / np.where(sa > 0, sa, 1.0), 0.0)
    return r_unit, r_ampw


def run_measure(measure: str, names: list[str], series: list, group_idx: dict[str, list[int]],
                n_surr: int, rng: np.random.Generator) -> list[dict]:
    """Compute cross-asset phase coherence for ALL groups in ONE pass for a vol measure.
    Each asset is surrogated ONCE per draw; group coherences are formed from index subsets (ALL = crypto∪equity),
    so we never regenerate surrogates per group. Named astro periods + dense lunar band, R_unit and R_ampw."""
    period_names = list(ASTRO_PERIODS.keys())
    period_vals = np.array([ASTRO_PERIODS[k] for k in period_names])
    band_grid = np.linspace(LUNAR_BAND[0], LUNAR_BAND[1], N_BAND_GRID)
    all_periods = np.concatenate([period_vals, band_grid])
    n_named = len(period_vals)
    n_assets = len(series)

    # real phasors for every asset (n_assets, P)
    real_all = np.empty((n_assets, len(all_periods)), complex)
    for ai, (t, y) in enumerate(series):
        real_all[ai] = ls_phasors(t, y, all_periods)

    groups = list(group_idx.keys())

    # real coherence per group: named-period (R_unit/ampw) and band-max
    real_named = {}   # (group) -> (n_named,) unit, ampw
    real_bandmax = {}  # (group) -> (unit_max, ampw_max, peak_unit, peak_ampw)
    for g, idx in group_idx.items():
        sub = real_all[idx]
        ru, ra = _coh_from_phasors(sub)
        real_named[g] = (ru[:n_named], ra[:n_named])
        bu, ba = ru[n_named:], ra[n_named:]
        real_bandmax[g] = (bu.max(), ba.max(), float(band_grid[bu.argmax()]), float(band_grid[ba.argmax()]))

    # surrogate ensemble — surrogate every asset ONCE per draw, slice subsets for each group
    surr_named = {g: {"unit": np.empty((n_surr, n_named)), "ampw": np.empty((n_surr, n_named))} for g in groups}
    surr_bandmax = {g: {"unit": np.empty(n_surr), "ampw": np.empty(n_surr)} for g in groups}
    for d in range(n_surr):
        surr_all = np.empty((n_assets, len(all_periods)), complex)
        for ai, (t, y) in enumerate(series):
            s = iaaft_surrogate(y, rng, n_iter=IAAFT_ITERS)
            surr_all[ai] = ls_phasors(t, s, all_periods)
        for g, idx in group_idx.items():
            ru, ra = _coh_from_phasors(surr_all[idx])
            surr_named[g]["unit"][d] = ru[:n_named]
            surr_named[g]["ampw"][d] = ra[:n_named]
            surr_bandmax[g]["unit"][d] = ru[n_named:].max()
            surr_bandmax[g]["ampw"][d] = ra[n_named:].max()

    def p_of(real_val, surr_arr):
        return (1.0 + (surr_arr >= real_val).sum()) / (n_surr + 1.0)

    out = []
    for g in groups:
        na = len(group_idx[g])
        ru_named, ra_named = real_named[g]
        for j, pn in enumerate(period_names):
            for stat, real_v, surr_v in (("R_unit", ru_named[j], surr_named[g]["unit"][:, j]),
                                          ("R_ampw", ra_named[j], surr_named[g]["ampw"][:, j])):
                out.append({"group": g, "measure": measure, "period": pn, "stat": stat, "n_assets": na,
                            "real": float(real_v), "surr_mean": float(surr_v.mean()),
                            "surr_p95": float(np.percentile(surr_v, 95)), "p": p_of(real_v, surr_v)})
        bu_max, ba_max, pk_u, pk_a = real_bandmax[g]
        out.append({"group": g, "measure": measure, "period": f"band_max@{pk_u:.2f}", "stat": "R_unit", "n_assets": na,
                    "real": float(bu_max), "surr_mean": float(surr_bandmax[g]["unit"].mean()),
                    "surr_p95": float(np.percentile(surr_bandmax[g]["unit"], 95)),
                    "p": p_of(bu_max, surr_bandmax[g]["unit"])})
        out.append({"group": g, "measure": measure, "period": f"band_max@{pk_a:.2f}", "stat": "R_ampw", "n_assets": na,
                    "real": float(ba_max), "surr_mean": float(surr_bandmax[g]["ampw"].mean()),
                    "surr_p95": float(np.percentile(surr_bandmax[g]["ampw"], 95)),
                    "p": p_of(ba_max, surr_bandmax[g]["ampw"])})
    return out


def bh_fdr_survivors(pvals: np.ndarray, q: float = 0.10):
    n = len(pvals)
    order = np.argsort(pvals)
    ranked = pvals[order]
    below = ranked <= q * (np.arange(1, n + 1) / n)
    if not below.any():
        return np.zeros(n, bool), None
    kmax = np.max(np.where(below)[0])
    crit = ranked[kmax]
    return pvals <= crit, float(crit)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--surr", type=int, default=500)
    ap.add_argument("--seed", type=int, default=23)
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)

    crypto = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT",
              "AVAXUSDT", "LINKUSDT", "DOTUSDT", "LTCUSDT", "BCHUSDT", "ATOMUSDT", "UNIUSDT",
              "FILUSDT", "NEARUSDT", "AAVEUSDT"]
    equity = ["SPY", "QQQ", "IWM", "GLD", "SLV", "TLT", "XLE", "XLF", "XLK", "USO"]
    if args.quick:
        crypto, equity, args.surr = crypto[:8], equity[:6], min(args.surr, 120)

    print(f"[load] {len(crypto)} crypto + {len(equity)} equity, {args.surr} IAAFT surrogates/asset", flush=True)
    cbars = RP.load_crypto_bars(crypto, "1d", days=3650)
    ebars = RP.load_equity_bars(equity)
    cbars = {s: b for s, b in cbars.items() if len(b) >= 500}
    ebars = {s: b for s, b in ebars.items() if len(b) >= 500}
    allbars = {**cbars, **ebars}
    crypto_set = set(cbars)

    rows = []
    for measure in ("abs_logret", "rv5"):
        names, series = build_series(allbars, measure)  # union of assets, surrogated ONCE per draw
        ci = [i for i, s in enumerate(names) if s in crypto_set]
        ei = [i for i, s in enumerate(names) if s not in crypto_set]
        group_idx = {"crypto": ci, "equity": ei, "ALL": list(range(len(names)))}
        group_idx = {g: idx for g, idx in group_idx.items() if len(idx) >= 4}
        print(f"[run] measure={measure:10s} assets={len(names)} "
              f"(crypto={len(ci)} equity={len(ei)}); {args.surr} surrogates", flush=True)
        rows.extend(run_measure(measure, names, series, group_idx, args.surr, rng))

    res = pd.DataFrame(rows)
    res.to_csv("/tmp/spectral_vol_coherence.csv", index=False)

    print("\n================ CROSS-ASSET LUNAR PHASE COHERENCE vs IAAFT NULL ================")
    print(f"total coherence tests: {len(res)}")
    # show full table sorted by p
    cols = ["group", "measure", "period", "stat", "n_assets", "real", "surr_mean", "surr_p95", "p"]
    show = res.sort_values("p")[cols].copy()
    for c in ("real", "surr_mean", "surr_p95"):
        show[c] = show[c].map(lambda v: f"{v:.4f}")
    show["p"] = show["p"].map(lambda v: f"{v:.4f}")
    print(show.to_string(index=False))

    surv, crit = bh_fdr_survivors(res.p.to_numpy(), q=0.10)
    res["fdr_survive"] = surv
    print(f"\n[BH-FDR q=0.10] survivors: {int(surv.sum())}/{len(res)}  (crit p = {crit})")
    if surv.any():
        print(res[res.fdr_survive].sort_values("p")[cols].to_string(index=False))

    # lunar-synodic focus across groups (the prime suspect)
    syn = res[res.period == "lunar_synodic_29.53"]
    print("\n[lunar synodic 29.53] coherence by group/measure/stat:")
    print(syn.sort_values("p")[cols].to_string(index=False))

    print("\nsaved: /tmp/spectral_vol_coherence.csv")


if __name__ == "__main__":
    main()
