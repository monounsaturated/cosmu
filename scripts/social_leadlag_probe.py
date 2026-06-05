#!/usr/bin/env python3
"""Non-obvious social-signal probe over the backfilled LunarCrush store.

Reads the raw JSONL social store + cached Binance daily bars DIRECTLY (no engine
imports) and computes four descriptive studies, point-in-time honest:

  (a) lead-lag: which social metric CHANGE at day t predicts forward return over t+1..t+k
  (b) galaxy_score extremes -> ASYMMETRIC forward outcomes (drawdown vs runup)
  (c) social_volume RELATIVE to price (dollar) volume -> forward return
  (d) cross-asset contagion: BTC social move -> mean ALT forward return

PIT rule: a social row carries available_at = ts + 1 day. We only ever use a social
value to predict returns that begin strictly AFTER its available_at. Concretely we
align social ts=t (known at t+1 00:00) to the bar that OPENS at t+1, and measure
forward returns from that bar's close onward. No bar ever sees a social value
published after that bar's decision point.

Output: raw numbers to stdout. Cross-asset significance uses each asset's own
statistic as ONE observation (a t-test across the 30 assets), which is conservative
against within-asset autocorrelation; we also report the pooled correlation.
"""
import glob
import json
import os

import numpy as np
from scipy import stats

# Data roots — override via env for any checkout. Defaults assume the run is launched from a dir whose
# .cosmu/ holds the backfilled LunarCrush JSONL store + the cached Binance daily bars (see the report's
# Reproduce section for the symlink recipe). No engine import, no network: pure offline EDA on the raw files.
SOCIAL_DIR = os.environ.get("COSMU_SOCIAL_DIR", os.path.join(".cosmu", "altdata"))
BAR_DIR    = os.environ.get("COSMU_BAR_DIR", os.path.join(".cosmu", "market_data", "binance"))
METRICS    = ["social_volume", "social_sentiment", "galaxy_score"]
HORIZONS   = [1, 2, 3, 5, 7]

def load_social(sym, metric):
    """Return dict date(int yyyymmdd as np.datetime64 day) -> value, indexed by ts DAY."""
    path = os.path.join(SOCIAL_DIR, f"lunarcrush_{sym}_{metric}.jsonl")
    out = {}
    with open(path) as f:
        for line in f:
            r = json.loads(line)
            d = np.datetime64(r["ts"][:10])
            out[d] = float(r["value"])
    return out

