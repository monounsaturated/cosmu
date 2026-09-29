"""
DIMENSION: tail_extreme (wave 1)

Do astro configurations CLUSTER extreme events (jumps / crash onsets / vol spikes)
rather than shift mean returns?

PROPER NULL = circular-shift (block-rotation) of the astro-state mask relative to the
event series. This preserves BOTH (a) the periodic structure of the astro signal and
(b) the empirical autocorrelation/clustering of the event series. An iid fake-date null
would manufacture false positives (as it did last time). Circular shift is the gold-
standard surrogate for "is this alignment between two autocorrelated series real or a
coincidence of phase".

Statistic per (asset, event-type, astro-mask): odds-ratio of P(event | astro-active)
vs P(event | astro-inactive), and the raw lift. Null distribution from N circular shifts
of the astro mask. One-sided p (we look for ENRICHMENT in the astro-active state, the
direction a fat-tail effect would take). Pooled across assets via Stouffer / Fisher and
a pooled-OR circular-shift null. BH-FDR across the whole family.
"""
import sys, json, math
sys.path.insert(0, 'scripts/research/astro_deep')
sys.path.insert(0, 'scripts/research/astro_strategy_lab')

import numpy as np
import pandas as pd
import astro_features_deep as AF
import real_panel as RP

RNG = np.random.default_rng(20260615)
N_SHIFT = 5000          # circular-shift surrogates
MIN_SHIFT = 14          # avoid trivially-small rotations (keep them de-correlated)

CRYPTO = ['BTCUSDT','ETHUSDT','BNBUSDT','SOLUSDT','XRPUSDT','DOGEUSDT','ADAUSDT',
          'AVAXUSDT','LINKUSDT','DOTUSDT','LTCUSDT','BCHUSDT','ATOMUSDT','UNIUSDT',
          'FILUSDT','NEARUSDT','AAVEUSDT']
EQUITY = ['SPY','QQQ','IWM','GLD','SLV','TLT','XLE','XLF','XLK','USO']


# ---------------------------------------------------------------- event defs
def daily_close(df):
    s = df['close'].copy()
    s.index = pd.to_datetime(s.index).normalize()
    s = s[~s.index.duplicated(keep='last')].sort_index()
    return s

def log_ret(close):
    return np.log(close).diff()

def event_jump(close, win=60, k=3.0):
    """|standardized return| > k, using a TRAILING (causal) rolling std (no look-ahead)."""
    r = log_ret(close)
    mu = r.rolling(win, min_periods=20).mean().shift(1)
    sd = r.rolling(win, min_periods=20).std().shift(1)
    z = (r - mu) / sd
    return (z.abs() > k).astype(float), z

def event_crash_onset(close, win=60, k=3.0):
    """Onset of a DOWN jump: standardized return < -k (the first bar of a crash)."""
    r = log_ret(close)
    mu = r.rolling(win, min_periods=20).mean().shift(1)
    sd = r.rolling(win, min_periods=20).std().shift(1)
    z = (r - mu) / sd
    return (z < -k).astype(float), z

def event_vol_spike(close, win=30, k=3.0):
    """Spike in realized vol: today's |ret| jumps vs trailing typical |ret| (causal)."""
    r = log_ret(close).abs()
    mu = r.rolling(win, min_periods=15).mean().shift(1)
    sd = r.rolling(win, min_periods=15).std().shift(1)
    z = (r - mu) / sd
    return (z > k).astype(float), z


