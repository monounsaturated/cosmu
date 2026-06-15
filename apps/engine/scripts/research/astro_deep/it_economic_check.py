"""
ECONOMIC disconfirmer for the info-theoretic survivors.

MI > null says "dependence exists"; it does NOT say the dependence is a MONOTONE,
DIRECTIONAL, FEE-SURVIVABLE signal.  This converts each surviving (state,target) into
the actual tradeable statistic and asks: net of ~10bps round-trip, is there money?

For each survivor we:
  1. group the forward target by the astro state,
  2. report the per-state mean forward return (directional) and mean |return| (vol),
  3. for the BEST long/short rule implied by the state, compute the net daily edge after
     a 10bps round-trip cost charged on every state TRANSITION (entries/exits only),
  4. compare the realized rule PnL to a circular-shift null of the SAME rule (so the
     turnover/exposure is held fixed) — one-sided p on net Sharpe.

A survivor is economically real only if the net-of-fees edge beats its own shifted null.
Pure-vol survivors (saturn_sign etc.) have no directional rule -> reported as
"vol-timing only, not directly tradeable spot-long-only".
"""
from __future__ import annotations
import sys, os, json
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
import real_panel as RP
import info_theoretic_study as IT

FEE = 0.0010   # 10 bps round-trip
N_NULL = 5000

# directional survivors worth an economic look (state on fwd_ret)
DIRECTIONAL = [
    ("DOGEUSDT","moon_near_new","fwd_ret_1d"),
    ("DOGEUSDT","mars_out_of_bounds","fwd_ret_1d"),
    ("UNIUSDT","venus_sign","fwd_ret_1d"),
    ("SOLUSDT","saturn_sign","fwd_ret_1d"),
]


def state_position(lab: np.ndarray, fwd: np.ndarray) -> np.ndarray:
    """In-sample best monotone rule: long the states whose mean fwd ret > grand mean,
    short the rest (sign map).  This is GENEROUS to the signal (in-sample fit) — if it
    still can't beat the shifted null net of fees, it is truly dead."""
    grand = fwd.mean()
    pos = np.zeros(len(lab))
    for s in np.unique(lab):
        msk = lab == s
        pos[msk] = 1.0 if fwd[msk].mean() >= grand else -1.0
    return pos


def net_pnl(pos: np.ndarray, fwd: np.ndarray, fee: float = FEE):
    turn = np.abs(np.diff(np.concatenate([[0.0], pos])))
    gross = pos * fwd
    cost = turn * fee
    net = gross - cost
    return net


def sharpe(x):
    s = x.std()
    return float(x.mean() / s * np.sqrt(252)) if s > 0 else 0.0


def main():
    syms = sorted({a for a, _, _ in DIRECTIONAL})
    bars = RP.load_crypto_bars(syms, "1d", days=3650)
    rows = []
    for asset, state, target in DIRECTIONAL:
        close = bars[asset]["close"]
        states = IT.build_astro_states(close.index)
        targets = IT.build_targets(close)
        m = pd.concat([states[state].rename("s"),
                       targets[target].rename("f")], axis=1).dropna()
        L = m["s"].to_numpy().astype(int)
        F = m["f"].to_numpy().astype(float)
        pos = state_position(L, F)
        net = net_pnl(pos, F)
        gross = pos * F
        obs_sh = sharpe(net)
        obs_net_mean = net.mean()
        # null: circular-shift the LABEL (rebuild the rule each time -> in-sample-fit null)
        rng = np.random.default_rng(abs(hash((asset, state))) % (2**32))
        nl = len(L); lo, hi = IT.MIN_SHIFT, nl - IT.MIN_SHIFT
        null_sh = np.empty(N_NULL)
        for i in range(N_NULL):
            Ls = np.roll(L, rng.integers(lo, hi))
            ps = state_position(Ls, F)
            null_sh[i] = sharpe(net_pnl(ps, F))
        p = (np.sum(null_sh >= obs_sh) + 1) / (N_NULL + 1)
        rows.append(dict(asset=asset, state=state,
                         gross_sharpe=sharpe(gross), net_sharpe=obs_sh,
                         net_ann_ret=float(obs_net_mean * 252),
                         null_sharpe_mean=float(null_sh.mean()),
                         null_sharpe_p95=float(np.quantile(null_sh, 0.95)),
                         p_vs_shifted=p, n=len(m),
                         avg_daily_turnover=float(np.abs(np.diff(np.concatenate([[0.0], pos]))).mean())))
        print(f"{asset:9s} {state:18s} net_SR={obs_sh:6.2f} net_ann={obs_net_mean*252:7.3f} "
              f"null95={np.quantile(null_sh,0.95):5.2f} p={p:.4f}", file=sys.stderr)
    res = pd.DataFrame(rows)
    print(json.dumps(dict(fee_roundtrip=FEE, n_null=N_NULL,
                          n_beats_shifted_null_p05=int((res["p_vs_shifted"] < 0.05).sum())), indent=2))
    print(res.to_string(index=False))
    res.to_csv(os.path.join(os.path.dirname(__file__), "it_economic_check_crypto.csv"), index=False)


if __name__ == "__main__":
    main()