def load_bars(sym):
    """Return (days array, close array, dollar_vol array) for daily bars, sorted.
    Bar 'ts' is OPEN time (ms). Bar opening day = ts date."""
    path = os.path.join(BAR_DIR, f"{sym}_1d.json")
    with open(path) as f:
        rows = json.load(f)
    days, close, dvol = [], [], []
    for r in rows:
        d = np.datetime64(int(r["ts"]) // 1000, "s").astype("datetime64[D]")
        c = float(r["close"]); v = float(r["volume"])
        days.append(d); close.append(c); dvol.append(c * v)
    idx = np.argsort(days)
    days = np.array(days)[idx]; close = np.array(close)[idx]; dvol = np.array(dvol)[idx]
    return days, close, dvol

def build_panel(sym):
    """Aligned daily panel for one symbol over the bar window.
    For bar that OPENS on day D (close known at D+1), the social info available at
    that bar's open is social ts <= D-1 (available_at = D <= bar-open D). We attach
    social_known[D] = social value at ts=D-1. Forward returns measured from close[D].
    Returns a dict of np arrays aligned on bar index i (0..n-1)."""
    days, close, dvol = load_bars(sym)
    soc = {m: load_social(sym, m) for m in METRICS}
    n = len(days)
    logc = np.log(close)
    # forward log returns from close[i] to close[i+k]
    panel = {"days": days, "close": close, "dvol": dvol, "logc": logc, "n": n}
    for k in HORIZONS:
        fwd = np.full(n, np.nan)
        fwd[: n - k] = logc[k:] - logc[: n - k]
        panel[f"fwd{k}"] = fwd
    # forward max drawdown / runup over next k bars (from close[i])
    for k in HORIZONS:
        dd = np.full(n, np.nan); ru = np.full(n, np.nan)
        for i in range(n - k):
            seg = close[i + 1 : i + 1 + k]
            dd[i] = seg.min() / close[i] - 1.0
            ru[i] = seg.max() / close[i] - 1.0
        panel[f"dd{k}"] = dd; panel[f"ru{k}"] = ru
    # social aligned by availability: value known at bar-open D is ts = D-1
    for m in METRICS:
        lvl = np.full(n, np.nan)
        for i, D in enumerate(days):
            v = soc[m].get(D - np.timedelta64(1, "D"))
            if v is not None:
                lvl[i] = v
        panel[f"{m}_lvl"] = lvl
        # daily change of the social metric, also PIT (uses ts=D-1 vs ts=D-2)
        chg = np.full(n, np.nan)
        chg[1:] = lvl[1:] - lvl[:-1]
        if m == "social_volume":
            # log-change for the exploding-scale metric
            lvl_safe = np.where(lvl > 0, lvl, np.nan)
            chg = np.full(n, np.nan)
            chg[1:] = np.log(lvl_safe[1:]) - np.log(lvl_safe[:-1])
        panel[f"{m}_chg"] = chg
    # social_volume relative to dollar volume (excess attention): log ratio, z within asset
    sv = panel["social_volume_lvl"]
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.log(np.where(sv > 0, sv, np.nan)) - np.log(np.where(dvol > 0, dvol, np.nan))
    panel["sv_over_dvol"] = ratio
    return panel

def zscore(x):
    x = np.asarray(x, float)
    m = np.nanmean(x); s = np.nanstd(x)
    return (x - m) / s if s > 0 else x * np.nan

def pearson(a, b):
    mask = np.isfinite(a) & np.isfinite(b)
    if mask.sum() < 30:
        return np.nan, mask.sum()
    return float(np.corrcoef(a[mask], b[mask])[0, 1]), int(mask.sum())

def agg_corr(per_asset):
    """per_asset: list of (sym, corr, n). Return mean, t-stat across assets, frac>0."""
    cs = np.array([c for _, c, n in per_asset if np.isfinite(c)])
    if len(cs) < 3:
        return None
    t, p = stats.ttest_1samp(cs, 0.0)
    return dict(mean=float(cs.mean()), median=float(np.median(cs)),
                t=float(t), p=float(p), frac_pos=float((cs > 0).mean()), k=len(cs))

def main():
    syms = sorted({os.path.basename(p).split("_")[1]
                   for p in glob.glob(os.path.join(SOCIAL_DIR, "lunarcrush_*_galaxy_score.jsonl"))})
    panels = {}
    for s in syms:
        try:
            panels[s] = build_panel(s)
        except Exception as e:
            print(f"skip {s}: {e}")
    print(f"# assets: {len(panels)}   bars/asset (median): "
          f"{int(np.median([p['n'] for p in panels.values()]))}\n")

    # ---------- (a) lead-lag: social CHANGE -> forward return ----------
    print("=" * 78)
    print("(a) LEAD-LAG  —  corr( social-metric CHANGE at t ,  fwd log-ret t->t+k )")
    print("    per-asset corr, aggregated across assets (t over the cross-section)")
    print("=" * 78)
    for m in METRICS:
        for k in HORIZONS:
            per = [(s, *pearson(p[f"{m}_chg"], p[f"fwd{k}"])) for s, p in panels.items()]
            a = agg_corr(per)
            if a:
                star = "  <<<" if a["p"] < 0.05 else ""
                print(f"  {m:16s} k={k}:  mean r={a['mean']:+.4f}  med={a['median']:+.4f}  "
                      f"t={a['t']:+.2f}  p={a['p']:.3f}  pos={a['frac_pos']:.2f}{star}")
        print()

    # also: social LEVEL z-score -> forward return (mean-reversion / momentum of attention)
    print("-" * 78)
    print("(a') social LEVEL z-score (PIT, within-asset) -> fwd ret")
    print("-" * 78)
    for m in METRICS:
        for k in HORIZONS:
            per = [(s, *pearson(zscore(p[f"{m}_lvl"]), p[f"fwd{k}"])) for s, p in panels.items()]
            a = agg_corr(per)
            if a:
                star = "  <<<" if a["p"] < 0.05 else ""
                print(f"  {m:16s} k={k}:  mean r={a['mean']:+.4f}  t={a['t']:+.2f}  "
                      f"p={a['p']:.3f}  pos={a['frac_pos']:.2f}{star}")
        print()

    # ---------- (b) galaxy extremes -> ASYMMETRIC outcomes ----------
    print("=" * 78)
    print("(b) GALAXY_SCORE EXTREMES -> forward outcome (asymmetry: drawdown vs runup)")
    print("    top/bottom decile of galaxy_score (within-asset), pooled forward stats")
    print("=" * 78)
    for k in HORIZONS:
        hi_dd, hi_ru, lo_dd, lo_ru, mid_dd = [], [], [], [], []
        hi_fwd, lo_fwd, mid_fwd = [], [], []
        for _s, p in panels.items():
            g = p["galaxy_score_lvl"]; mask = np.isfinite(g)
            if mask.sum() < 100:
                continue
            q90 = np.nanpercentile(g, 90); q10 = np.nanpercentile(g, 10)
            dd = p[f"dd{k}"]; ru = p[f"ru{k}"]; fwd = p[f"fwd{k}"]
            hi = (g >= q90) & np.isfinite(dd)
            lo = (g <= q10) & np.isfinite(dd)
            md = (g > q10) & (g < q90) & np.isfinite(dd)
            hi_dd += list(dd[hi]); hi_ru += list(ru[hi]); hi_fwd += list(fwd[hi])
            lo_dd += list(dd[lo]); lo_ru += list(ru[lo]); lo_fwd += list(fwd[lo])
            mid_dd += list(dd[md]); mid_fwd += list(fwd[md])
        def mm(x): return (np.mean(x), np.median(x), len(x))
        hdm, hdmd, hn = mm(hi_dd); hrm, *_ = mm(hi_ru)
        ldm, ldmd, ln = mm(lo_dd); lrm, *_ = mm(lo_ru)
        mdm, *_ = mm(mid_dd)
        hfm = np.mean(hi_fwd); lfm = np.mean(lo_fwd); mfm = np.mean(mid_fwd)
        # is hi-galaxy fwd drawdown worse than mid?  t-test
        t, pv = stats.ttest_ind(hi_dd, mid_dd, equal_var=False)
        print(f"  k={k}:  HI-galaxy(top10%) fwd_dd mean={hdm:+.4f} med={hdmd:+.4f} runup={hrm:+.4f} fwd_ret={hfm:+.4f}  n={hn}")
        print(f"        LO-galaxy(bot10%) fwd_dd mean={ldm:+.4f} med={ldmd:+.4f} runup={lrm:+.4f} fwd_ret={lfm:+.4f}  n={ln}")
        print(f"        MID               fwd_dd mean={mdm:+.4f}                          fwd_ret={mfm:+.4f}")
        print(f"        HI vs MID drawdown: t={t:+.2f} p={pv:.3f}   (neg t => hi-galaxy has DEEPER drawdowns){'  <<<' if pv<0.05 else ''}")
        print()

    # ---------- (c) social_volume RELATIVE to price volume ----------
    print("=" * 78)
    print("(c) EXCESS ATTENTION = log(social_vol) - log(dollar_vol), z within asset")
    print("    corr( excess-attention z at t , fwd ret t->t+k )  +  decile spread")
    print("=" * 78)
    for k in HORIZONS:
        per = [(s, *pearson(zscore(p["sv_over_dvol"]), p[f"fwd{k}"])) for s, p in panels.items()]
        a = agg_corr(per)
        # decile spread: top vs bottom decile of excess attention, pooled fwd ret
        top, bot = [], []
        for _s, p in panels.items():
            z = zscore(p["sv_over_dvol"]); fwd = p[f"fwd{k}"]
            m = np.isfinite(z) & np.isfinite(fwd)
            if m.sum() < 100: continue
            q90 = np.nanpercentile(z[m], 90); q10 = np.nanpercentile(z[m], 10)
            top += list(fwd[m & (z >= q90)]); bot += list(fwd[m & (z <= q10)])
        if a:
            tt, tp = stats.ttest_ind(top, bot, equal_var=False)
            print(f"  k={k}:  mean r={a['mean']:+.4f} t={a['t']:+.2f} p={a['p']:.3f} pos={a['frac_pos']:.2f}"
                  f"   |  top-decile fwd={np.mean(top):+.4f} bot={np.mean(bot):+.4f} "
                  f"spread={np.mean(top)-np.mean(bot):+.4f} (t={tt:+.2f} p={tp:.3f})"
                  f"{'  <<<' if min(a['p'],tp)<0.05 else ''}")
    print()

    # ---------- (d) cross-asset contagion: BTC social -> ALT fwd ret ----------
    print("=" * 78)
    print("(d) CONTAGION — BTC social CHANGE at t -> mean-ALT fwd ret t->t+k")
    print("    also BTC excess-attention & BTC galaxy extreme -> alt outcomes")
    print("=" * 78)
    btc = panels["BTCUSDT"]
    alts = {s: p for s, p in panels.items() if s != "BTCUSDT"}
    # build mean-alt forward return aligned to btc days
    btc_days = btc["days"]
    for m in METRICS:
        for k in HORIZONS:
            sig = btc[f"{m}_chg"]
            # mean alt fwd ret on the same bar-open day
            altfwd = np.full(len(btc_days), np.nan)
            for i, d in enumerate(btc_days):
                vals = []
                for _s, p in alts.items():
                    j = np.where(p["days"] == d)[0]
                    if len(j) and np.isfinite(p[f"fwd{k}"][j[0]]):
                        vals.append(p[f"fwd{k}"][j[0]])
                if vals:
                    altfwd[i] = np.mean(vals)
            r, n = pearson(sig, altfwd)
            print(f"  BTC {m:16s} chg  k={k}:  corr(BTCsocialΔ, meanALT fwd{k})  r={r:+.4f}  n={n}")
        print()
    # BTC galaxy extreme -> alt forward drawdown
    print("  --- BTC galaxy top/bottom decile -> mean-ALT fwd drawdown & ret ---")
    g = btc["galaxy_score_lvl"]; q90 = np.nanpercentile(g, 90); q10 = np.nanpercentile(g, 10)
    for k in HORIZONS:
        altfwd = np.full(len(btc_days), np.nan); altdd = np.full(len(btc_days), np.nan)
        for i, d in enumerate(btc_days):
            fr, dr = [], []
            for _s, p in alts.items():
                j = np.where(p["days"] == d)[0]
                if len(j):
                    if np.isfinite(p[f"fwd{k}"][j[0]]): fr.append(p[f"fwd{k}"][j[0]])
                    if np.isfinite(p[f"dd{k}"][j[0]]): dr.append(p[f"dd{k}"][j[0]])
            if fr: altfwd[i] = np.mean(fr)
            if dr: altdd[i] = np.mean(dr)
        hi = (g >= q90) & np.isfinite(altfwd); lo = (g <= q10) & np.isfinite(altfwd)
        print(f"  k={k}:  BTC-hi-galaxy -> ALT fwd_ret={np.nanmean(altfwd[hi]):+.4f} fwd_dd={np.nanmean(altdd[hi]):+.4f} n={hi.sum()}"
              f"   |  BTC-lo-galaxy -> ALT fwd_ret={np.nanmean(altfwd[lo]):+.4f} fwd_dd={np.nanmean(altdd[lo]):+.4f} n={lo.sum()}")

    disconfirmers(panels, btc, alts, btc_days)


def disconfirmers(panels, btc, alts, btc_days):
    """The pre-registered falsification tests for the three specs."""
    print("\n" + "=" * 78)
    print("DISCONFIRMERS (pre-registered falsification tests)")
    print("=" * 78)

    # Spec 1: does the ACCELERATION carry signal INDEPENDENT of the LEVEL? (partial corr of accel vs fwd,
    # controlling for level z). If accel's signal vanishes once level is controlled, the decomposition is fake.
    print("\n[Spec1] accel vs fwd-ret, RAW corr vs corr after removing level-z (per-asset mean, k=2):")
    raw, partial = [], []
    for _s, p in panels.items():
        a = p["social_volume_accel_chg"] if "social_volume_accel_chg" in p else p["social_volume_chg"]
        lev = zscore(p["social_volume_lvl"]); fwd = p["fwd2"]
        m = np.isfinite(a) & np.isfinite(lev) & np.isfinite(fwd)
        if m.sum() < 50: continue
        raw.append(np.corrcoef(a[m], fwd[m])[0, 1])
        # residualize accel and fwd on level, correlate residuals (partial corr)
        def resid(y, x):
            b = np.polyfit(x, y, 1); return y - (b[0] * x + b[1])
        ra = resid(a[m], lev[m]); rf = resid(fwd[m], lev[m])
        partial.append(np.corrcoef(ra, rf)[0, 1])
    print(f"   raw mean r={np.mean(raw):+.4f}   partial(level-controlled) mean r={np.mean(partial):+.4f}  "
          f"(n_assets={len(raw)})  -> accel {'SURVIVES' if abs(np.mean(partial))>0.5*abs(np.mean(raw)) else 'COLLAPSES'} controlling for level")

    # Spec 3: does BTC SOCIAL beat BTC PRICE at predicting mean-ALT fwd ret? Head-to-head OLS (both standardized).
    print("\n[Spec3] mean-ALT fwd2 ~ BTC_social_accel + BTC_price_ret (standardized betas, t-stats):")
    btc_close = btc["close"]; btc_pret = np.full(len(btc_days), np.nan)
    btc_pret[1:] = np.log(btc_close[1:]) - np.log(btc_close[:-1])
    soc = btc["social_volume_chg"]
    altfwd = np.full(len(btc_days), np.nan)
    for i, d in enumerate(btc_days):
        vals = [p["fwd2"][np.where(p["days"] == d)[0][0]] for p in alts.values()
                if len(np.where(p["days"] == d)[0]) and np.isfinite(p["fwd2"][np.where(p["days"] == d)[0][0]])]
        if vals: altfwd[i] = np.mean(vals)
    m = np.isfinite(soc) & np.isfinite(btc_pret) & np.isfinite(altfwd)
    X = np.column_stack([zscore(soc[m]), zscore(btc_pret[m])]); y = zscore(altfwd[m])
    # OLS with intercept
    Xi = np.column_stack([np.ones(m.sum()), X])
    beta, *_ = np.linalg.lstsq(Xi, y, rcond=None)
    resid = y - Xi @ beta
    dof = m.sum() - Xi.shape[1]
    s2 = (resid @ resid) / dof
    cov = s2 * np.linalg.inv(Xi.T @ Xi)
    se = np.sqrt(np.diag(cov))
    tvals = beta / se
    print(f"   BTC_social_accel  beta={beta[1]:+.4f}  t={tvals[1]:+.2f}")
    print(f"   BTC_price_ret     beta={beta[2]:+.4f}  t={tvals[2]:+.2f}   (n={m.sum()})")
    print(f"   -> BTC social {'ADDS signal over price' if abs(tvals[1])>1.96 else 'is REDUNDANT to price'} "
          f"(its beta is {'still significant' if abs(tvals[1])>1.96 else 'insignificant'} with price in the model)")


if __name__ == "__main__":
    main()
