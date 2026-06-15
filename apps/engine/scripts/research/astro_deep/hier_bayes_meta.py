# intent: WAVE-1 "hierarchical_bayes" weak-signal detector for pure-astro vs markets.
#
# A weak COMMON astro effect can be invisible per-asset (drowned in idiosyncratic noise) yet
# detectable once POOLED across many assets with PARTIAL POOLING. We treat each asset's predictive
# IC for a given astro feature as a noisy estimate y_i ~ N(theta_i, s_i^2), theta_i ~ N(mu, tau^2),
# and estimate the shared mean mu (+ its CI) by closed-form DerSimonian-Laird random-effects
# meta-analysis. The physicist's question: is the POOLED mu distinguishable from 0 for ANY astro
# feature, beyond a null that PRESERVES the autocorrelation of returns?
#
# CARDINAL RULES honored:
#  * LIVE-HONEST: deterministic astro (knowable in advance) + raw real prices. No social/back-filled alt.
#  * PROPER NULL: circular block-shift of each asset's *return* series (exactly preserves its
#    autocorrelation / vol clustering) — NOT i.i.d. fake dates. We rebuild the ENTIRE pooled-mu
#    statistic on shifted returns, per feature, to get a null distribution of the pooled effect.
#  * EFFECT SIZE + null + p, multiple-testing aware (BH across all features), economic > statistical.
#  * NO p-hacking: we report whatever survives the hardest test; "nothing survives" is a valid result.
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "astro_strategy_lab"))

import astro_features_deep as AF  # noqa: E402
import real_panel as RP  # noqa: E402

# ── universe: crypto majors/mids/smalls + equity/ETF ──────────────────────────────────────────
CRYPTO = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT",
    "AVAXUSDT", "LINKUSDT", "DOTUSDT", "LTCUSDT", "BCHUSDT", "ATOMUSDT", "UNIUSDT",
    "FILUSDT", "NEARUSDT", "AAVEUSDT",
]
EQUITY = ["SPY", "QQQ", "IWM", "GLD", "SLV", "TLT", "XLE", "XLF", "XLK", "USO"]


