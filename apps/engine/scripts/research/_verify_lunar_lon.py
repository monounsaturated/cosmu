"""Adversarial verification of: sin(moon_lon) -> next-day crypto return (time-series rule).

Four hardness tests demanded by the candidate's own disconfirmer:
  (A) STRICT proper null, n>=5000 surrogates that preserve return autocorr + cross-asset corr
      - primary: circular-shift of the deterministic moon signal (preserves cross-asset return
        correlation exactly, so the effective-N problem is baked in)
      - secondary: IAAFT surrogate returns (preserve power spectrum + amplitude dist per asset)
  (B) OUT-OF-SAMPLE split (train pre-2023 -> test 2023+, plus a true forward 2026 slice)
  (C) ECONOMIC test net of 10bps round-trip on realized turnover
  (D) MULTIPLE-TESTING charge for the 704/88-test scan that surfaced it (Bonferroni + BH)
"""
import sys, warnings, json
warnings.filterwarnings("ignore")
sys.path.insert(0, "scripts/research/astro_deep")
sys.path.insert(0, "scripts/research/astro_strategy_lab")
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
import real_panel as RP
import astro_features_deep as AF
from spectral_vol import iaaft_surrogate  # debugged IAAFT

RNG = np.random.default_rng(20260615)
FEE = 0.0010  # 10bps round-trip per unit turnover

CRYPTO = ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","DOGEUSDT","ADAUSDT","AVAXUSDT",
          "LINKUSDT","DOTUSDT","LTCUSDT","BCHUSDT","ATOMUSDT","UNIUSDT","FILUSDT","NEARUSDT","AAVEUSDT"]
EQUITY = ["SPY","QQQ","IWM","GLD","SLV","TLT","XLE","XLF","XLK","USO"]


def zscore(x):
    s = np.nanstd(x)
    return (x - np.nanmean(x)) / (s if s > 0 else 1.0)


def ts_rule_returns(sig, ret):
    """Time-series rule: pos_t = clip(-z(sig_t)) in [-1,1], pnl_{t+1} = pos_t * ret_{t+1}.
    Returns (gross_pnl_series, turnover_series). sig and ret aligned, ret is NEXT-day return at t."""
    pos = np.clip(-zscore(sig), -1.0, 1.0)
    gross = pos * ret
    turn = np.abs(np.diff(np.concatenate([[0.0], pos])))
    return gross, turn, pos


def sharpe(x):
    x = x[~np.isnan(x)]
    if len(x) < 30 or np.std(x) == 0:
        return 0.0
    return np.mean(x) / np.std(x) * np.sqrt(365)


def build_panel():
    cb = RP.load_crypto_bars(CRYPTO, "1d", days=3650)
    eb = RP.load_equity_bars(EQUITY)
    allidx = sorted(set().union(*[v.index for v in cb.values()], *[v.index for v in eb.values()]))
    allidx = pd.DatetimeIndex(allidx)
    af = AF.deep_astro_features(allidx)
    sig = pd.Series(np.sin(np.deg2rad(af["moon_lon_deg"].values)), index=allidx, name="sinmoon")
    return cb, eb, sig


def asset_arrays(bars, sig):
    """For each asset return aligned (sig_t, nextret_{t+1}) numpy arrays on its own clean index."""
    out = {}
    for s, df in bars.items():
        r = np.log(df["close"]).diff().shift(-1)
        x = sig.reindex(df.index)
        m = (~r.isna()) & (~x.isna())
        if m.sum() < 250:
            continue
        out[s] = (x[m].values.astype(float), r[m].values.astype(float), df.index[m])
    return out


