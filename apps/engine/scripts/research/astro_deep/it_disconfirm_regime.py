"""
DISCONFIRMER: is the surviving astro->vol MI just a multi-year REGIME confound?

The high-res floor confirmation left 10 Bonferroni survivors, but 5 are `saturn_sign`
(changes sign every ~2.5y -> an EPOCH label) and the rest are slowly-varying states,
all coupling to VOLATILITY targets.  Crypto vol has huge multi-year regimes, so a slow
astro label can score high MI purely by co-trending, and a circular-shift null is
under-powered when the label has only ~4 effective blocks in the sample.

The decisive test: remove the slow regime from the TARGET and see if the MI survives.
  raw target          -> may carry regime confound
  REGIME-RESIDUAL     -> target standardized within a trailing 126-day window
                         (z = (x - roll_median)/roll_IQR), strictly past-only, NO
                         look-ahead.  This strips the multi-year vol regime, leaving
                         only higher-frequency structure that a genuine astro effect
                         would still inhabit.

If excess MI and p collapse on the regime-residual target, the survivor was a regime
proxy (DISCONFIRMED).  If it persists, it is a real higher-frequency coupling worth
escalating.  Same circular-shift null (5000) on the residual target.
"""
from __future__ import annotations
import sys, os, json
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
import real_panel as RP
import info_theoretic_study as IT

N_NULL = 5000
ROLL = 126   # trailing window for regime de-meaning (past-only)

# the 10 Bonferroni survivors from it_confirm_floor
SURV = [
    ("BTCUSDT","harmonic_4_count_q5","fwd_absret_1d"),
    ("LTCUSDT","saturn_sign","fwd_vol_5d"),
    ("SOLUSDT","saturn_sign","fwd_vol_5d"),
    ("SOLUSDT","saturn_sign","fwd_absret_1d"),
    ("SOLUSDT","saturn_sign","fwd_ret_1d"),
    ("NEARUSDT","aspect_trine_count_q5","fwd_vol_5d"),
    ("BNBUSDT","saturn_sign","fwd_vol_5d"),
    ("DOGEUSDT","moon_near_new","fwd_ret_1d"),
    ("DOGEUSDT","moon_near_new","fwd_absret_1d"),
    ("UNIUSDT","venus_sign","fwd_ret_1d"),
]


def regime_residual(x: pd.Series, win: int = ROLL) -> pd.Series:
    """Strip slow regime: subtract trailing median, scale by trailing IQR. Past-only."""
    med = x.shift(1).rolling(win, min_periods=win // 2).median()
    q75 = x.shift(1).rolling(win, min_periods=win // 2).quantile(0.75)
    q25 = x.shift(1).rolling(win, min_periods=win // 2).quantile(0.25)
    iqr = (q75 - q25).replace(0, np.nan)
    return (x - med) / iqr


def eval_cell(close, state, target, residual: bool):
    states = IT.build_astro_states(close.index)
    targets = IT.build_targets(close)
    lab = states[state]
    tser = targets[target]
    if residual:
        tser = regime_residual(tser)
    m = pd.concat([lab.rename("lab"), tser.rename("tgt")], axis=1).dropna()
    L = m["lab"].to_numpy().astype(int)
    Y = m["tgt"].to_numpy().astype(float)
    if len(m) < 400 or len(np.unique(L)) < 2:
        return None
    tbin = IT._bin_target(Y)
    IT.RNG = np.random.default_rng(abs(hash((state, target, residual))) % (2**32))
    mi = IT.mi_plugin(L, tbin)
    null = IT.circular_shift_null(L, tbin, N_NULL)
    p = (np.sum(null >= mi) + 1) / (N_NULL + 1)
    z = (mi - null.mean()) / (null.std() + 1e-12)
    return dict(mi=mi, null_mean=float(null.mean()), excess=mi - float(null.mean()),
                z=z, p=p, n=len(m))


def main():
    syms = sorted({a for a, _, _ in SURV})
    bars = RP.load_crypto_bars(syms, "1d", days=3650)
    rows = []
    for asset, state, target in SURV:
        close = bars[asset]["close"]
        raw = eval_cell(close, state, target, residual=False)
        res = eval_cell(close, state, target, residual=True)
        row = dict(asset=asset, state=state, target=target,
                   raw_excess=raw["excess"], raw_p=raw["p"], raw_z=raw["z"],
                   resid_excess=res["excess"] if res else np.nan,
                   resid_p=res["p"] if res else np.nan,
                   resid_z=res["z"] if res else np.nan,
                   excess_kept=(res["excess"] / raw["excess"]) if (res and raw["excess"] > 0) else np.nan)
        rows.append(row)
        print(f"{asset:9s} {state:22s} {target:14s} | raw p={raw['p']:.4f} ex={raw['excess']:.4f} "
              f"-> RESID p={row['resid_p']:.4f} ex={row['resid_excess']:.4f} kept={row['excess_kept']:.2f}",
              file=sys.stderr)
    res = pd.DataFrame(rows)
    bonf = 0.05 / len(res)
    res["resid_survives_bonf"] = res["resid_p"] < bonf
    summary = dict(n_null=N_NULL, roll_window=ROLL, bonferroni=bonf,
                   n_resid_survive=int(res["resid_survives_bonf"].sum()),
                   n_total=len(res))
    print(json.dumps(summary, indent=2))
    print(res.to_string(index=False))
    res.to_csv(os.path.join(os.path.dirname(__file__), "it_disconfirm_regime_crypto.csv"), index=False)


if __name__ == "__main__":
    main()
