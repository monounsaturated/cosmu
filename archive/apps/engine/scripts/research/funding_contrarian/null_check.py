# intent: the CORRECT null for funding-contrarian — does the SIGNAL's timing add anything, or is the positive
# OOS mean just the unconditional drift of holding longs in the universe? We circular-SHIFT the position series
# relative to realised returns (block-preserving), which destroys true timing while keeping the same number of
# long/short/flat days and the same return autocorrelation. p = P(shifted-Sharpe >= observed). If the edge is
# real timing, observed sits in the right tail. We run it PER selected config on the OOS window AND full sample.
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import study as S  # noqa: E402


def shift_null(panel, k, mode, dates_mask, n=3000, seed=11):
    """Circular-shift each symbol's POSITION by a random lag, recompute pooled net return, get Sharpe null."""
    rng = np.random.default_rng(seed)
    # precompute per-symbol pos + fwd ret aligned
    syms = []
    for s, df in panel.items():
        pos = S.position(df["z"], k, mode)
        syms.append((pos.values, df["ret_fwd"].values, df.index))
    # observed pooled
    def pooled(shift_lags):
        cols = []
        idxs = []
        for (pos, ret, idx), lag in zip(syms, shift_lags):
            p = np.roll(pos, lag)
            turn = np.abs(np.diff(np.concatenate([[0.0], p])))
            net = p * ret - turn * (S.RT_COST / 2.0)
            cols.append(pd.Series(net, index=idx))
        mat = pd.concat(cols, axis=1)
        pr = mat.mean(axis=1, skipna=True)
        return pr[dates_mask(pr.index)]
    obs = S.sharpe(pooled([0] * len(syms)))
    null = np.empty(n)
    lens = [len(p) for p, _, _ in syms]
    for b in range(n):
        lags = [int(rng.integers(20, L - 20)) for L in lens]
        null[b] = S.sharpe(pooled(lags))
    p = float((null >= obs).mean())
    return obs, p, null.mean(), null.std()


def main():
    panel = S.build_panel()
    all_dates = pd.DatetimeIndex(sorted(set().union(*[df.index for df in panel.values()])))
    split = int(len(all_dates) * (1 - S.OOS_FRAC))
    oos_start = all_dates[split]
    train_end = all_dates[split - 1]

    print("Signal-timing (position circular-shift) null — the HONEST test of whether the contrarian rule adds edge")
    for mode in S.MODES:
        for k in S.KS:
            obs_oos, p_oos, mu, sd = shift_null(panel, k, mode, lambda ix: ix >= oos_start)
            obs_full, p_full, _, _ = shift_null(panel, k, mode, lambda ix: np.ones(len(ix), bool), seed=23)
            flag = "***" if (p_oos < 0.05 and obs_oos > 0) else ""
            print(f"  mode={mode:11s} k={k:.1f} | OOS SR={obs_oos:6.3f} p={p_oos:.3f} "
                  f"(null {mu:+.3f}±{sd:.3f}) | FULL SR={obs_full:6.3f} p={p_full:.3f} {flag}")


if __name__ == "__main__":
    main()
