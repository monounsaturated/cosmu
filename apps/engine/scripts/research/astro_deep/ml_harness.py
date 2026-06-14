# intent: the statistics + ML core for the deep astro study. Pure functions over arrays/frames — imports NONE of
# the sibling build modules, so it is independently testable. Everything here is built to make a FALSE positive
# hard: walk-forward OOS only, label-permutation nulls, an incremental-over-baseline test (does astro add anything
# to a model that already has the real signals?), BH-FDR across the whole grid, and a Deflated Sharpe Ratio that
# charges for the number of trials. No look-ahead, no in-sample scoring, no fabrication.

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

try:
    from lightgbm import LGBMClassifier  # noqa: F401

    _HAVE_LGBM = True
except Exception:  # noqa: BLE001
    _HAVE_LGBM = False


# ── feature encoding ────────────────────────────────────────────────────────────────────────────

def encode_matrix(
    df: pd.DataFrame,
    continuous: list[str],
    circular: list[str],
    binary: list[str],
    categorical: list[str],
) -> tuple[np.ndarray, list[str]]:
    """Build the model matrix: continuous raw · circular→(sin,cos) · binary raw · categorical→one-hot.
    Columns absent from `df` are skipped (so callers can pass a superset). Returns (X, feature_names)."""
    cols: list[np.ndarray] = []
    names: list[str] = []
    for c in continuous:
        if c in df:
            cols.append(df[c].to_numpy(float))
            names.append(c)
    for c in circular:
        if c in df:
            rad = np.radians(df[c].to_numpy(float))
            cols.append(np.sin(rad)); names.append(f"{c}_sin")
            cols.append(np.cos(rad)); names.append(f"{c}_cos")
    for c in binary:
        if c in df:
            cols.append(df[c].to_numpy(float))
            names.append(c)
    for c in categorical:
        if c in df:
            v = df[c].to_numpy(float)
            for lvl in np.unique(v[np.isfinite(v)]):
                cols.append((v == lvl).astype(float))
                names.append(f"{c}={int(lvl)}")
    if not cols:
        return np.empty((len(df), 0)), []
    return np.column_stack(cols), names


# ── walk-forward OOS AUC ─────────────────────────────────────────────────────────────────────────

def expanding_folds(dates: np.ndarray, n_splits: int = 5,
                    lo: float = 0.40, hi: float = 0.92) -> list[tuple[np.ndarray, np.ndarray]]:
    """Date-respecting expanding-window folds for a POOLED multi-asset matrix (test strictly later than train)."""
    uniq = np.unique(dates)
    if len(uniq) < n_splits + 2:
        return []
    cuts = np.quantile(np.arange(len(uniq)), np.linspace(lo, hi, n_splits + 1)).astype(int)
    folds = []
    for a, b in zip(cuts[:-1], cuts[1:], strict=True):
        tr_end, te_end = uniq[a], uniq[min(b, len(uniq) - 1)]
        tr = np.where(dates < tr_end)[0]
        te = np.where((dates >= tr_end) & (dates < te_end))[0]
        if len(tr) > 200 and len(te) > 50:
            folds.append((tr, te))
    return folds


def _model(kind: str, seed: int):
    if kind == "lgbm" and _HAVE_LGBM:
        from lightgbm import LGBMClassifier

        return LGBMClassifier(n_estimators=200, max_depth=3, num_leaves=15, learning_rate=0.05,
                              subsample=0.8, colsample_bytree=0.8, reg_lambda=1.0,
                              min_child_samples=80, random_state=seed, n_jobs=1, verbosity=-1)
    return HistGradientBoostingClassifier(max_depth=3, max_iter=150, learning_rate=0.05,
                                          l2_regularization=1.0, min_samples_leaf=80, random_state=seed)


def cv_auc(X: np.ndarray, y: np.ndarray, folds, kind: str = "hgb", seed: int = 0) -> float:
    """Pooled walk-forward out-of-sample ROC-AUC."""
    if X.shape[1] == 0:
        return float("nan")
    preds, truth = [], []
    for tr, te in folds:
        if len(np.unique(y[tr])) < 2:
            continue
        clf = _model(kind, seed)
        clf.fit(X[tr], y[tr])
        preds.append(clf.predict_proba(X[te])[:, 1])
        truth.append(y[te])
    if not truth:
        return float("nan")
    yt = np.concatenate(truth)
    if len(np.unique(yt)) < 2:
        return float("nan")
    return float(roc_auc_score(yt, np.concatenate(preds)))