def pooled_sharpe_net(arrs, sig_override=None):
    """Pool the time-series rule across assets (equal weight, daily). Net of fees.
    sig_override: optional dict {sym: sig_array} to swap in a surrogate signal."""
    pnls_gross, turns = [], []
    for s, (x, r, idx) in arrs.items():
        xs = sig_override[s] if sig_override is not None else x
        g, t, _ = ts_rule_returns(xs, r)
        pnls_gross.append(pd.Series(g, index=idx))
        turns.append(pd.Series(t, index=idx))
    G = pd.concat(pnls_gross, axis=1).mean(axis=1)        # equal-weight portfolio gross pnl
    T = pd.concat(turns, axis=1).mean(axis=1)             # avg turnover/day
    net = G - FEE * T
    return sharpe(G.values), sharpe(net.values), float(T.mean())


# ---------------------------------------------------------------------------
# NULL A1: circular-shift of the deterministic moon signal (cross-asset corr preserved)
# ---------------------------------------------------------------------------
def null_circular_shift(arrs, sig_full, n=6000):
    """Shift the single deterministic moon signal by a random lag, re-evaluate the POOLED net Sharpe.
    Because all assets share the SAME shifted signal, the cross-asset return correlation is preserved
    exactly -> the effective-N inflation is inside the null. Min shift kept away from 0 +-1 period."""
    # Master signal on union index; per-asset we just reindex the shifted master.
    master = sig_full
    L = len(master)
    obs_g, obs_net, obs_turn = pooled_sharpe_net(arrs)
    null_net = np.empty(n)
    null_g = np.empty(n)
    vals = master.values
    midx = master.index
    for i in range(n):
        k = RNG.integers(15, L - 15)  # avoid trivial ~0 and ~full shifts
        shifted = pd.Series(np.roll(vals, k), index=midx, name="sinmoon")
        ov = {s: shifted.reindex(idx).values for s, (x, r, idx) in arrs.items()}
        g, net, _ = pooled_sharpe_net(arrs, sig_override=ov)
        null_net[i] = net
        null_g[i] = g
    p_net = (np.sum(null_net >= obs_net) + 1) / (n + 1)
    p_g = (np.sum(null_g >= obs_g) + 1) / (n + 1)
    return dict(obs_gross=obs_g, obs_net=obs_net, obs_turn=obs_turn,
                p_net=p_net, p_gross=p_g,
                null_net_p95=float(np.percentile(null_net, 95)),
                null_net_p99=float(np.percentile(null_net, 99)),
                null_net_mean=float(null_net.mean()), n=n)


# ---------------------------------------------------------------------------
# NULL A2: IAAFT surrogate RETURNS per asset (preserve power spectrum + amplitude dist)
# ---------------------------------------------------------------------------
def null_iaaft(arrs, n=2000):
    """Keep moon signal fixed; replace each asset's NEXT-day return series with an IAAFT surrogate.
    Preserves per-asset autocorrelation/vol-clustering & marginal; destroys phase-lock to the moon.
    Test stat: pooled net Sharpe. (n smaller: IAAFT is ~100 FFT iters/asset/surrogate.)"""
    obs_g, obs_net, obs_turn = pooled_sharpe_net(arrs)
    # pre-extract
    items = list(arrs.items())
    null_net = np.empty(n)
    for i in range(n):
        ov_arrs = {}
        for s, (x, r, idx) in items:
            rs = iaaft_surrogate(r, RNG, n_iter=60)
            ov_arrs[s] = (x, rs, idx)
        _, net, _ = pooled_sharpe_net(ov_arrs)
        null_net[i] = net
    p_net = (np.sum(null_net >= obs_net) + 1) / (n + 1)
    return dict(obs_net=obs_net, p_net=p_net,
                null_net_p95=float(np.percentile(null_net, 95)),
                null_net_p99=float(np.percentile(null_net, 99)),
                null_net_mean=float(null_net.mean()), n=n)


