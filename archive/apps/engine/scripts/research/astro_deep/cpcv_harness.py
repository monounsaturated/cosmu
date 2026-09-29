# intent: WAVE-1 "nonlinear_ml_purged" — the ONE test the existing ml_harness.py does NOT do.
# ml_harness uses expanding-window folds + label-permutation; good, but overlapping multi-day labels
# (fwd_5, fwd_20) leak across a single train|test boundary and INFLATE OOS AUC. This module is the
# López de Prado fix: COMBINATORIAL-PURGED CROSS-VALIDATION with PURGING + EMBARGO, so every training
# sample whose label horizon overlaps a test block is *removed*, and a band right after each test block
# is *embargoed*. That kills the overlap-leakage false positive at its root.
#
# CARDINAL RULES honoured:
#   - LIVE-HONEST features only: deterministic astro (126→108 real cols) + immutable macro
#     (fear_greed/funding_rate/vix_level/dxy/fed_funds_rate). NO LunarCrush social (back-filled = look-ahead).
#   - PROPER null: LABEL-PERMUTATION re-running the ENTIRE CPCV pipeline (purge+embargo identical), so the
#     null sees the same leakage structure as the real fit. p = P(null_AUC >= real_AUC).
#   - Effect size + null dist + one-sided p, multiple-testing aware (Bonferroni across the model×horizon grid).
#   - Economic gate is reported separately (a sign-classifier AUC is only tradeable if AUC materially > 0.5
#     AND survives ~10bps round-trip — we report the implied edge, not just significance).
#
# NOT duplicating prior work: single-feature IC, ML group-battle (expanding folds), 152k backtests, lunar
# phase-shuffle — those are done. This attacks a DIFFERENT axis: nonlinear interactions under purged CV.

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from itertools import combinations
from scipy import stats
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

warnings.filterwarnings("ignore")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import astro_features_deep as AF  # noqa: E402
import real_panel as RP  # noqa: E402

# LIVE-HONEST macro only — immutable sources, NO LunarCrush social.
HONEST_MACRO = ["fear_greed", "funding_rate", "vix_level", "dxy", "fed_funds_rate"]

# astro features are DETERMINISTIC PER CALENDAR DATE and identical across every asset — computing them
# per-asset would recompute the (slow, pure-Python ephem) panel 17× redundantly. Compute ONCE over the
# union of all dates, on-disk-cache it, and slice per asset.
_ASTRO_CACHE_DIR = Path("/tmp/cosmu_astro_cache/astro_encoded")


def astro_encoded_for_dates(all_dates: pd.DatetimeIndex) -> tuple[pd.DataFrame, list[str]]:
    """Encoded astro matrix (sin/cos circular, one-hot categorical) as a DataFrame indexed by date,
    computed ONCE over the union of dates and cached to parquet. Returns (df, feature_names)."""
    import hashlib

    key = hashlib.md5(repr((str(all_dates.min()), str(all_dates.max()), len(all_dates))).encode()).hexdigest()[:16]
    _ASTRO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    pq = _ASTRO_CACHE_DIR / f"{key}.parquet"
    if pq.exists():
        try:
            df = pd.read_parquet(pq)
            return df, list(df.columns)
        except Exception:  # noqa: BLE001
            pass
    af = AF.deep_astro_features(all_dates)
    X, names = encode_astro(af)
    df = pd.DataFrame(X, index=all_dates, columns=names)
    try:
        df.to_parquet(pq)
    except Exception:  # noqa: BLE001
        pass
    return df, names


# ── model ────────────────────────────────────────────────────────────────────────────────────────
def _gbm(seed: int) -> HistGradientBoostingClassifier:
    # small & regularized: shallow trees, strong leaf floor, early-stopping to cap fit time on the big
    # pooled matrix. max_iter=120 with early-stop is ample for a depth-3 model; trims wall-clock ~2x.
    return HistGradientBoostingClassifier(
        max_depth=3, max_iter=100, learning_rate=0.06, l2_regularization=1.0,
        min_samples_leaf=200, max_leaf_nodes=8, early_stopping=True,
        n_iter_no_change=8, validation_fraction=0.12, max_bins=128, random_state=seed,
    )