# ---------------------------------------------------------------- astro masks
def build_masks(idx):
    """Return dict name -> boolean mask aligned to idx. Each mask flags an 'astro-active'
    state with reasonable prior prevalence (5-35%)."""
    a = AF.deep_astro_features(idx)
    age = a['moon_synodic_age'].values            # 0..1 fraction of synodic cycle
    illum = a['moon_illum_frac'].values
    masks = {}
    # lunar phase windows (each ~ +/- a few days around the marked phase)
    masks['new_moon_window']  = (age < 0.06) | (age > 0.94)          # ~ +/-1.8d around new
    masks['full_moon_window'] = (np.abs(age - 0.5) < 0.06)           # ~ +/-1.8d around full
    masks['syzygy_window']    = masks['new_moon_window'] | masks['full_moon_window']
    masks['quarter_window']   = (np.abs(age-0.25)<0.05) | (np.abs(age-0.75)<0.05)
    masks['low_illum']        = illum < 0.10
    masks['high_illum']       = illum > 0.90
    # eclipse proximity
    masks['eclipse_window']   = a['eclipse_window'].values > 0.5
    masks['near_eclipse_7d']  = a['days_to_next_eclipse'].values < 7.0
    # hard aspects (squares+oppositions) elevated
    ha = a['hard_aspect_count'].values
    masks['hard_aspect_hi']   = ha >= np.quantile(ha, 0.80)
    conj = a['aspect_conjunction_count'].values
    masks['conj_hi']          = conj >= np.quantile(conj, 0.80)
    # lunar declination extreme (lunstandstill-ish): |decl| high
    md = np.abs(a['moon_decl_deg'].values)
    masks['moon_decl_extreme']= md >= np.quantile(md, 0.85)
    # mercury retrograde (folklore favorite)
    masks['mercury_retro']    = a['mercury_retrograde'].values > 0.5
    # any planet retro count high
    retro_cols=[c for c in a.columns if c.endswith('_retrograde')]
    rc = a[retro_cols].sum(axis=1).values
    masks['many_retro']       = rc >= np.quantile(rc, 0.80)
    # fast moon (perigee-ish speed) extreme
    ms = a['moon_speed_deg'].values
    masks['moon_fast']        = ms >= np.quantile(ms, 0.85)
    return {k: v.astype(bool) for k,v in masks.items()}


# ---------------------------------------------------------------- statistics
def odds_ratio(event, mask):
    """2x2 OR with Haldane-Anscombe 0.5 correction. event,mask are 0/1 arrays."""
    a = np.sum((mask==1)&(event==1)) + 0.5   # active & event
    b = np.sum((mask==1)&(event==0)) + 0.5   # active & no-event
    c = np.sum((mask==0)&(event==1)) + 0.5   # inactive & event
    d = np.sum((mask==0)&(event==0)) + 0.5
    return (a*d)/(b*c)

def lift(event, mask):
    """P(event|active)/P(event|inactive)."""
    mask = mask.astype(bool)
    pa = event[mask].mean() if mask.sum()>0 else np.nan
    pi = event[~mask].mean() if (~mask).sum()>0 else np.nan
    if pi==0 or np.isnan(pi) or np.isnan(pa): return np.nan
    return pa/pi

def circ_shift_null(event, mask, stat_fn, n=N_SHIFT, min_shift=MIN_SHIFT):
    """Circular-shift the MASK; recompute stat. event series untouched (preserves its
    clustering). Returns observed, null array, one-sided p (enrichment)."""
    T = len(event)
    obs = stat_fn(event, mask)
    null = np.empty(n)
    shifts = RNG.integers(min_shift, T-min_shift, size=n)
    for i,s in enumerate(shifts):
        null[i] = stat_fn(event, np.roll(mask, s))
    # one-sided p: how often null >= obs (enrichment direction)
    p = (np.sum(null >= obs) + 1) / (n + 1)
    return obs, null, p


def bh_fdr(pvals):
    p = np.asarray(pvals, float)
    m = len(p)
    order = np.argsort(p)
    ranked = p[order]
    crit = (np.arange(1, m+1)/m)
    passed = ranked <= crit*0.05
    out = np.zeros(m, bool)
    if passed.any():
        kmax = np.max(np.where(passed))
        thr = ranked[kmax]
        out[p <= thr] = True
    # also return q-values
    q = ranked * m / np.arange(1, m+1)
    q = np.minimum.accumulate(q[::-1])[::-1]
    qfull = np.empty(m); qfull[order]=q
    return out, qfull