def _norm_index_to_date(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse intraday-stamped equity bars to a clean midnight-UTC daily index."""
    out = df.copy()
    out.index = pd.DatetimeIndex(out.index).normalize()
    out = out[~out.index.duplicated(keep="last")]
    return out


def load_returns(min_days: int = 800) -> pd.DataFrame:
    """Return a wide DataFrame of next-DAY-ALIGNED daily log returns (one col per asset)."""
    cb = RP.load_crypto_bars(CRYPTO, "1d", days=3650)
    eb = RP.load_equity_bars(EQUITY)
    cols: dict[str, pd.Series] = {}
    for sym, df in {**cb, **eb}.items():
        if df is None or len(df) < min_days:
            continue
        df = _norm_index_to_date(df)
        close = df["close"].astype(float)
        ret = np.log(close).diff()
        ret = ret.replace([np.inf, -np.inf], np.nan).dropna()
        if len(ret) >= min_days:
            cols[sym] = ret
    wide = pd.DataFrame(cols).sort_index()
    return wide


def build_feature_matrix(index: pd.DatetimeIndex) -> pd.DataFrame:
    """108 deterministic astro cols, with CIRCULAR angles expanded to sin/cos and binaries kept.

    Categorical (sign/element/modality) are dropped — they are tested elsewhere (cross-sectional
    natal already done) and don't map to a single signed IC. We keep continuous, circular(sin/cos),
    and binary features: the set most amenable to a signed pooled-mean meta-analysis."""
    raw = AF.deep_astro_features(index)
    feats: dict[str, pd.Series] = {}
    for c in AF.CONTINUOUS_COLS:
        feats[c] = raw[c].astype(float)
    for c in AF.CIRCULAR_COLS:
        rad = np.deg2rad(raw[c].astype(float))
        feats[f"{c}__sin"] = np.sin(rad)
        feats[f"{c}__cos"] = np.cos(rad)
    for c in AF.BINARY_COLS:
        s = raw[c].astype(float)
        if s.nunique(dropna=True) > 1:  # drop degenerate (never-fires-in-window) binaries
            feats[c] = s
    fm = pd.DataFrame(feats, index=index)
    # drop any all-constant or all-NaN columns
    fm = fm.loc[:, fm.std(skipna=True) > 1e-12]
    return fm


def spearman_ic_and_se(x: np.ndarray, y: np.ndarray) -> tuple[float, float, int]:
    """Spearman rho between x_t and y (already next-day-aligned), with Fisher-z SE.

    Returns (rho, se_rho, n). SE on rho via the delta method on Fisher-z: se_z = 1/sqrt(n-3),
    se_rho ≈ (1-rho^2) * se_z. We meta-analyse on the Fisher-z scale (variance-stabilised) and
    map mu back to rho for reporting."""
    mask = np.isfinite(x) & np.isfinite(y)
    n = int(mask.sum())
    if n < 60:
        return np.nan, np.nan, n
    rho = stats.spearmanr(x[mask], y[mask]).statistic
    if not np.isfinite(rho):
        return np.nan, np.nan, n
    return float(rho), float(1.0 / np.sqrt(n - 3)), n  # se on FISHER-Z scale


def _rankdata_nan(a: np.ndarray) -> np.ndarray:
    """Average ranks of finite entries (NaN stays NaN). Vectorised Spearman building block."""
    out = np.full(a.shape, np.nan)
    m = np.isfinite(a)
    if m.sum() == 0:
        return out
    out[m] = stats.rankdata(a[m])
    return out


def spearman_from_raw(xraw: np.ndarray, yraw: np.ndarray) -> tuple[float, int]:
    """EXACT Spearman == Pearson on ranks, re-ranked on the JOINT finite support (matches scipy).

    xraw/yraw are the RAW (un-ranked) aligned values with NaNs. We mask to common support FIRST,
    then rank — identical to scipy.stats.spearmanr on that mask, including tie handling."""
    mask = np.isfinite(xraw) & np.isfinite(yraw)
    n = int(mask.sum())
    if n < 60:
        return np.nan, n
    a = stats.rankdata(xraw[mask])
    b = stats.rankdata(yraw[mask])
    a = a - a.mean()
    b = b - b.mean()
    da = np.sqrt(np.dot(a, a))
    db = np.sqrt(np.dot(b, b))
    if da <= 0 or db <= 0:
        return np.nan, n
    return float(np.dot(a, b) / (da * db)), n


def fisher_z(r: float) -> float:
    r = float(np.clip(r, -0.999999, 0.999999))
    return float(np.arctanh(r))


def inv_fisher_z(z: float) -> float:
    return float(np.tanh(z))


def dersimonian_laird(y: np.ndarray, v: np.ndarray) -> dict:
    """Closed-form DerSimonian-Laird random-effects meta-analysis on effects y with variances v.

    y_i are per-asset Fisher-z ICs, v_i = se_z^2. Returns pooled mean mu, its SE, tau^2 (between-
    asset variance), Q heterogeneity, and the random-effects z-stat mu/se(mu)."""
    k = len(y)
    w = 1.0 / v
    mu_fixed = np.sum(w * y) / np.sum(w)
    Q = float(np.sum(w * (y - mu_fixed) ** 2))
    c = float(np.sum(w) - np.sum(w**2) / np.sum(w))
    tau2 = max(0.0, (Q - (k - 1)) / c) if c > 0 else 0.0
    w_re = 1.0 / (v + tau2)
    mu_re = float(np.sum(w_re * y) / np.sum(w_re))
    se_re = float(np.sqrt(1.0 / np.sum(w_re)))
    z_re = mu_re / se_re if se_re > 0 else 0.0
    return {
        "mu_z": mu_re, "se_z": se_re, "z_stat": z_re, "tau2": tau2,
        "Q": Q, "k": k, "mu_rho": inv_fisher_z(mu_re),
        "ci_lo_rho": inv_fisher_z(mu_re - 1.96 * se_re),
        "ci_hi_rho": inv_fisher_z(mu_re + 1.96 * se_re),
    }


def pooled_mu_from_raw(
    feat_lag: np.ndarray, ret_next: list[np.ndarray]
) -> dict | None:
    """Pool per-asset Spearman ICs (feature_t vs return_{t+1}) with DL random effects.

    `feat_lag`  = feature RAW values at positions 0..T-2 (feature_t, aligned to return t+1).
    `ret_next`  = list of each asset's RAW next-day return array (positions 1..T-1), with NaNs.
    Each pair is re-ranked on its joint finite support -> EXACT scipy Spearman, then Fisher-z pooled."""
    ys, vs = [], []
    for rr in ret_next:
        rho, n = spearman_from_raw(feat_lag, rr)
        if not np.isfinite(rho) or n < 60:
            continue
        ys.append(fisher_z(rho))
        vs.append(1.0 / (n - 3))
    if len(ys) < 8:
        return None
    return dersimonian_laird(np.asarray(ys), np.asarray(vs))


def dersimonian_laird_raw(y: np.ndarray, v: np.ndarray) -> dict:
    """DL random-effects on a RAW (already interpretable) effect scale — no Fisher-z mapping.

    Used for event-premium effects measured directly in log-return units. Returns pooled mean mu,
    its SE, a 95% CI, tau^2, Q and the random-effects z-stat."""
    k = len(y)
    w = 1.0 / v
    mu_fixed = np.sum(w * y) / np.sum(w)
    Q = float(np.sum(w * (y - mu_fixed) ** 2))
    c = float(np.sum(w) - np.sum(w**2) / np.sum(w))
    tau2 = max(0.0, (Q - (k - 1)) / c) if c > 0 else 0.0
    w_re = 1.0 / (v + tau2)
    mu = float(np.sum(w_re * y) / np.sum(w_re))
    se = float(np.sqrt(1.0 / np.sum(w_re)))
    z = mu / se if se > 0 else 0.0
    return {"mu": mu, "se": se, "z_stat": z, "tau2": tau2, "Q": Q, "k": k,
            "ci_lo": mu - 1.96 * se, "ci_hi": mu + 1.96 * se}


def pooled_mu_for_feature(
    feat: np.ndarray, rets: dict[str, np.ndarray], next_idx: dict[str, np.ndarray]
) -> dict | None:
    """Reference (slow) path kept for the timing-sanity check; main() uses the ranked fast path."""
    ys, vs = [], []
    for _sym, r in rets.items():
        rho, se_z, n = spearman_ic_and_se(feat[:-1], r[1:])
        if not np.isfinite(rho) or not np.isfinite(se_z):
            continue
        ys.append(fisher_z(rho))
        vs.append(se_z**2)
    if len(ys) < 8:
        return None
    return dersimonian_laird(np.asarray(ys), np.asarray(vs))


def circular_shift_returns(rets: dict[str, np.ndarray], rng: np.random.Generator) -> dict[str, np.ndarray]:
    """PROPER NULL: independently circular-shift each asset's return series by a random lag.

    A circular shift exactly preserves every asset's autocorrelation function and volatility
    clustering (it's a rotation of the same series) while destroying any genuine astro→return
    phase alignment. Each asset gets its OWN random lag so we don't preserve a spurious common
    calendar coincidence either."""
    out = {}
    for sym, r in rets.items():
        n = len(r)
        k = int(rng.integers(low=n // 20, high=n - n // 20))  # avoid trivial near-zero shifts
        out[sym] = np.roll(r, k)
    return out


def main(n_surr: int = 400, seed: int = 12345) -> None:
    rng = np.random.default_rng(seed)
    print("Loading real price panel ...", flush=True)
    wide = load_returns(min_days=800)
    print(f"  assets with >=800d returns: {wide.shape[1]} -> {list(wide.columns)}", flush=True)
    print(f"  union date range: {wide.index.min().date()} .. {wide.index.max().date()} "
          f"({wide.shape[0]} rows)", flush=True)

    fm = build_feature_matrix(wide.index)
    print(f"  astro feature columns (cont + circular sin/cos + binary): {fm.shape[1]}", flush=True)

    # Per-asset RAW return arrays on the union index (NaN where the asset has no bar that day).
    rets = {sym: wide[sym].to_numpy(dtype=float) for sym in wide.columns}
    syms = list(rets.keys())

    # ── feature_t -> aligns with return_{t+1}: drop the last feature position ──
    feat_cols = list(fm.columns)
    feat_lag = {c: fm[c].to_numpy(dtype=float)[:-1] for c in feat_cols}

    def ret_next_for(ret_arrays: dict[str, np.ndarray]) -> list[np.ndarray]:
        """Each asset's NEXT-day RAW return (positions 1..T-1)."""
        return [ret_arrays[s][1:] for s in syms]

    # ── OBSERVED pooled mu per feature ──────────────────────────────────────────────────────
    obs_ret_next = ret_next_for(rets)
    obs = {}
    for c in feat_cols:
        res = pooled_mu_from_raw(feat_lag[c], obs_ret_next)
        if res is not None:
            obs[c] = res
    print(f"  features with a valid pooled estimate: {len(obs)}", flush=True)

    # ── PROPER NULL: rebuild the full pooled-mu for EVERY feature under circular-shifted returns ──
    # For each surrogate we shift returns once and recompute pooled |z| for all features, then count
    # how often the surrogate pooled |z| >= observed |z| (per feature). Permutation p, autocorr-safe.
    obs_absz = {c: abs(obs[c]["z_stat"]) for c in obs}
    ge_count = {c: 0 for c in obs}
    null_max_absz = np.empty(n_surr)  # for a FAMILY-WISE null (max over features per surrogate)

    print(f"Running {n_surr} circular-shift surrogates (autocorrelation-preserving null) ...", flush=True)
    for s in range(n_surr):
        shifted = circular_shift_returns(rets, rng)
        sur_ret_next = ret_next_for(shifted)
        cur_max = 0.0
        for c in obs:
            res = pooled_mu_from_raw(feat_lag[c], sur_ret_next)
            az = abs(res["z_stat"]) if res is not None else 0.0
            if az >= obs_absz[c]:
                ge_count[c] += 1
            if az > cur_max:
                cur_max = az
        null_max_absz[s] = cur_max
        if (s + 1) % 50 == 0:
            print(f"  surrogate {s + 1}/{n_surr}", flush=True)

    # Per-feature permutation p (one-sided on |z|), +1 smoothing.
    rows = []
    for c in obs:
        p_perm = (ge_count[c] + 1) / (n_surr + 1)
        # family-wise p: how often the surrogate's MAX |z| over all features beats THIS feature's |z|
        p_fwe = (np.sum(null_max_absz >= obs_absz[c]) + 1) / (n_surr + 1)
        r = obs[c]
        rows.append({
            "feature": c, "k_assets": r["k"], "mu_rho": r["mu_rho"],
            "ci_lo_rho": r["ci_lo_rho"], "ci_hi_rho": r["ci_hi_rho"],
            "tau2": r["tau2"], "z_pool": r["z_stat"], "abs_z": abs(r["z_stat"]),
            "p_perm": p_perm, "p_fwe": p_fwe,
        })
    res_df = pd.DataFrame(rows).sort_values("p_perm").reset_index(drop=True)
    # persist immediately so a late display error can't lose the computed science
    res_df.to_csv(HERE / "_hier_bayes_meta_results.csv", index=False)

    # BH-FDR across all features on the permutation p.
    m = len(res_df)
    ranked = res_df.sort_values("p_perm").copy()
    ranked["rank"] = np.arange(1, m + 1)
    ranked["bh_thresh"] = ranked["rank"] / m * 0.05
    ranked["bh_pass"] = ranked["p_perm"] <= ranked["bh_thresh"]
    # step-up: a feature passes if any larger-rank p passes
    passing_ranks = ranked.loc[ranked["bh_pass"], "rank"]
    max_pass = int(passing_ranks.max()) if len(passing_ranks) else 0
    ranked["bh_survive"] = ranked["rank"] <= max_pass

    pd.set_option("display.width", 200, "display.max_columns", 20, "display.float_format",
                  lambda v: f"{v:.5f}")
    print("\n=== TOP 20 features by permutation p (autocorrelation-preserving null) ===")
    print(ranked.head(20)[
        ["feature", "k_assets", "mu_rho", "ci_lo_rho", "ci_hi_rho", "tau2",
         "z_pool", "p_perm", "p_fwe", "bh_survive"]
    ].to_string(index=False))

    n_bh = int(ranked["bh_survive"].sum())
    n_fwe = int((ranked["p_fwe"] <= 0.05).sum())
    print(f"\nFeatures tested: {m}")
    print(f"BH-FDR(0.05) survivors on permutation p: {n_bh}")
    print(f"Family-wise (maxT) p<=0.05 survivors: {n_fwe}")
    print(f"Smallest permutation p achievable with {n_surr} surrogates: {1/(n_surr+1):.5f}")

    # economic sanity for the single best, regardless of significance
    best = ranked.iloc[0]
    print(f"\nBest feature: {best['feature']}  pooled IC(rho)={best['mu_rho']:.5f} "
          f"[{best['ci_lo_rho']:.5f},{best['ci_hi_rho']:.5f}]  z={best['z_pool']:.3f} "
          f"p_perm={best['p_perm']:.5f} p_fwe={best['p_fwe']:.5f}")
    bps = abs(best["mu_rho"]) * 1e4 / 1.0  # crude: rho≈ correlation; |edge| in 'IC bps' terms
    print(f"  |pooled IC| ~ {abs(best['mu_rho']):.5f}  (a daily next-bar rank corr; "
          f"~10bps round-trip needs |IC| well above noise to be tradeable)")

    out_path = HERE / "_hier_bayes_meta_results.csv"
    ranked.to_csv(out_path, index=False)
    print(f"\nfull results -> {out_path}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--surr", type=int, default=400)
    ap.add_argument("--seed", type=int, default=12345)
    args = ap.parse_args()
    main(n_surr=args.surr, seed=args.seed)
