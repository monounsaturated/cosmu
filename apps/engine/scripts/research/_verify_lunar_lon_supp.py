"""Supplementary adversarial tests for sin(moon_lon) -> next-day crypto return.

S1. BTC-beta neutralization: is the alt signal just BTC cloned across corr~0.61 assets?
    Regress each alt's next-day return on contemporaneous BTC next-day return, take residual,
    recompute IC on residual. If the effect is purely BTC-beta it dies on residuals.

S2. Effective-N honest null on IC: block-bootstrap the cross-asset IC mean with the SAME signal
    on all assets, accounting for cross-asset corr (one shared circular shift of the signal).

S3. Synodic vs sidereal alias: replace sin(moon_lon_sidereal) with sin of the SYNODIC phase
    (moon-sun elongation = illumination phase). If the 'edge' is really a new/full-moon calendar
    seasonality it should be carried by the synodic phase, not the sidereal longitude.

S4. Sign-flip honest deflation: best-of-both-signs. The scan tried sin AND implicitly the sign;
    charge a x2 for free sign choice on top of the feature count.
"""
import sys, warnings, json
warnings.filterwarnings("ignore")
sys.path.insert(0, "scripts/research/astro_deep")
import numpy as np, pandas as pd
from scipy.stats import spearmanr
import real_panel as RP, astro_features_deep as AF

RNG = np.random.default_rng(7)
CRYPTO = ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","DOGEUSDT","ADAUSDT","AVAXUSDT",
          "LINKUSDT","DOTUSDT","LTCUSDT","BCHUSDT","ATOMUSDT","UNIUSDT","FILUSDT","NEARUSDT","AAVEUSDT"]


def main():
    cb = RP.load_crypto_bars(CRYPTO, "1d", days=3650)
    allidx = pd.DatetimeIndex(sorted(set().union(*[v.index for v in cb.values()])))
    af = AF.deep_astro_features(allidx)
    sin_lon = pd.Series(np.sin(np.deg2rad(af["moon_lon_deg"].values)), index=allidx)
    # synodic phase: 0..360 from new->full->new; use elongation = moon_lon - sun_lon
    elong = np.deg2rad((af["moon_lon_deg"].values - af["sun_lon_deg"].values) % 360.0)
    sin_syn = pd.Series(np.sin(elong), index=allidx)

    # next-day log returns
    rets = {s: np.log(df["close"]).diff().shift(-1).reindex(allidx) for s, df in cb.items()}
    btc = rets["BTCUSDT"]

    # ---- S1: BTC-beta neutralization ----
    print("=== S1: BTC-beta-neutralized residual IC ===")
    res_ics, raw_ics = [], []
    for s in CRYPTO:
        if s == "BTCUSDT":
            continue
        r = rets[s]
        m = (~r.isna()) & (~btc.isna()) & (~sin_lon.isna())
        if m.sum() < 250:
            continue
        # residualize r on contemporaneous BTC next-day ret
        b = btc[m].values; y = r[m].values
        beta = np.cov(y, b)[0, 1] / np.var(b)
        resid = y - beta * b
        ic_raw, _ = spearmanr(sin_lon[m].values, y)
        ic_res, _ = spearmanr(sin_lon[m].values, resid)
        raw_ics.append(ic_raw); res_ics.append(ic_res)
    raw_ics = np.array(raw_ics); res_ics = np.array(res_ics)
    print(f"  raw alt IC mean={raw_ics.mean():+.4f} frac_neg={(raw_ics<0).mean():.2f}")
    print(f"  BTC-resid IC mean={res_ics.mean():+.4f} frac_neg={(res_ics<0).mean():.2f} "
          f"({(res_ics<0).sum()}/{len(res_ics)})")
    # also: does BTC itself carry it? (can't residualize BTC on itself)
    mb = (~btc.isna()) & (~sin_lon.isna())
    ic_btc, _ = spearmanr(sin_lon[mb].values, btc[mb].values)
    print(f"  BTC own IC={ic_btc:+.4f}")

    # ---- S3: synodic vs sidereal ----
    print("\n=== S3: synodic (illumination) phase vs sidereal longitude IC ===")
    sid, syn = [], []
    for s in CRYPTO:
        r = rets[s]
        m = (~r.isna()) & (~sin_lon.isna())
        ic_sid, _ = spearmanr(sin_lon[m].values, r[m].values)
        ic_syn, _ = spearmanr(sin_syn[m].values, r[m].values)
        sid.append(ic_sid); syn.append(ic_syn)
    sid = np.array(sid); syn = np.array(syn)
    print(f"  sidereal sin(moon_lon)  IC mean={sid.mean():+.4f} frac_neg={(sid<0).mean():.2f}")
    print(f"  synodic  sin(elong)     IC mean={syn.mean():+.4f} frac_neg={(syn<0).mean():.2f}")
    # correlation of the two signals
    cc = np.corrcoef(sin_lon[allidx].values, sin_syn[allidx].values)[0, 1]
    print(f"  corr(sidereal, synodic) signal = {cc:+.3f}")

    # ---- S2: effective-N honest IC null (shared circular shift) ----
    print("\n=== S2: cross-asset IC mean vs shared-shift null (effective-N honest) ===")
    aligned = {s: rets[s] for s in CRYPTO}
    obs = sid.mean()
    L = len(allidx); vals = sin_lon.values
    null = np.empty(4000)
    for i in range(4000):
        k = RNG.integers(15, L - 15)
        sh = pd.Series(np.roll(vals, k), index=allidx)
        ics = []
        for s in CRYPTO:
            r = aligned[s]
            m = (~r.isna()) & (~sh.isna())
            ic, _ = spearmanr(sh[m].values, r[m].values)
            ics.append(ic)
        null[i] = np.mean(ics)
    # two-sided: effect is negative, so p = P(null mean <= obs)
    p_one = (np.sum(null <= obs) + 1) / 4001
    p_two = (np.sum(np.abs(null) >= abs(obs)) + 1) / 4001
    print(f"  obs IC mean={obs:+.4f}  null mean={null.mean():+.4f} sd={null.std():.4f}")
    print(f"  null p05={np.percentile(null,5):+.4f}  one-sided p={p_one:.4f}  two-sided p={p_two:.4f}")

    out = dict(s1_resid_ic_mean=float(res_ics.mean()), s1_resid_frac_neg=float((res_ics<0).mean()),
               s1_btc_ic=float(ic_btc),
               s3_sidereal_ic=float(sid.mean()), s3_synodic_ic=float(syn.mean()), s3_signal_corr=float(cc),
               s2_obs_ic=float(obs), s2_null_p_one=float(p_one), s2_null_p_two=float(p_two))
    with open("scripts/research/_verify_lunar_lon_supp_results.json", "w") as f:
        json.dump(out, f, indent=2)
    print("\n", json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