def perm_null(X: np.ndarray, y: np.ndarray, dates: np.ndarray, *, B: int = 250,
              kind: str = "hgb", n_jobs: int = -1) -> dict:
    """Real OOS AUC vs a label-permutation null. p = P(null >= real). Beating chance needs p<0.05 AND auc>null_p95."""
    from joblib import Parallel, delayed

    folds = expanding_folds(dates)
    if not folds:
        return dict(auc=float("nan"), null_mean=float("nan"), null_p95=float("nan"), p=float("nan"), n=int(len(y)), n_perm=0)
    real = cv_auc(X, y, folds, kind)
    rng = np.random.default_rng(20260614)
    seeds = rng.integers(0, 2**31 - 1, size=B)

    def _one(s):
        r = np.random.default_rng(int(s))
        return cv_auc(X, r.permutation(y), folds, kind, seed=int(s) % 1000)

    null = Parallel(n_jobs=n_jobs, prefer="processes")(delayed(_one)(s) for s in seeds)
    null = np.array([v for v in null if np.isfinite(v)])
    p = (1 + int(np.sum(null >= real))) / (1 + len(null)) if len(null) else float("nan")
    return dict(auc=real, null_mean=float(np.mean(null)) if len(null) else float("nan"),
                null_p95=float(np.quantile(null, 0.95)) if len(null) else float("nan"),
                p=float(p), n=int(len(y)), n_perm=int(len(null)))


def incremental_test(X_base: np.ndarray, X_extra: np.ndarray, y: np.ndarray, dates: np.ndarray, *,
                     B: int = 250, kind: str = "hgb", n_jobs: int = -1) -> dict:
    """THE headline test. Does X_extra (astro) add OOS information ON TOP OF X_base (the real signals)?
    real = AUC([base|extra]); null = AUC([base | row-shuffled extra]) — base info preserved, extra info destroyed.
    p<0.05 AND lift>0 ⇒ astro carries incremental signal. Otherwise astro is redundant noise atop the real model."""
    from joblib import Parallel, delayed

    folds = expanding_folds(dates)
    if not folds or X_extra.shape[1] == 0:
        return dict(auc_base=float("nan"), auc_full=float("nan"), lift=float("nan"),
                    null_mean=float("nan"), p=float("nan"), n=int(len(y)), n_perm=0)
    auc_base = cv_auc(X_base, y, folds, kind)
    auc_full = cv_auc(np.hstack([X_base, X_extra]), y, folds, kind)
    rng = np.random.default_rng(20260615)
    seeds = rng.integers(0, 2**31 - 1, size=B)

    def _one(s):
        r = np.random.default_rng(int(s))
        Xe = X_extra[r.permutation(len(X_extra))]
        return cv_auc(np.hstack([X_base, Xe]), y, folds, kind, seed=int(s) % 1000)

    null = Parallel(n_jobs=n_jobs, prefer="processes")(delayed(_one)(s) for s in seeds)
    null = np.array([v for v in null if np.isfinite(v)])
    p = (1 + int(np.sum(null >= auc_full))) / (1 + len(null)) if len(null) else float("nan")
    return dict(auc_base=float(auc_base), auc_full=float(auc_full), lift=float(auc_full - auc_base),
                null_mean=float(np.mean(null)) if len(null) else float("nan"),
                p=float(p), n=int(len(y)), n_perm=int(len(null)))


# ── IC panel (single-feature, FDR + t>3) ─────────────────────────────────────────────────────────

def ic_panel(per_asset: dict[str, pd.DataFrame], scalar: list[str], categorical: list[str],
             horizons: tuple[int, ...], regimes=("all", "bull", "bear"), q: float = 0.05) -> pd.DataFrame:
    """Spearman IC (scalar) / Kruskal-Wallis (categorical) of feature_t vs forward return, stride-sampled for
    honest n, across asset×horizon×regime. BH-FDR over the WHOLE grid + the Harvey-Liu-Zhu |t|>3 bar."""
    from cosmu.master.fdr import benjamini_hochberg

    recs = []
    for asset, df in per_asset.items():
        for h in horizons:
            if f"fwd_{h}" not in df:
                continue
            y_all = df[f"fwd_{h}"].to_numpy(float)
            for regime in regimes:
                rmask = np.ones(len(df), bool) if regime == "all" else (df["regime"].to_numpy() == regime)
                idx = np.arange(0, len(df), max(1, h))
                for feat in scalar:
                    if feat not in df:
                        continue
                    x = df[feat].to_numpy(float)
                    m = rmask[idx] & np.isfinite(x[idx]) & np.isfinite(y_all[idx])
                    xi, yi = x[idx][m], y_all[idx][m]
                    if len(xi) < 40 or np.std(xi) == 0:
                        continue
                    ic, p = stats.spearmanr(xi, yi)
                    if not np.isfinite(p):
                        continue
                    recs.append(dict(asset=asset, feature=feat, kind="scalar", horizon=h, regime=regime,
                                     n=len(xi), ic=float(ic), p=float(p)))
                for feat in categorical:
                    if feat not in df:
                        continue
                    m = rmask[idx] & np.isfinite(y_all[idx])
                    g = df[feat].to_numpy(float)[idx][m]
                    yy = y_all[idx][m]
                    groups = [yy[g == lvl] for lvl in np.unique(g[np.isfinite(g)])]
                    groups = [grp for grp in groups if len(grp) >= 5]
                    if len(groups) < 2 or sum(len(grp) for grp in groups) < 40:
                        continue
                    Hk, p = stats.kruskal(*groups)
                    recs.append(dict(asset=asset, feature=feat, kind="categorical", horizon=h, regime=regime,
                                     n=int(sum(len(grp) for grp in groups)), ic=float("nan"), p=float(p)))
    res = pd.DataFrame(recs)
    if len(res):
        res["survives_fdr"] = benjamini_hochberg(res["p"].tolist(), q=q)
        with np.errstate(divide="ignore", invalid="ignore"):
            res["t"] = res["ic"] * np.sqrt((res["n"] - 2) / (1 - res["ic"] ** 2))
        res["survives_t3"] = res["t"].abs() > 3.0
    return res


