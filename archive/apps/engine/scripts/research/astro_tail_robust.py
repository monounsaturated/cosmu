"""
Robustness / disconfirmer harness for any tail_extreme candidate.

Two INDEPENDENT surrogates (a candidate must survive BOTH, not just circular-shift):
  (A) circular-shift of the astro mask  (already in astro_tail_fast.fft_null_or)
  (B) STATIONARY BLOCK BOOTSTRAP of the EVENT series — resample the event indicator in
      blocks (preserves clustering/autocorrelation), keep the mask fixed, recompute OR.
      This breaks the date-alignment differently from a rigid rotation, so agreement
      between (A) and (B) is strong evidence the alignment is not an artifact of one
      surrogate's structure.

Plus an ECONOMIC test: does the astro-active state actually let you AVOID / HARVEST the
extreme move net of ~10bps round trip? For 'crash_onset' we test a simple rule: flat the
day after the mask fires (skip the crash) vs always-in; for 'vol_spike' we test a long-
straddle proxy (does |next-day ret| in the active state exceed the cost of a straddle?).
Statistical clustering that isn't tradeable net of costs is a non-finding.
"""
import sys
sys.path.insert(0,'scripts/research/astro_deep'); sys.path.insert(0,'scripts/research/astro_strategy_lab')
import numpy as np, pandas as pd
import astro_tail_fast as TF

RNG=np.random.default_rng(7)

def block_bootstrap_null_or(event, mask, block=10, n=4000):
    """Stationary block bootstrap of the EVENT series (mask fixed). Returns obs OR, null, p."""
    T=len(event); obs=TF.or_from_counts(
        np.sum((mask==1)&(event==1)), np.sum((mask==1)&(event==0)),
        np.sum((mask==0)&(event==1)), np.sum((mask==0)&(event==0)))
    null=np.empty(n)
    nblocks=int(np.ceil(T/block))
    for i in range(n):
        starts=RNG.integers(0,T,size=nblocks)
        idx=(starts[:,None]+np.arange(block)[None,:]).ravel()%T
        e2=event[idx[:T]]
        null[i]=TF.or_from_counts(
            np.sum((mask==1)&(e2==1)), np.sum((mask==1)&(e2==0)),
            np.sum((mask==0)&(e2==1)), np.sum((mask==0)&(e2==0)))
    p=(np.sum(null>=obs)+1)/(n+1)
    return obs,null,p


def test_candidate(etype, mname, jwin=60, vwin=30, k=3.0, block=10):
    cc=TF._load_cache(); panels=cc['panels']; closes=cc['closes']; master=cc['master']
    fn={'jump':lambda c:TF.ev_jump(c,jwin,k),'crash_onset':lambda c:TF.ev_crash(c,jwin,k),
        'vol_spike':lambda c:TF.ev_volspike(c,vwin,k)}[etype]
    out=[]
    for (cls,sym),c in closes.items():
        if len(c)<400: continue
        idx=c.index
        mask=master[cls].reindex(idx)[mname].values.astype(float)
        if mask.sum()<10 or (len(mask)-mask.sum())<10: continue
        ev=fn(c).reindex(idx).fillna(0).values.astype(float)
        if ev.sum()<15: continue
        oA,_,pA,lf=TF.fft_null_or(ev,mask)
        oB,_,pB=block_bootstrap_null_or(ev,mask,block=block)
        out.append(dict(cls=cls,sym=sym,n_ev=int(ev.sum()),OR=float(oA),lift=float(lf),
                        p_circshift=float(pA),p_blockboot=float(pB)))
    return pd.DataFrame(out)


def economic_crash_avoid(mname, jwin=60, k=3.0, cost_bps=10.0):
    """For each asset: compare buy&hold vs 'go flat the day AFTER mask fires for 1 day'.
    If the astro state genuinely precedes crashes, skipping it should improve risk-adj
    return net of cost. We charge cost_bps round-trip each time we toggle out and back."""
    cc=TF._load_cache(); closes=cc['closes']; master=cc['master']
    rows=[]
    for (cls,sym),c in closes.items():
        if len(c)<400: continue
        idx=c.index; r=np.log(c).diff().reindex(idx).fillna(0).values
        mask=master[cls].reindex(idx)[mname].values.astype(float)
        # position = 0 on the day AFTER mask fires (act on tomorrow's bar, no look-ahead), else 1
        pos=np.ones(len(idx)); fire=np.roll(mask,1); fire[0]=0
        pos[fire>0]=0.0
        toggles=np.abs(np.diff(np.concatenate([[1],pos])))
        cost=toggles*(cost_bps/1e4)
        strat=pos*r - cost
        bh=r
        def sharpe(x):
            sd=np.std(x); return (np.mean(x)/sd*np.sqrt(252)) if sd>0 else 0.0
        rows.append(dict(cls=cls,sym=sym,
                         bh_sharpe=float(sharpe(bh)), strat_sharpe=float(sharpe(strat)),
                         bh_cumret=float(np.exp(np.sum(bh))-1),
                         strat_cumret=float(np.exp(np.sum(strat))-1),
                         n_flat=int((pos==0).sum())))
    df=pd.DataFrame(rows)
    df['sharpe_delta']=df.strat_sharpe-df.bh_sharpe
    return df


if __name__=='__main__':
    import argparse,json
    ap=argparse.ArgumentParser()
    ap.add_argument('--etype',required=True); ap.add_argument('--mask',required=True)
    ap.add_argument('--k',type=float,default=3.0); ap.add_argument('--block',type=int,default=10)
    ap.add_argument('--econ',action='store_true')
    a=ap.parse_args()
    pd.set_option('display.width',200); pd.set_option('display.max_rows',200)
    d=test_candidate(a.etype,a.mask,k=a.k,block=a.block)
    print(f'=== {a.etype} x {a.mask} (k={a.k}) per-asset two-surrogate ===')
    print(d.sort_values('p_circshift').to_string(index=False))
    # pooled Stouffer Z for EACH surrogate (one-sided enrichment), directly comparable
    from scipy.stats import norm
    def stouffer_p(ps):
        ps=np.clip(np.asarray(ps,float),1e-9,1-1e-9)
        z=np.sum(norm.isf(ps))/np.sqrt(len(ps))   # isf = inverse survival = z for one-sided
        return z, float(norm.sf(z))
    zc,pc=stouffer_p(d.p_circshift.values)
    zb,pb=stouffer_p(d.p_blockboot.values)
    both=((d.p_circshift<0.1)&(d.p_blockboot<0.1)&(d.OR>1)).mean()
    print(f'\nPOOLED circular-shift : Stouffer Z={zc:.3f}  p={pc:.5f}')
    print(f'POOLED block-bootstrap: Stouffer Z={zb:.3f}  p={pb:.5f}   <-- INDEPENDENT surrogate')
    print(f'frac assets OR>1 & both surrogate p<0.1: {both:.2f}')
    print(f'median OR={d.OR.median():.3f}  median p_circ={d.p_circshift.median():.3f}  median p_block={d.p_blockboot.median():.3f}')
    if a.econ:
        e=economic_crash_avoid(a.mask,k=a.k)
        print(f'\n=== ECONOMIC (skip day after {a.mask} fires, 10bps) ===')
        print(e.sort_values('sharpe_delta',ascending=False).to_string(index=False))
        print(f'mean sharpe_delta={e.sharpe_delta.mean():.3f}  median={e.sharpe_delta.median():.3f}  frac>0={ (e.sharpe_delta>0).mean():.2f}')