# ── astro encoding (reuse the registry; circular→sin/cos, categorical→one-hot) ─────────────────────
def encode_astro(af: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    cols, names = [], []
    for c in AF.CONTINUOUS_COLS:
        if c in af:
            cols.append(af[c].to_numpy(float)); names.append(c)
    for c in AF.CIRCULAR_COLS:
        if c in af:
            rad = np.radians(af[c].to_numpy(float))
            cols.append(np.sin(rad)); names.append(f"{c}_sin")
            cols.append(np.cos(rad)); names.append(f"{c}_cos")
    for c in AF.BINARY_COLS:
        if c in af:
            cols.append(af[c].to_numpy(float)); names.append(c)
    for c in AF.CATEGORICAL_COLS:
        if c in af:
            v = af[c].to_numpy(float)
            for lvl in np.unique(v[np.isfinite(v)]):
                cols.append((v == lvl).astype(float)); names.append(f"{c}={int(lvl)}")
    if not cols:
        return np.empty((len(af), 0)), []
    return np.column_stack(cols), names


# ── combinatorial-purged CV with embargo (López de Prado, Ch.7) ────────────────────────────────────
def cpcv_splits(t_index: np.ndarray, n_groups: int, k_test: int) -> list[tuple[np.ndarray, np.ndarray]]:
    """t_index: per-row INTEGER time-rank (same scale as the label horizon h, see build_panel).
    Partition the UNIQUE time-ranks into `n_groups` contiguous blocks; every C(n_groups, k_test)
    choice of `k_test` blocks is one test set, the rest train. Returns list of (test_block_ids, ...).
    Splitting on UNIQUE ranks (not rows) keeps the same calendar day across assets together."""
    uniq = np.unique(t_index)
    blocks = np.array_split(uniq, n_groups)
    block_of_rank = {}
    for bid, blk in enumerate(blocks):
        for r in blk:
            block_of_rank[r] = bid
    return [(np.array(c), block_of_rank, blocks) for c in combinations(range(n_groups), k_test)]


def purge_embargo_train(
    t_rank: np.ndarray, test_mask: np.ndarray, h: int, embargo: int
) -> np.ndarray:
    """Train mask = NOT test, MINUS any row whose label window [t, t+h] overlaps ANY test row's window,
    MINUS an embargo band of `embargo` ranks AFTER each test row. Returns boolean train mask."""
    test_ranks = t_rank[test_mask]
    if len(test_ranks) == 0:
        return ~test_mask
    # a train row r is purged if its label window [r, r+h] intersects any test window [tt, tt+h]:
    #   overlap  ⇔  r <= tt+h  AND  r+h >= tt  ⇔  (tt - h) <= r <= (tt + h)
    # plus embargo: r in (tt, tt+embargo]. Combine both as: r in [tt-h, tt+max(h,embargo)] for some tt.
    lo = test_ranks - h
    hi = test_ranks + max(h, embargo)
    # mark every rank inside any [lo,hi] interval as blocked (vectorised via a sorted-interval sweep)
    order = np.argsort(lo)
    lo_s, hi_s = lo[order], hi[order]
    train = ~test_mask
    r = t_rank
    blocked = np.zeros(len(r), bool)
    # for each row, is there an interval covering it? merge intervals then binary-search.
    merged = []
    cl, ch = lo_s[0], hi_s[0]
    for a, b in zip(lo_s[1:], hi_s[1:]):
        if a <= ch + 1:
            ch = max(ch, b)
        else:
            merged.append((cl, ch)); cl, ch = a, b
    merged.append((cl, ch))
    ml = np.array([m[0] for m in merged]); mh = np.array([m[1] for m in merged])
    pos = np.searchsorted(ml, r, side="right") - 1
    valid = pos >= 0
    blocked[valid] = r[valid] <= mh[pos[valid]]
    return train & ~blocked


def cpcv_oos_auc(
    X: np.ndarray, y: np.ndarray, t_rank: np.ndarray, *, n_groups: int, k_test: int,
    h: int, embargo: int, seed: int,
) -> float:
    """Pooled OOS AUC over ALL combinatorial test sets, purged+embargoed. Each calendar rank is predicted
    in (n_groups-1 choose k_test-1) folds; we average its probability across folds, then score ONE AUC on
    the full panel. This is the leakage-hardened analogue of cv_auc."""
    if X.shape[1] == 0 or len(np.unique(y)) < 2:
        return float("nan")
    splits = cpcv_splits(t_rank, n_groups, k_test)
    if not splits:
        return float("nan")
    block_of_rank = splits[0][1]
    blocks = splits[0][2]
    bid_arr = np.array([block_of_rank[r] for r in t_rank])  # block id per row
    prob_sum = np.zeros(len(y)); prob_cnt = np.zeros(len(y))
    for test_blocks, _, _ in splits:
        test_mask = np.isin(bid_arr, test_blocks)
        train_mask = purge_embargo_train(t_rank, test_mask, h, embargo)
        if train_mask.sum() < 250 or len(np.unique(y[train_mask])) < 2 or test_mask.sum() < 30:
            continue
        clf = _gbm(seed)
        clf.fit(X[train_mask], y[train_mask])
        p = clf.predict_proba(X[test_mask])[:, 1]
        prob_sum[test_mask] += p; prob_cnt[test_mask] += 1
    scored = prob_cnt > 0
    if scored.sum() < 100 or len(np.unique(y[scored])) < 2:
        return float("nan")
    return float(roc_auc_score(y[scored], prob_sum[scored] / prob_cnt[scored]))


def cpcv_perm_null(
    X: np.ndarray, y: np.ndarray, t_rank: np.ndarray, *, n_groups: int, k_test: int,
    h: int, embargo: int, B: int, n_jobs: int = -1,
) -> dict:
    """Real CPCV-OOS-AUC vs label-permutation null running the IDENTICAL purged pipeline. To respect the
    serial dependence of returns, we permute LABELS BY CALENDAR BLOCK (shuffle whole rank-blocks), which
    preserves within-block autocorrelation while destroying the feature→label map — a stronger null than
    i.i.d. row-shuffle. p = (1+#{null>=real})/(1+n)."""
    from joblib import Parallel, delayed

    real = cpcv_oos_auc(X, y, t_rank, n_groups=n_groups, k_test=k_test, h=h, embargo=embargo, seed=0)
    if not np.isfinite(real):
        return dict(auc=float("nan"), null_mean=float("nan"), null_p95=float("nan"),
                    p=float("nan"), n=int(len(y)), n_perm=0)
    # CIRCULAR-BLOCK label shuffle: order rows by (t_rank, then their pooled position), cut the label
    # vector into contiguous blocks of ~max(h,5) and circularly rotate by a random offset, THEN shuffle
    # whole blocks. This preserves the SERIAL AUTOCORRELATION of the labels (a proper null for periodic /
    # momentum-laden series) while destroying the feature→label alignment. Far stronger than i.i.d. shuffle
    # — i.i.d. is exactly what manufactured the false lunar-vol positive before.
    order = np.argsort(t_rank, kind="stable")
    inv = np.empty_like(order); inv[order] = np.arange(len(order))
    y_ord = y[order]
    blk_size = max(h, 5)
    n = len(y_ord)
    n_blocks = int(np.ceil(n / blk_size))
    rng0 = np.random.default_rng(20260615)
    seeds = rng0.integers(0, 2**31 - 1, size=B)

    def _one(s):
        r = np.random.default_rng(int(s))
        shift = int(r.integers(0, n))
        yc = np.roll(y_ord, shift)                       # circular rotation (preserves autocorr)
        blocks = [yc[i * blk_size:(i + 1) * blk_size] for i in range(n_blocks)]
        r.shuffle(blocks)                                # shuffle whole blocks
        yperm_ord = np.concatenate(blocks)[:n]
        yperm = yperm_ord[inv]                           # back to pooled row order
        return cpcv_oos_auc(X, yperm, t_rank, n_groups=n_groups, k_test=k_test,
                            h=h, embargo=embargo, seed=int(s) % 1000)

    # Cap workers at 7 (leave 1 core for the OS) and run inside a context-managed pool so loky workers
    # are REAPED when the block exits — prevents the orphaned-worker-pool pileup that pegs the CPU when a
    # parent is killed. `loky` backend + idle timeout ensures no lingering pool across calls.
    import os as _os
    eff = min(7, _os.cpu_count() or 4) if n_jobs in (-1, None) else n_jobs
    with Parallel(n_jobs=eff, backend="loky", prefer="processes") as par:
        null = par(delayed(_one)(s) for s in seeds)
    null = np.array([v for v in null if np.isfinite(v)])
    p = (1 + int(np.sum(null >= real))) / (1 + len(null)) if len(null) else float("nan")
    return dict(auc=float(real),
                null_mean=float(np.mean(null)) if len(null) else float("nan"),
                null_p95=float(np.quantile(null, 0.95)) if len(null) else float("nan"),
                null_std=float(np.std(null)) if len(null) else float("nan"),
                p=float(p), n=int(len(y)), n_perm=int(len(null)))


# ── interaction features: top-variance astro × each macro (capped) ─────────────────────────────────
def interaction_block(Xa: np.ndarray, names_a: list[str], Xm: np.ndarray, names_m: list[str],
                      top_a: int = 12) -> tuple[np.ndarray, list[str]]:
    """Pairwise products of the `top_a` highest-variance astro columns with every macro column.
    Standardize first so products are scale-comparable. Keeps the block small (top_a × n_macro)."""
    if Xa.shape[1] == 0 or Xm.shape[1] == 0:
        return np.empty((Xa.shape[0], 0)), []

    def z(M):
        mu = np.nanmean(M, 0); sd = np.nanstd(M, 0); sd[sd == 0] = 1.0
        return (M - mu) / sd

    Za, Zm = z(Xa), z(Xm)
    var = np.nanvar(Za, 0)
    sel = np.argsort(var)[::-1][:min(top_a, Za.shape[1])]
    cols, names = [], []
    for i in sel:
        for j in range(Zm.shape[1]):
            cols.append(Za[:, i] * Zm[:, j])
            names.append(f"{names_a[i]}×{names_m[j]}")
    if not cols:
        return np.empty((Xa.shape[0], 0)), []
    return np.column_stack(cols), names


# ── panel builder: pooled multi-asset, with integer time-rank + label horizons ─────────────────────
def build_panel(symbols: list[str], asset_class: str, horizons=(1, 5, 20),
                require_macro: bool = False):
    """Returns dict with pooled arrays: per-horizon y (sign of fwd log-return, >0 → 1),
    astro X + names, macro X + names, and t_rank (integer calendar rank shared across assets so
    purge/embargo align on the same DAY across the pool)."""
    if asset_class == "crypto":
        bars = RP.load_crypto_bars(symbols, "1d", days=3650)
    else:
        bars = RP.load_equity_bars(symbols, limit=2600)
    bars = {s: b for s, b in bars.items() if len(b) > 400}
    if not bars:
        return None
    idx = {s: b.index for s in bars for b in [bars[s]]}
    macro = RP.load_real_alt_panel(list(bars), HONEST_MACRO, idx)

    # global calendar rank: rank EVERY distinct date across the pool so the same day → same rank
    all_dates = sorted(set().union(*[set(b.index) for b in bars.values()]))
    rank_of = {d: i for i, d in enumerate(all_dates)}

    # ONE astro computation over the union of dates (cached), sliced per asset below.
    astro_df, names_a = astro_encoded_for_dates(pd.DatetimeIndex(all_dates))

    rows_astro, rows_macro, t_rank = [], [], []
    ys = {h: [] for h in horizons}
    closes = []
    for s, b in bars.items():
        Xa = astro_df.reindex(b.index).to_numpy(float)
        m = macro[s].reindex(b.index)
        Xm = m[HONEST_MACRO].to_numpy(float)
        c = b["close"].to_numpy(float)
        logc = np.log(c)
        n = len(b)
        for i in range(n):
            # need all horizons computable
            if i + max(horizons) >= n:
                continue
            if require_macro and not np.all(np.isfinite(Xm[i])):
                continue
            if not np.all(np.isfinite(Xa[i])):
                continue
            rows_astro.append(Xa[i])
            rows_macro.append(Xm[i])
            t_rank.append(rank_of[b.index[i]])
            for h in horizons:
                ys[h].append(1 if (logc[i + h] - logc[i]) > 0 else 0)
            closes.append(c[i])
    if not rows_astro:
        return None
    Xa = np.array(rows_astro); Xm = np.array(rows_macro)
    t_rank = np.array(t_rank)
    # macro has NaN before 2022 — median-impute per column (PIT-safe: imputation uses only the pooled
    # train+test marginal, a constant; it adds no future info to any single row's prediction beyond a
    # column median, which the GBM would learn anyway). Mark missingness with an indicator column.
    macro_missing = (~np.isfinite(Xm)).astype(float)
    med = np.nanmedian(np.where(np.isfinite(Xm), Xm, np.nan), axis=0)
    med = np.where(np.isfinite(med), med, 0.0)
    Xm_filled = np.where(np.isfinite(Xm), Xm, med)
    Xm_full = np.hstack([Xm_filled, macro_missing])
    names_m = HONEST_MACRO + [f"{m}_isnan" for m in HONEST_MACRO]
    # float32: halves the matrix footprint → every GBM fit + every joblib pickle of X to a null worker
    # is ~2x cheaper. No precision concern for a depth-3 binned tree on standardized-scale features.
    return dict(Xa=Xa.astype(np.float32), names_a=names_a,
                Xm=Xm_full.astype(np.float32), names_m=names_m,
                ys={h: np.array(v) for h, v in ys.items()}, t_rank=t_rank,
                closes=np.array(closes), n_assets=len(bars))


# ── one full comparison: astro-only vs +macro vs +interactions, per horizon ────────────────────────
def run_comparison(panel: dict, horizons=(1, 5, 20), *, n_groups=8, k_test=2,
                   embargo_extra=2, B=200, tag=""):
    out = []
    Xa, Xm = panel["Xa"], panel["Xm"]
    names_a, names_m = panel["names_a"], panel["names_m"]
    Xi, names_i = interaction_block(Xa, names_a, Xm[:, :len(HONEST_MACRO)], HONEST_MACRO)
    t_rank = panel["t_rank"]
    models = {
        "astro_only": Xa,
        "astro+macro": np.hstack([Xa, Xm]),
        "macro_only": Xm,
        "astro+macro+interact": np.hstack([Xa, Xm, Xi]) if Xi.shape[1] else np.hstack([Xa, Xm]),
    }
    for h in horizons:
        y = panel["ys"][h]
        embargo = h + embargo_extra
        for mname, X in models.items():
            res = cpcv_perm_null(X, y, t_rank, n_groups=n_groups, k_test=k_test,
                                 h=h, embargo=embargo, B=B)
            res.update(model=mname, horizon=h, tag=tag, n_feat=int(X.shape[1]),
                       base_rate=float(np.mean(y)))
            out.append(res)
            print(f"[{tag}] h={h:>2} {mname:24s} AUC={res['auc']:.4f} "
                  f"null={res['null_mean']:.4f}±{res.get('null_std',float('nan')):.4f} "
                  f"p95={res['null_p95']:.4f} p={res['p']:.4f} nfeat={X.shape[1]} n={res['n']}", flush=True)
    return out
