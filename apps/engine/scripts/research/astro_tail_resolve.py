"""
RESOLVE the fork for the 3 aspect-mask candidates that pass worst-of-4-surrogate Bonf6:
  jump x hard_aspect_hi, jump x conj_hi, vol_spike x hard_aspect_hi
(all use LOW-FREQUENCY masks tau=22-37d, where the circular-shift null draws from only
~80-120 independent configurations and may be too lenient.)

DECISIVE TEST = WITHIN-YEAR PERMUTATION NULL.
For each asset, partition the timeline into calendar years. The null SHUFFLES the mask
in CIRCULAR fashion WITHIN each year independently. This:
  - preserves the within-year astro structure (so a genuine 'aspects precede extremes
    within a year' signal can still show up), and
  - DESTROYS any cross-year low-frequency alignment between the aspect regime and the
    volatility regime (the suspected confound for a tau=30d mask).
The event series is held fixed (its clustering preserved). Pooled Stouffer across assets.

If the candidates collapse here, they were regime coincidences, not astro->extreme links.

Also: ECONOMIC test. Even a real clustering must be tradeable net of 10bps. We test a
straddle-proxy for vol_spike (does realized |next-ret| in the active state pay for a
straddle?) and a crash-avoid rule for the jump candidates.
"""
import sys
sys.path.insert(0,'scripts/research/astro_deep'); sys.path.insert(0,'scripts/research/astro_strategy_lab')
import numpy as np, pandas as pd
from scipy.stats import norm
import astro_tail_fast as TF

RNG=np.random.default_rng(23)
CAND=[('jump','hard_aspect_hi'),('jump','conj_hi'),('vol_spike','hard_aspect_hi'),
      ('crash_onset','conj_hi'),('crash_onset','full_moon_window')]  # +2 for contrast

def or2(mask,ev):
    return TF.or_from_counts(np.sum((mask==1)&(ev==1)),np.sum((mask==1)&(ev==0)),
                             np.sum((mask==0)&(ev==1)),np.sum((mask==0)&(ev==0)))

def within_year_circ_null(ev,mask,years,n=3000):
    obs=or2(mask,ev)
    uy=np.unique(years); idx_by_year=[np.where(years==y)[0] for y in uy]
    null=np.empty(n)
    for i in range(n):
        m2=mask.copy()
        for ix in idx_by_year:
            L=len(ix)
            if L>3:
                s=RNG.integers(1,L)
                m2[ix]=np.roll(mask[ix],s)
        null[i]=or2(m2,ev)
    return obs,(np.sum(null>=obs)+1)/(n+1)

def stouffer(ps):
    ps=np.clip(np.asarray(ps,float),1e-9,1-1e-9)
    z=np.sum(norm.isf(ps))/np.sqrt(len(ps)); return z,float(norm.sf(z))

def run():
    cc=TF._load_cache(); closes=cc['closes']; master=cc['master']; K=3.0
    efn={'jump':lambda c:TF.ev_jump(c,60,K),'crash_onset':lambda c:TF.ev_crash(c,60,K),'vol_spike':lambda c:TF.ev_volspike(c,30,K)}
    out=[]
    for et,mn in CAND:
        ps=[]; ors=[]; n=0
        for (cls,sym),c in closes.items():
            if len(c)<400: continue
            idx=c.index; years=idx.year.values
            mask=master[cls].reindex(idx)[mn].values.astype(float)
            if mask.sum()<10 or (len(mask)-mask.sum())<10: continue
            ev=efn[et](c).reindex(idx).fillna(0).values.astype(float)
            if ev.sum()<15: continue
            o,p=within_year_circ_null(ev,mask,years); ps.append(p); ors.append(o); n+=1
        z,pc=stouffer(ps)
        out.append(dict(etype=et,maskname=mn,n_assets=n,mean_OR=float(np.mean(ors)),
                        withinYr_circ_Z=z, withinYr_circ_p=pc, frac_OR_gt1=float(np.mean(np.array(ors)>1))))
    return pd.DataFrame(out)


def econ_straddle(mname, vwin=30, k=3.0, cost_bps=10.0):
    """Vol-spike straddle proxy: on days the mask is active, would a 1-day long straddle
    (cost ~ 2*sigma_implied; we proxy implied by trailing realized sigma) be profitable?
    Payoff = |next-day log-ret| - straddle_cost. We compare active vs inactive days. A
    tradeable vol effect needs E[|ret| - cost | active] > E[|ret| - cost | inactive] AND
    > 0 net of cost_bps execution."""
    cc=TF._load_cache(); closes=cc['closes']; master=cc['master']; rows=[]
    for (cls,sym),c in closes.items():
        if len(c)<400: continue
        idx=c.index; r=np.log(c).diff()
        sig=r.rolling(vwin,min_periods=15).std().shift(1)          # trailing implied proxy
        nxt=r.shift(-1).abs()                                       # realized move to harvest
        mask=master[cls].reindex(idx)[mname].values.astype(float)
        straddle_cost=2*sig + cost_bps/1e4                          # premium + execution
        pnl=(nxt - straddle_cost)
        act=mask>0
        pa=pnl[act].mean(); pi=pnl[~act].mean()
        rows.append(dict(cls=cls,sym=sym,edge_active=float(pa),edge_inactive=float(pi),
                         edge_delta=float(pa-pi)))
    d=pd.DataFrame(rows)
    return d


if __name__=='__main__':
    pd.set_option('display.width',200)
    d=run()
    print('=== WITHIN-YEAR circular-shift null (destroys cross-year regime confound) ===')
    print(d.to_string(index=False))
    surv=d[(d.withinYr_circ_p*5<0.05)]   # Bonferroni across the 5 tested
    print('\nSurvivors after within-year null (Bonferroni x5, p<0.05):',
          list(zip(surv.etype,surv.maskname)) or 'NONE')

    print('\n=== ECONOMIC: vol-spike straddle proxy on hard_aspect_hi (10bps) ===')
    e=econ_straddle('hard_aspect_hi')
    print(e.sort_values('edge_delta',ascending=False).to_string(index=False))
    print('mean edge_delta=%.6f  median=%.6f  frac_delta>0=%.2f  | mean edge_active=%.6f (want >0)'
          %(e.edge_delta.mean(), e.edge_delta.median(), (e.edge_delta>0).mean(), e.edge_active.mean()))
    print('FINISHED')
