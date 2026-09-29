# intent: FINAL adjudication of the lunar TS candidate. Three hard tests the +0.59 net Sharpe must pass:
#  (1) PROPER NULL on the Sharpe: circular-shift the moon feature (preserves its monthly autocorrelation),
#      rebuild the SAME TS rule, recompute the pooled net Sharpe. p = frac of null Sharpe >= observed.
#  (2) CALENDAR CONFOUND: the synodic month (29.5d) can alias with turn-of-month / day-of-week / month-of-year.
#      Orthogonalize each asset's forward return against {dow dummies, day-of-month, month dummies} FIRST,
#      then recompute the moon IC on the residual. If the moon IC vanishes -> it was a calendar proxy.
#  (3) ROBUSTNESS: per-asset net Sharpe spread (broad vs a few names), and crypto-only vs equity-only Sharpe.
# LIVE-HONEST: deterministic moon feature + real prices only.
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import regime_conditional_study as S  # noqa: E402

FEE_RT = 0.0010
RNG = np.random.default_rng(7)

def spearman(x, y):
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 50: return np.nan
    return float(np.corrcoef(pd.Series(x[m]).rank(), pd.Series(y[m]).rank())[0, 1])

def ts_rule_net_returns(z, y, s_sign):
    """position = clip(s_sign*(-z),-1,1); daily net = pos*y - fee*|dpos|. Returns the net daily series."""
    pos = np.clip(s_sign * (-z), -1, 1); pos = np.where(np.isfinite(pos), pos, 0.0)
    r = pos * np.nan_to_num(y)
    dpos = np.abs(np.diff(np.concatenate([[0.0], pos])))
    return r - FEE_RT * dpos

def main(feat="moon_lon_deg__sin", n_null=400):
    cbars = S.RP.load_crypto_bars(S.CRYPTO, "1d", days=3650)
    ebars = S.RP.load_equity_bars(S.EQUITY)
    bars = {**{s: cbars[s] for s in S.CRYPTO if len(cbars.get(s, [])) > 600},
            **{s: ebars[s] for s in S.EQUITY if len(ebars.get(s, [])) > 600}}
    all_dates = pd.DatetimeIndex(sorted(set().union(*[set(b.index) for b in bars.values()])))
    AP = S.astro_panel(all_dates)
    x_all = AP[feat].reindex(all_dates).to_numpy()
    L = len(all_dates)
    fwd = {}
    for s in bars:
        logc = np.log(bars[s]["close"]); fwd[s] = (logc.shift(-1) - logc).reindex(all_dates).to_numpy()

    # observed pooled IC & TS-rule net Sharpe
    z_all = (x_all - np.nanmean(x_all)) / (np.nanstd(x_all) + 1e-9)
    ics = [spearman(x_all, fwd[s]) for s in bars]
    pic = float(np.nanmean(ics)); s_sign = -np.sign(pic)
    def pooled_net_sharpe(zvec):
        cols = [pd.Series(ts_rule_net_returns(zvec, fwd[s], s_sign), index=all_dates) for s in bars]
        port = pd.concat(cols, axis=1).mean(axis=1).dropna()
        return port.mean() / port.std() * np.sqrt(252) if port.std() > 0 else np.nan
    obs_sharpe = pooled_net_sharpe(z_all)
    print(f"=== FINAL ADJUDICATE {feat} ===")
    print(f"observed: pooled_IC={pic:+.4f}  TS net Sharpe={obs_sharpe:+.3f}")

    # (1) circular-shift null on the Sharpe
    null_sh = np.empty(n_null)
    for j in range(n_null):
        k = int(RNG.integers(30, L - 30))
        xs = np.concatenate([x_all[-k:], x_all[:-k]])
        zs = (xs - np.nanmean(xs)) / (np.nanstd(xs) + 1e-9)
        null_sh[j] = pooled_net_sharpe(zs)
    null_sh = null_sh[np.isfinite(null_sh)]
    p_one = (np.sum(null_sh >= obs_sharpe) + 1) / (len(null_sh) + 1)
    print(f"(1) phase-shift null Sharpe: mean={null_sh.mean():+.3f} std={null_sh.std():.3f} "
          f"95pct={np.percentile(null_sh,95):+.3f}  -> one-sided p={p_one:.4f}")

    # (2) calendar-confound control: residualize fwd return on dow + dom + month, then re-IC
    dow = all_dates.dayofweek.to_numpy(); dom = all_dates.day.to_numpy(); mon = all_dates.month.to_numpy()
    D = np.column_stack([np.ones(L)] + [ (dow==i).astype(float) for i in range(6)] +
                        [ (mon==i).astype(float) for i in range(1,12)] + [dom.astype(float), (dom**2).astype(float)])
    resid_ics = []
    for s in bars:
        y = fwd[s].copy(); m = np.isfinite(y)
        if m.sum() < 200: continue
        beta, *_ = np.linalg.lstsq(D[m], y[m], rcond=None)
        res = np.full(L, np.nan); res[m] = y[m] - D[m] @ beta
        resid_ics.append(spearman(x_all, res))
    resid_ics = [i for i in resid_ics if np.isfinite(i)]
    print(f"(2) calendar-residualized pooled IC = {np.mean(resid_ics):+.4f}  "
          f"(raw {pic:+.4f}); ratio kept = {np.mean(resid_ics)/pic:.2f}")

    # (3) per-asset net Sharpe spread + crypto/equity split
    per = {}
    for s in bars:
        net = pd.Series(ts_rule_net_returns(z_all, fwd[s], s_sign), index=all_dates).dropna()
        per[s] = net.mean()/net.std()*np.sqrt(252) if net.std()>0 else np.nan
    per = pd.Series(per)
    crypto = [s for s in bars if s.endswith("USDT")]; equity=[s for s in bars if not s.endswith("USDT")]
    print(f"(3) per-asset net Sharpe: median={per.median():+.2f}  frac>0={np.mean(per>0):.2f}  "
          f"min={per.min():+.2f} max={per.max():+.2f}")
    print(f"    crypto median Sharpe={per[crypto].median():+.2f}  equity median Sharpe={per[equity].median():+.2f}")
    print(f"VERDICT: null_p={p_one:.4f} {'BEATS' if p_one<0.05 else 'FAILS'} phase null; "
          f"calendar {'SURVIVES' if abs(np.mean(resid_ics))>0.5*abs(pic) else 'KILLED-as-proxy'}")

if __name__ == "__main__":
    import argparse
    p=argparse.ArgumentParser(); p.add_argument("--feat",default="moon_lon_deg__sin"); p.add_argument("--nnull",type=int,default=400)
    a=p.parse_args(); main(a.feat,a.nnull)
