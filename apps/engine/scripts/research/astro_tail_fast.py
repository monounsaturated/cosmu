"""
tail_extreme — FFT-exact circular-shift null version (supersedes astro_tail_extreme.py
for speed). Identical statistics, but the circular-shift null uses the FULL set of T
valid shifts computed exactly via FFT cross-correlation instead of Monte-Carlo sampling.

Key identity: for a fixed event series e and mask m of length T, the count
   n11(s) = sum_t m[(t-s) mod T] * e[t]    (events co-occurring with the mask rolled by s)
is the circular cross-correlation of e and m, = irfft(rfft(e) * conj(rfft(m))). The
marginals sum(m) and sum(e) are invariant under circular shift, so the full 2x2 table
(and hence OR / lift) for EVERY shift follows in O(T log T). The null is then the exact
distribution of the statistic over all (de-correlated) circular shifts.

This preserves both the astro periodicity (mask is shifted as a whole, rigid) and the
event clustering (event series untouched) — the correct surrogate.
"""
import sys, json
sys.path.insert(0, 'scripts/research/astro_deep')
sys.path.insert(0, 'scripts/research/astro_strategy_lab')
import numpy as np
import pandas as pd
import astro_features_deep as AF
import real_panel as RP

MIN_SHIFT = 14   # exclude near-zero shifts (mask ~ itself) from the null

CRYPTO = ['BTCUSDT','ETHUSDT','BNBUSDT','SOLUSDT','XRPUSDT','DOGEUSDT','ADAUSDT',
          'AVAXUSDT','LINKUSDT','DOTUSDT','LTCUSDT','BCHUSDT','ATOMUSDT','UNIUSDT',
          'FILUSDT','NEARUSDT','AAVEUSDT']
EQUITY = ['SPY','QQQ','IWM','GLD','SLV','TLT','XLE','XLF','XLK','USO']


def daily_close(df):
    s = df['close'].copy()
    s.index = pd.to_datetime(s.index).normalize()
    s = s[~s.index.duplicated(keep='last')].sort_index()
    return s

def log_ret(c): return np.log(c).diff()

def ev_jump(c, win=60, k=3.0):
    r=log_ret(c); mu=r.rolling(win,min_periods=20).mean().shift(1); sd=r.rolling(win,min_periods=20).std().shift(1)
    return ((r-mu)/sd).abs().gt(k).astype(float)

def ev_crash(c, win=60, k=3.0):
    r=log_ret(c); mu=r.rolling(win,min_periods=20).mean().shift(1); sd=r.rolling(win,min_periods=20).std().shift(1)
    return ((r-mu)/sd).lt(-k).astype(float)

def ev_volspike(c, win=30, k=3.0):
    r=log_ret(c).abs(); mu=r.rolling(win,min_periods=15).mean().shift(1); sd=r.rolling(win,min_periods=15).std().shift(1)
    return ((r-mu)/sd).gt(k).astype(float)


def build_masks_df(idx):
    """Compute boolean astro masks on a (super-set) index, returned as a DataFrame so any
    sub-asset can slice by .reindex(asset_idx). Thresholds (quantiles) are computed on the
    SUPERSET index — they are functions of the deterministic astro series only (no price,
    no look-ahead), so this is fully PIT-honest as a definition of 'astro-active state'."""
    a = AF.deep_astro_features(idx)
    age=a['moon_synodic_age'].values; illum=a['moon_illum_frac'].values
    m={}
    m['new_moon_window']  = (age<0.06)|(age>0.94)
    m['full_moon_window'] = (np.abs(age-0.5)<0.06)
    m['syzygy_window']    = m['new_moon_window']|m['full_moon_window']
    m['quarter_window']   = (np.abs(age-0.25)<0.05)|(np.abs(age-0.75)<0.05)
    m['low_illum']        = illum<0.10
    m['high_illum']       = illum>0.90
    m['eclipse_window']   = a['eclipse_window'].values>0.5
    m['near_eclipse_7d']  = a['days_to_next_eclipse'].values<7.0
    ha=a['hard_aspect_count'].values;   m['hard_aspect_hi']=ha>=np.quantile(ha,0.80)
    cj=a['aspect_conjunction_count'].values; m['conj_hi']=cj>=np.quantile(cj,0.80)
    md=np.abs(a['moon_decl_deg'].values);m['moon_decl_extreme']=md>=np.quantile(md,0.85)
    m['mercury_retro']    = a['mercury_retrograde'].values>0.5
    rc=a[[c for c in a.columns if c.endswith('_retrograde')]].sum(axis=1).values
    m['many_retro']       = rc>=np.quantile(rc,0.80)
    ms=a['moon_speed_deg'].values;       m['moon_fast']=ms>=np.quantile(ms,0.85)
    return pd.DataFrame({k:v.astype(float) for k,v in m.items()}, index=idx)


