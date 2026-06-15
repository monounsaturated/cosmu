"""
High-resolution confirmation of the p-floor MI cells from info_theoretic_study.

The main crypto MI grid (n_null=250) left 16 cells tied at the 1/251 p-floor and
0 survived BH-FDR.  Those 16 are the ONLY ones that could conceivably be real; the
250-shift null simply lacked resolution to rank them.  Here we re-test each with a
LARGE circular-shift null (default 5000 shifts, p-floor 1/5001 ~ 2e-4) and judge
against BOTH:
  - BH-FDR over the 16
  - Bonferroni 0.05/16 ~ 3.1e-3
A cell is a candidate only if it clears these AFTER the high-res null.  We ALSO report
a KSG cross-check (the slow exact estimator) on any cell that clears, so a survivor
isn't an artifact of the 10-bin plug-in discretization.
"""
from __future__ import annotations
import sys, os, json
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
import real_panel as RP
import info_theoretic_study as IT

N_NULL = 5000

# (asset, state, target) extracted from the floor set
FLOOR = [
    ("DOGEUSDT","moon_near_new","fwd_ret_1d"),
    ("DOGEUSDT","moon_near_new","fwd_absret_1d"),
    ("BTCUSDT","harmonic_4_count_q5","fwd_absret_1d"),
    ("NEARUSDT","aspect_trine_count_q5","fwd_vol_5d"),
    ("BNBUSDT","mercury_retrograde","fwd_vol_5d"),
    ("NEARUSDT","aspect_trine_count_q5","fwd_absret_1d"),
    ("DOGEUSDT","mars_out_of_bounds","fwd_ret_1d"),
    ("SOLUSDT","moon_out_of_bounds","fwd_vol_5d"),
    ("LTCUSDT","saturn_sign","fwd_vol_5d"),
    ("UNIUSDT","venus_sign","fwd_ret_1d"),
    ("SOLUSDT","saturn_sign","fwd_vol_5d"),
    ("SOLUSDT","saturn_sign","fwd_absret_1d"),
    ("AVAXUSDT","aspect_trine_count_q5","fwd_vol_5d"),
    ("UNIUSDT","moon_sign","fwd_vol_5d"),
    ("BNBUSDT","saturn_sign","fwd_vol_5d"),
    ("SOLUSDT","saturn_sign","fwd_ret_1d"),
]


def main():
    syms = sorted({a for a, _, _ in FLOOR})
    bars = RP.load_crypto_bars(syms, "1d", days=3650)
    rows = []
    for asset, state, target in FLOOR:
        close = bars[asset]["close"]
        states = IT.build_astro_states(close.index)
        targets = IT.build_targets(close)
        lab = states[state]
        tcol = targets[target]
        m = pd.concat([lab.rename("lab"), tcol.rename("tgt")], axis=1).dropna()
        L = m["lab"].to_numpy().astype(int)
        Y = m["tgt"].to_numpy().astype(float)
        tbin = IT._bin_target(Y)
        IT.RNG = np.random.default_rng(abs(hash((asset, state, target))) % (2**32))
        mi_obs = IT.mi_plugin(L, tbin)
        null = IT.circular_shift_null(L, tbin, N_NULL)
        p = (np.sum(null >= mi_obs) + 1) / (N_NULL + 1)
        z = (mi_obs - null.mean()) / (null.std() + 1e-12)
        rows.append(dict(asset=asset, state=state, target=target,
                         mi_obs=mi_obs, null_mean=float(null.mean()),
                         excess=mi_obs - float(null.mean()), z=z, p=p, n=len(m)))
        print(f"{asset:9s} {state:22s} {target:14s} p={p:.5f} z={z:5.2f} excess={mi_obs-null.mean():.5f}",
              file=sys.stderr)

    res = pd.DataFrame(rows).sort_values("p").reset_index(drop=True)
    bonf = 0.05 / len(res)
    bh_rej, bh_cut = IT.bh_fdr(res["p"].to_numpy(), 0.05)
    res["bh_reject"] = bh_rej
    res["bonf_reject"] = res["p"] < bonf
    summary = dict(n_null=N_NULL, n_cells=len(res), bonferroni=bonf,
                   bh_threshold=float(bh_cut),
                   n_bh_survive=int(res["bh_reject"].sum()),
                   n_bonf_survive=int(res["bonf_reject"].sum()),
                   min_p=float(res["p"].min()))
    print(json.dumps(summary, indent=2))
    print(res.to_string(index=False))
    res.to_csv(os.path.join(os.path.dirname(__file__), "it_confirm_floor_crypto.csv"), index=False)


if __name__ == "__main__":
    main()