# ── backtest a single-feature rule → Deflated Sharpe Ratio ────────────────────────────────────────

def deflated_sharpe(sr: float, n_trials: int, n_obs: int, skew: float, kurt: float) -> float:
    """Bailey & López de Prado Deflated Sharpe Ratio: P(true SR>0) after charging for `n_trials` selections.
    Returns a probability in [0,1]; a real edge wants DSR>0.95. SR/skew/kurt are on the per-bar return series."""
    if n_obs < 10 or not np.isfinite(sr):
        return float("nan")
    e = 0.5772156649
    # Expected max Sharpe under the null of `n_trials` independent strategies (variance of trial SRs ≈ 1/sqrt(n_obs)).
    z = stats.norm.ppf
    emax = (1 - e) * z(1 - 1.0 / max(n_trials, 2)) + e * z(1 - 1.0 / (max(n_trials, 2) * np.e))
    sr0 = (1.0 / np.sqrt(n_obs)) * emax  # expected max SR under the null (per-bar units)
    denom = np.sqrt(1 - skew * sr + (kurt - 1) / 4.0 * sr ** 2)
    if denom <= 0:
        return float("nan")
    return float(stats.norm.cdf((sr - sr0) * np.sqrt(n_obs - 1) / denom))


def backtest_long_short(close: np.ndarray, signal: np.ndarray, *, fee_bps: float = 10.0,
                        n_trials: int = 1) -> dict:
    """Trade tomorrow on today's signal sign (+1 long / -1 short / 0 flat), charge `fee_bps` per position change.
    Returns per-bar Sharpe (annualized √365), total net return, and the Deflated Sharpe probability."""
    ret = np.diff(np.log(close))
    pos = np.sign(signal[:-1])  # act on signal known at t, earn ret t→t+1
    pnl = pos * ret
    turn = np.abs(np.diff(np.concatenate([[0.0], pos])))
    pnl = pnl - turn * (fee_bps / 1e4)
    pnl = pnl[np.isfinite(pnl)]
    if len(pnl) < 30 or np.std(pnl) == 0:
        return dict(sharpe=float("nan"), net_return=float("nan"), dsr=float("nan"), n=int(len(pnl)))
    sr_bar = np.mean(pnl) / np.std(pnl)
    sharpe_ann = sr_bar * np.sqrt(365)
    dsr = deflated_sharpe(sr_bar, n_trials, len(pnl), float(stats.skew(pnl)), float(stats.kurtosis(pnl) + 3))
    return dict(sharpe=float(sharpe_ann), net_return=float(np.exp(np.sum(pnl)) - 1), dsr=float(dsr), n=int(len(pnl)))


if __name__ == "__main__":
    # Self-test on synthetic data: a pure-noise feature must NOT beat the null; a planted signal must.
    rng = np.random.default_rng(0)
    n = 4000
    dates = np.repeat(np.arange(n // 4), 4)
    Xnoise = rng.normal(size=(n, 8))
    y_rand = rng.integers(0, 2, n)
    folds = expanding_folds(dates)
    print("folds:", len(folds))
    print("noise→random  AUC:", round(cv_auc(Xnoise, y_rand, folds), 4), "(expect ≈0.50)")
    signal = rng.normal(size=(n, 3))
    y_real = (signal[:, 0] + 0.5 * signal[:, 1] + rng.normal(scale=0.5, size=n) > 0).astype(int)
    pn = perm_null(signal, y_real, dates, B=40, n_jobs=-1)
    print("planted signal perm_null:", {k: (round(v, 4) if isinstance(v, float) else v) for k, v in pn.items()})
    inc = incremental_test(signal, Xnoise, y_real, dates, B=40, n_jobs=-1)
    print("astro(noise) on top of real(signal):", {k: (round(v, 4) if isinstance(v, float) else v) for k, v in inc.items()})
    print("DSR of a t=2 strat over 1000 trials:", round(deflated_sharpe(2/np.sqrt(252), 1000, 252, 0.0, 3.0), 4))