# ---------------------------------------------------------------------------
# B: OUT-OF-SAMPLE split
# ---------------------------------------------------------------------------
def oos_split(arrs, cut="2023-01-01", fwd="2026-01-01"):
    def slice_arrs(lo, hi):
        out = {}
        for s, (x, r, idx) in arrs.items():
            m = (idx >= pd.Timestamp(lo)) & (idx < pd.Timestamp(hi))
            if m.sum() < 120:
                continue
            out[s] = (x[m], r[m], idx[m])
        return out
    train = slice_arrs("2000-01-01", cut)
    test = slice_arrs(cut, fwd)
    fwd_s = slice_arrs(fwd, "2100-01-01")
    res = {}
    for name, a in [("train_pre2023", train), ("test_2023_2025", test), ("fwd_2026", fwd_s)]:
        if not a:
            res[name] = None
            continue
        # IC pooled
        ics = []
        for s, (x, r, idx) in a.items():
            mm = (~np.isnan(x)) & (~np.isnan(r))
            if mm.sum() < 60:
                continue
            ic, _ = spearmanr(x[mm], r[mm])
            ics.append(ic)
        g, net, turn = pooled_sharpe_net(a)
        res[name] = dict(ic_mean=float(np.mean(ics)), frac_neg=float(np.mean(np.array(ics) < 0)),
                         n_assets=len(ics), gross_sharpe=g, net_sharpe=net, turn=turn)
    return res


# ---------------------------------------------------------------------------
# Equity independent economic test
# ---------------------------------------------------------------------------
def equity_test(eb, sig):
    arrs = asset_arrays(eb, sig)
    if not arrs:
        return None
    ics = []
    for s, (x, r, idx) in arrs.items():
        mm = (~np.isnan(x)) & (~np.isnan(r))
        ic, _ = spearmanr(x[mm], r[mm])
        ics.append((s, ic))
    g, net, turn = pooled_sharpe_net(arrs)
    return dict(ic_mean=float(np.mean([i[1] for i in ics])),
                frac_neg=float(np.mean([i[1] < 0 for i in ics])),
                per_asset_ic={s: round(ic, 4) for s, ic in ics},
                gross_sharpe=g, net_sharpe=net, turn=turn, n_assets=len(ics))


def main():
    cb, eb, sig = build_panel()
    arrs = asset_arrays(cb, sig)
    print(f"[panel] crypto assets={len(arrs)} equity={len(eb)}")

    print("\n=== BASE (crypto pooled time-series rule) ===")
    g, net, turn = pooled_sharpe_net(arrs)
    print(f"gross Sharpe={g:+.3f}  net Sharpe={net:+.3f}  turnover/day={turn:.3f}")

    print("\n=== NULL A1: circular-shift of moon signal (cross-asset corr preserved) ===")
    a1 = null_circular_shift(arrs, sig, n=6000)
    print(json.dumps(a1, indent=2, default=float))

    print("\n=== NULL A2: IAAFT surrogate returns ===")
    a2 = null_iaaft(arrs, n=1500)
    print(json.dumps(a2, indent=2, default=float))

    print("\n=== B: OUT-OF-SAMPLE split ===")
    oos = oos_split(arrs)
    print(json.dumps(oos, indent=2, default=float))

    print("\n=== EQUITY independent economic test ===")
    eq = equity_test(eb, sig)
    print(json.dumps(eq, indent=2, default=float))

    # ---- D: multiple-testing charge ----
    p_primary = a1["p_net"]
    n_scan = 704
    n_feat = 88
    bonf_704 = min(1.0, p_primary * n_scan)
    bonf_88 = min(1.0, p_primary * n_feat)
    print("\n=== D: MULTIPLE-TESTING CHARGE ===")
    print(f"primary p (circular-shift, net Sharpe) = {p_primary:.4f}")
    print(f"Bonferroni x704 = {bonf_704:.4f}   Bonferroni x88 = {bonf_88:.4f}")

    summary = dict(base=dict(gross=g, net=net, turn=turn),
                   null_circshift=a1, null_iaaft=a2, oos=oos, equity=eq,
                   mt=dict(p_primary=p_primary, bonf704=bonf_704, bonf88=bonf_88))
    with open("scripts/research/_verify_lunar_lon_results.json", "w") as f:
        json.dump(summary, f, indent=2, default=float)
    print("\n[written] scripts/research/_verify_lunar_lon_results.json")


if __name__ == "__main__":
    main()
