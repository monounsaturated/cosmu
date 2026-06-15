# intent: DECISIVE disconfirmer for the lunar candidate (moon_lon_deg__sin / moon_decl_deg vs next-day return).
# The regime study flagged it as sign-stable across cells & assets. Three hard tests, fully vectorized:
#   (A) Independence: does the SAME-sign effect hold SEPARATELY in CRYPTO and in EQUITIES? (different markets;
#       if it's just crypto co-movement it dies in equities). Plus per-asset IC sign tally.
#   (B) Economic: a simple TIME-SERIES rule (long when sign*feature predicts up) net of 10bps round-trip on
#       realized turnover, pooled equal-weight across assets — gross & NET annualized Sharpe.
#   (C) OOS: fit sign on first half of the calendar, score the second half. Real effects keep their sign.
# All LIVE-HONEST: deterministic moon features + real prices.
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import regime_conditional_study as S  # noqa: E402

FEE_RT = 0.0010

def spearman(x, y):
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 50: return np.nan
    return float(np.corrcoef(pd.Series(x[m]).rank(), pd.Series(y[m]).rank())[0, 1])

def main(feat="moon_lon_deg__sin"):
    cbars = S.RP.load_crypto_bars(S.CRYPTO, "1d", days=3650)
    ebars = S.RP.load_equity_bars(S.EQUITY)
    bars = {**{s: cbars[s] for s in S.CRYPTO if len(cbars.get(s, [])) > 600},
            **{s: ebars[s] for s in S.EQUITY if len(ebars.get(s, [])) > 600}}
    all_dates = pd.DatetimeIndex(sorted(set().union(*[set(b.index) for b in bars.values()])))
    AP = S.astro_panel(all_dates)
    x_all = AP[feat]
    # per-asset fwd return + aligned feature
    fwd = {}; xf = {}
    for s in bars:
        logc = np.log(bars[s]["close"]); fwd[s] = (logc.shift(-1) - logc).reindex(all_dates)
        xf[s] = x_all.reindex(all_dates)
    crypto = [s for s in bars if s.endswith("USDT")]
    equity = [s for s in bars if not s.endswith("USDT")]

    def pooled_ic(group, lo=None, hi=None):
        ics, ns, signs = [], [], []
        for s in group:
            x = xf[s].to_numpy(); y = fwd[s].to_numpy()
            if lo is not None:
                sel = (all_dates >= lo) & (all_dates < hi); x = x[sel]; y = y[sel]
            ic = spearman(x, y)
            if np.isfinite(ic):
                ics.append(ic); ns.append(np.isfinite(x*y).sum()); signs.append(np.sign(ic))
        if not ics: return np.nan, np.nan, 0
        pic = float(np.average(ics, weights=ns))
        frac = float(np.mean([s == np.sign(pic) for s in signs]))
        return pic, frac, len(ics)

    print(f"=== DISCONFIRM {feat} ===")
    for name, grp in [("ALL", list(bars)), ("CRYPTO", crypto), ("EQUITY", equity)]:
        pic, frac, n = pooled_ic(grp)
        print(f"  {name:7s}: pooled_IC={pic:+.4f}  frac_sign={frac:.2f}  n_assets={n}")

    # OOS halves (ALL)
    mid = all_dates[len(all_dates)//2]
    e_ic, e_fr, _ = pooled_ic(list(bars), all_dates.min(), mid)
    l_ic, l_fr, _ = pooled_ic(list(bars), mid, all_dates.max()+pd.Timedelta(days=1))
    print(f"  OOS halves: early_IC={e_ic:+.4f}  late_IC={l_ic:+.4f}  sign_holds={np.sign(e_ic)==np.sign(l_ic)}")
    # equity OOS specifically (the independent market)
    ee, _, _ = pooled_ic(equity, all_dates.min(), mid)
    el, _, _ = pooled_ic(equity, mid, all_dates.max()+pd.Timedelta(days=1))
    print(f"  EQUITY OOS: early_IC={ee:+.4f}  late_IC={el:+.4f}  sign_holds={np.sign(ee)==np.sign(el)}")

    # economic TS rule: sign from ALL-sample IC; position = -sign(ic_all)*z(feature) clipped to +/-1 (the IC was
    # negative => short when feature high). Net of fees on |dpos| turnover. Pooled equal-weight across assets.
    pic_all, _, _ = pooled_ic(list(bars))
    s_sign = -np.sign(pic_all)  # trade WITH the IC direction
    daily_port = []
    turn_tot = 0.0; notional_tot = 0.0
    for s in bars:
        x = xf[s].to_numpy(); y = fwd[s].to_numpy()
        z = (x - np.nanmean(x)) / (np.nanstd(x) + 1e-9)
        pos = np.clip(s_sign * (-z), -1, 1)  # feature high -> (if ic<0) short
        pos = np.where(np.isfinite(pos), pos, 0.0)
        r = pos * np.nan_to_num(y)
        dpos = np.abs(np.diff(np.concatenate([[0.0], pos])))
        net = r - FEE_RT * dpos
        daily_port.append(pd.Series(net, index=all_dates))
        turn_tot += dpos.sum(); notional_tot += np.abs(pos).sum()
    port = pd.concat(daily_port, axis=1).mean(axis=1).dropna()
    ann = np.sqrt(252)
    gross = pd.concat([pd.Series(np.clip(s_sign*(-((xf[s].to_numpy()-np.nanmean(xf[s].to_numpy()))/(np.nanstd(xf[s].to_numpy())+1e-9))),-1,1)*np.nan_to_num(fwd[s].to_numpy()),index=all_dates) for s in bars],axis=1).mean(axis=1).dropna()
    gs = gross.mean()/gross.std()*ann
    ns_ = port.mean()/port.std()*ann
    print(f"  ECON TS rule: gross_Sharpe={gs:+.2f}  NET_Sharpe={ns_:+.2f}  avg_turnover/day={turn_tot/(len(all_dates)*len(bars)):.3f}")
    print(f"  VERDICT: {'TRADEABLE-ish' if ns_>0.3 and np.sign(ee)==np.sign(el) and abs(pooled_ic(equity)[0])>0.01 else 'DIES (not net-tradeable or not market-independent)'}")

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(); p.add_argument("--feat", default="moon_lon_deg__sin"); a = p.parse_args()
    main(a.feat)