def or_from_counts(n11, n10, n01, n00):
    return ((n11+0.5)*(n00+0.5))/((n10+0.5)*(n01+0.5))

def fft_null_or(event, mask):
    """Return observed OR and the full circular-shift null OR array (len T-2*MIN_SHIFT)."""
    T=len(event)
    E=event.sum(); M=mask.sum()
    # n11(s) for all shifts via cross-correlation
    n11 = np.fft.irfft(np.fft.rfft(event)*np.conj(np.fft.rfft(mask)), n=T)
    n11 = np.rint(n11)                      # integer counts
    n10 = M - n11                           # mask active, no event
    n01 = E - n11                           # event, mask inactive
    n00 = T - n11 - n10 - n01
    OR  = or_from_counts(n11, n10, n01, n00)
    obs = OR[0]                             # shift 0 = aligned (observed)
    # null = all shifts except the small-|s| band around 0 (and T)
    sel = np.ones(T, bool);
    sel[:MIN_SHIFT]=False; sel[T-MIN_SHIFT:]=False
    null = OR[sel]
    p = (np.sum(null>=obs)+1)/(null.size+1)
    # lift for reporting
    pa = n11[0]/M if M>0 else np.nan
    pi = n01[0]/(T-M) if (T-M)>0 else np.nan
    lf = pa/pi if (pi and not np.isnan(pi)) else np.nan
    return obs, null, p, lf

def bh_fdr(p, alpha=0.05):
    p=np.asarray(p,float); m=len(p); order=np.argsort(p); r=p[order]
    crit=np.arange(1,m+1)/m*alpha; passed=r<=crit
    out=np.zeros(m,bool)
    if passed.any():
        k=np.max(np.where(passed)); out[p<=r[k]]=True
    q=r*m/np.arange(1,m+1); q=np.minimum.accumulate(q[::-1])[::-1]
    qf=np.empty(m); qf[order]=q
    return out,qf


_CACHE = {}   # process-level cache so a multi-k sweep reuses panels + astro masters
def _load_cache():
    if _CACHE: return _CACHE
    crypto=RP.load_crypto_bars(CRYPTO,'1d',days=3650)
    equity=RP.load_equity_bars(EQUITY)
    panels={('crypto',k):v for k,v in crypto.items()}; panels.update({('equity',k):v for k,v in equity.items()})
    closes = {ks: daily_close(df) for ks,df in panels.items()}
    def superset(cls):
        idxs=[s.index for (c,_),s in closes.items() if c==cls]
        u=idxs[0]
        for i in idxs[1:]: u=u.union(i)
        return u
    master={}
    for cls in ('crypto','equity'):
        sup=superset(cls)
        print(f'[build] astro masks for {cls}: {len(sup)} days {sup[0].date()}..{sup[-1].date()}', flush=True)
        master[cls]=build_masks_df(sup)
    _CACHE.update(dict(panels=panels, closes=closes, master=master))
    return _CACHE


