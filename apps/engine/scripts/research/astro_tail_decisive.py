"""
DECISIVE disconfirmer for the k=3.0 pooled survivors.

The pooled survivors are dominated by ASPECT-COUNT masks (hard_aspect_hi, conj_hi) and
lunar masks (full_moon_window, high_illum, moon_fast). Aspect-count masks are LOW-FREQUENCY
(slow outer-planet drift => months-long 'on' runs). For a low-frequency mask, a rigid
circular-shift draws from only a few effectively-independent configurations, so it can
UNDER-estimate the null variance and inflate significance. This is the classic trap.

We attack each survivor with:
  (1) circular-shift pooled Stouffer Z         (the lenient-for-LF-mask test; baseline)
  (2) STATIONARY BLOCK BOOTSTRAP of events, block in {10,30,90}: a LONG block preserves
      regime-scale event clustering, which is the right null for a regime-like mask.
  (3) mask autocorrelation length  tau  (how low-frequency is the mask? => how few
      independent circular shifts there really are)
  (4) REGIME-CONFOUND check: recompute the pooled OR after removing the lowest-frequency
      common variation -- split each asset's history into yearly blocks and compute the OR
      WITHIN year then average (a within-stratum / Mantel-Haenszel-by-year OR). If the
      effect is a 'high-vol-year happened to coincide with high-aspect-year' artifact, the
      within-year OR collapses to ~1.

A survivor is only credible if it holds under (2) at long block AND under (4).
"""
import sys
sys.path.insert(0,'scripts/research/astro_deep'); sys.path.insert(0,'scripts/research/astro_strategy_lab')
import numpy as np, pandas as pd
from scipy.stats import norm
import astro_tail_fast as TF

RNG=np.random.default_rng(11)

SURVIVORS = [   # (etype, mask) -- the k=3.0 pooled BH survivors
    ('jump','hard_aspect_hi'), ('jump','conj_hi'), ('crash_onset','conj_hi'),
    ('vol_spike','hard_aspect_hi'), ('crash_onset','full_moon_window'),
    ('crash_onset','high_illum'),
]

def or2(mask,ev):
    return TF.or_from_counts(np.sum((mask==1)&(ev==1)),np.sum((mask==1)&(ev==0)),
                             np.sum((mask==0)&(ev==1)),np.sum((mask==0)&(ev==0)))

def block_boot_p(ev,mask,block,n=3000):
    T=len(ev); obs=or2(mask,ev); nb=int(np.ceil(T/block)); null=np.empty(n)
    ar=np.arange(block)
    for i in range(n):
        st=RNG.integers(0,T,size=nb)
        idx=(st[:,None]+ar[None,:]).ravel()%T
        e2=ev[idx[:T]]
        null[i]=or2(mask,e2)
    return (np.sum(null>=obs)+1)/(n+1)

def autocorr_tau(mask):
    """integrated autocorrelation length (days) of the 0/1 mask."""
    x=mask-mask.mean(); v=np.dot(x,x)
    if v==0: return 0.0
    tau=1.0
    for lag in range(1,120):
        c=np.dot(x[:-lag],x[lag:])/v
        if c<=0: break
        tau+=2*c
    return tau

def within_year_or(ev,mask,years):
    """Mantel-Haenszel OR pooled across calendar-year strata (removes year-regime confound)."""
    num=den=0.0
    for y in np.unique(years):
        s=years==y
        if s.sum()<60: continue
        m=mask[s]; e=ev[s]; T=s.sum()
        a=np.sum((m==1)&(e==1)); b=np.sum((m==1)&(e==0)); c=np.sum((m==0)&(e==1)); d=np.sum((m==0)&(e==0))
        if (a+b)==0 or (c+d)==0: continue
        num+=a*d/T; den+=b*c/T
    return (num+1e-9)/(den+1e-9)

def stouffer(ps):
    ps=np.clip(np.asarray(ps,float),1e-9,1-1e-9)
    z=np.sum(norm.isf(ps))/np.sqrt(len(ps)); return z,float(norm.sf(z))

def run():
    cc=TF._load_cache(); closes=cc['closes']; master=cc['master']
    K=3.0; rows=[]
    efn={'jump':lambda c:TF.ev_jump(c,60,K),'crash_onset':lambda c:TF.ev_crash(c,60,K),'vol_spike':lambda c:TF.ev_volspike(c,30,K)}
    for et,mn in SURVIVORS:
        pc=[]; p10=[]; p30=[]; p90=[]; ors=[]; wy_ors=[]; taus=[]; nass=0
        for (cls,sym),c in closes.items():
            if len(c)<400: continue
            idx=c.index; years=idx.year.values
            mask=master[cls].reindex(idx)[mn].values.astype(float)
            if mask.sum()<10 or (len(mask)-mask.sum())<10: continue
            ev=efn[et](c).reindex(idx).fillna(0).values.astype(float)
            if ev.sum()<15: continue
            nass+=1
            o,_,p_circ,_=TF.fft_null_or(ev,mask)
            ors.append(o); pc.append(p_circ); taus.append(autocorr_tau(mask))
            p10.append(block_boot_p(ev,mask,10)); p30.append(block_boot_p(ev,mask,30)); p90.append(block_boot_p(ev,mask,90))
            wy_ors.append(within_year_or(ev,mask,years))
        zc,pcomb_c=stouffer(pc); z10,p10c=stouffer(p10); z30,p30c=stouffer(p30); z90,p90c=stouffer(p90)
        rows.append(dict(etype=et,mask=mn,n_assets=nass,
            mean_OR=float(np.mean(ors)), mean_withinYr_OR=float(np.mean(wy_ors)),
            mask_tau_days=float(np.mean(taus)),
            Z_circ=zc, p_circ=pcomb_c,
            Z_block10=z10, p_block10=p10c,
            Z_block30=z30, p_block30=p30c,
            Z_block90=z90, p_block90=p90c))
    return pd.DataFrame(rows)

if __name__=='__main__':
    pd.set_option('display.width',240); pd.set_option('display.max_columns',40)
    d=run()
    cols=['etype','mask','n_assets','mask_tau_days','mean_OR','mean_withinYr_OR',
          'Z_circ','Z_block10','Z_block30','Z_block90','p_circ','p_block10','p_block30','p_block90']
    print(d[cols].to_string(index=False))
    # BH across the 6 x 4-surrogate p's? No -- report the WEAKEST (most honest) surrogate per row.
    d['worst_p']=d[['p_circ','p_block10','p_block30','p_block90']].max(axis=1)
    print('\nHonest verdict per survivor (worst-surrogate p, Bonferroni x6):')
    for _,r in d.iterrows():
        bonf=min(1.0,r.worst_p*6)
        verdict='SURVIVES' if bonf<0.05 and r.mean_withinYr_OR>1.05 else 'DIES'
        print(f"  {r.etype:12s} x {r.mask:16s} worstp={r.worst_p:.4f} bonf6={bonf:.4f} withinYrOR={r.mean_withinYr_OR:.3f} tau={r.mask_tau_days:.0f}d -> {verdict}")
    d.to_csv('/tmp/tail_decisive.csv',index=False); print('\nsaved /tmp/tail_decisive.csv\nFINISHED')