# ---------------------------------------------------------------- run
def run():
    crypto = RP.load_crypto_bars(CRYPTO, '1d', days=3650)
    equity = RP.load_equity_bars(EQUITY)
    panels = {('crypto',k):v for k,v in crypto.items()}
    panels.update({('equity',k):v for k,v in equity.items()})

    event_defs = {
        'jump3':       lambda c: event_jump(c, 60, 3.0)[0],
        'crash_onset': lambda c: event_crash_onset(c, 60, 3.0)[0],
        'vol_spike':   lambda c: event_vol_spike(c, 30, 3.0)[0],
    }

    rows = []
    # for pooled test we need aligned mask/event per (mask,event) across assets
    pooled_store = {}  # (etype, mname) -> list of (event_arr, mask_arr)

    for (cls, sym), df in panels.items():
        close = daily_close(df)
        if len(close) < 400:
            continue
        idx = close.index
        masks = build_masks(idx)
        for etype, fn in event_defs.items():
            ev = fn(close)
            ev = ev.reindex(idx).fillna(0).values.astype(float)
            n_ev = int(ev.sum())
            if n_ev < 15:   # too few events to say anything
                continue
            for mname, mask in masks.items():
                mask = mask.astype(float)
                # require both cells populated
                if mask.sum() < 10 or (1-mask).sum() < 10: continue
                obs_or, null_or, p_or = circ_shift_null(ev, mask, odds_ratio)
                lf = lift(ev, mask)
                rows.append(dict(cls=cls, sym=sym, etype=etype, mask=mname,
                                 n_events=n_ev, prevalence=float(mask.mean()),
                                 OR=float(obs_or), lift=float(lf), p=float(p_or)))
                pooled_store.setdefault((etype,mname),[]).append((ev, mask))

    res = pd.DataFrame(rows)

    # -------- BH-FDR across the entire per-asset family
    passed, q = bh_fdr(res['p'].values)
    res['q'] = q
    res['fdr_pass'] = passed

    # -------- POOLED test: stack all assets for a given (etype,mask), one circular-shift
    # null where EACH asset's mask is independently rotated, then aggregate the OR via a
    # Mantel-Haenszel-style pooled odds ratio. This is the strong test.
    pooled_rows=[]
    for (etype,mname), lst in pooled_store.items():
        if len(lst) < 5: continue
        def pooled_or(_=None, shift=False):
            num=den=0.0
            for ev,mask in lst:
                m = mask
                num += np.sum((m==1)&(ev==1))*np.sum((m==0)&(ev==0))/len(ev)
                den += np.sum((m==1)&(ev==0))*np.sum((m==0)&(ev==1))/len(ev)
            return (num+1e-9)/(den+1e-9)
        obs = pooled_or()
        null = np.empty(N_SHIFT)
        for i in range(N_SHIFT):
            num=den=0.0
            for ev,mask in lst:
                T=len(ev); s=RNG.integers(MIN_SHIFT, T-MIN_SHIFT)
                m=np.roll(mask, s)
                num += np.sum((m==1)&(ev==1))*np.sum((m==0)&(ev==0))/T
                den += np.sum((m==1)&(ev==0))*np.sum((m==0)&(ev==1))/T
            null[i]=(num+1e-9)/(den+1e-9)
        p = (np.sum(null>=obs)+1)/(N_SHIFT+1)
        pooled_rows.append(dict(etype=etype, mask=mname, n_assets=len(lst),
                                pooled_OR=float(obs),
                                null_med=float(np.median(null)),
                                null_p975=float(np.quantile(null,0.975)),
                                p=float(p)))
    pooled = pd.DataFrame(pooled_rows)
    ppass, pq = bh_fdr(pooled['p'].values)
    pooled['q']=pq; pooled['fdr_pass']=ppass

    return res, pooled


if __name__ == '__main__':
    res, pooled = run()
    pd.set_option('display.width', 200)
    pd.set_option('display.max_rows', 200)
    print('=== PER-ASSET tests (n=%d) ===' % len(res))
    print('FDR survivors:', int(res['fdr_pass'].sum()))
    print('raw p<0.01 :', int((res['p']<0.01).sum()), ' raw p<0.05:', int((res['p']<0.05).sum()))
    print('\nTop 15 by p (per-asset):')
    print(res.sort_values('p').head(15).to_string(index=False))

    print('\n=== POOLED tests (Mantel-Haenszel OR, per-asset circular-shift null) ===')
    print(pooled.sort_values('p').to_string(index=False))
    print('\nPOOLED FDR survivors:', int(pooled['fdr_pass'].sum()))

    res.to_csv('/tmp/tail_extreme_perasset.csv', index=False)
    pooled.to_csv('/tmp/tail_extreme_pooled.csv', index=False)
    print('\nsaved /tmp/tail_extreme_perasset.csv  /tmp/tail_extreme_pooled.csv')