def run(jump_k=3.0, jwin=60, vwin=30):
    cc=_load_cache(); panels=cc['panels']; closes=cc['closes']; master=cc['master']
    edefs={'jump':lambda c:ev_jump(c,jwin,jump_k),'crash_onset':lambda c:ev_crash(c,jwin,jump_k),'vol_spike':lambda c:ev_volspike(c,vwin,jump_k)}

    rows=[]; pooled_store={}
    for (cls,sym),df in panels.items():
        c=closes[(cls,sym)]
        if len(c)<400: continue
        idx=c.index
        msub=master[cls].reindex(idx)
        masks={col: msub[col].values.astype(float) for col in msub.columns}
        for et,fn in edefs.items():
            ev=fn(c).reindex(idx).fillna(0).values.astype(float)
            if ev.sum()<15: continue
            for mn,mask in masks.items():
                if mask.sum()<10 or (len(mask)-mask.sum())<10: continue
                obs,null,p,lf=fft_null_or(ev,mask)
                rows.append(dict(cls=cls,sym=sym,etype=et,mask=mn,n_events=int(ev.sum()),
                                 prevalence=float(mask.mean()),OR=float(obs),lift=float(lf),
                                 null_med=float(np.median(null)),p=float(p)))
                pooled_store.setdefault((et,mn),[]).append((ev,mask))
    res=pd.DataFrame(rows)
    res['fdr_pass'],res['q']=bh_fdr(res['p'].values)

    # pooled (Mantel-Haenszel-ish OR) with FFT null per asset, summed
    prows=[]
    for (et,mn),lst in pooled_store.items():
        if len(lst)<5: continue
        # per-asset n11(s) arrays, aligned by shift index 0..T-1 (different T per asset!)
        # Use fractional-overlap MH weights as in slow version. Build common shift grid by
        # sampling: take the per-asset full null OR distributions and combine via summed
        # weighted num/den at matched RANDOM shifts is hard across unequal T. Instead we
        # combine using the per-asset standardized OR (z vs its own null) -> Stouffer.
        zs=[]; obs_ors=[]
        for ev,mask in lst:
            obs,null,p,lf=fft_null_or(ev,mask)
            mu=np.mean(np.log(null)); sd=np.std(np.log(null))
            z=(np.log(obs)-mu)/sd if sd>0 else 0.0
            zs.append(z); obs_ors.append(obs)
        zs=np.array(zs)
        Z=zs.sum()/np.sqrt(len(zs))            # Stouffer combined
        from math import erf,sqrt
        p_comb=0.5*(1-erf(Z/sqrt(2)))          # one-sided (enrichment)
        prows.append(dict(etype=et,mask=mn,n_assets=len(lst),
                          mean_OR=float(np.mean(obs_ors)),
                          median_OR=float(np.median(obs_ors)),
                          frac_OR_gt1=float(np.mean(np.array(obs_ors)>1)),
                          stouffer_Z=float(Z),p=float(p_comb)))
    pooled=pd.DataFrame(prows)
    if len(pooled):
        pooled['fdr_pass'],pooled['q']=bh_fdr(pooled['p'].values)
    return res,pooled


if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument('--ks', type=str, default='3.0', help='comma list of k thresholds')
    a=ap.parse_args()
    pd.set_option('display.width',220); pd.set_option('display.max_rows',300)
    ks=[float(x) for x in a.ks.split(',')]
    for k in ks:
        res,pooled=run(jump_k=k)
        print(f'\n################ k={k} ################')
        print(f'=== PER-ASSET (k={k}) n={len(res)} | FDR survivors={int(res.fdr_pass.sum())} | rawp<0.01={int((res.p<0.01).sum())} rawp<0.05={int((res.p<0.05).sum())} | expected_at_0.05={0.05*len(res):.0f} ===')
        print('Top 18 by p:'); print(res.sort_values('p').head(18).to_string(index=False))
        print(f'=== POOLED (Stouffer across assets, FFT circ-shift null) [k={k}] ===')
        print(pooled.sort_values('p').to_string(index=False))
        print('POOLED FDR survivors:',int(pooled.fdr_pass.sum()))
        res.to_csv(f'/tmp/tail_fast_perasset_k{k}.csv',index=False)
        pooled.to_csv(f'/tmp/tail_fast_pooled_k{k}.csv',index=False)
    print('FINISHED')
