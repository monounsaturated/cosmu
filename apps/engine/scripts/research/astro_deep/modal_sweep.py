#!/usr/bin/env python3
# intent: the EMBARRASSINGLY-PARALLEL stage of the honest astrology-vs-markets study — a LARGE
# label-permutation null + multi-asset/model sweep, fanned out one container per job on Modal.
#
# DESIGN: features are precomputed LOCALLY (deterministic ephemeris + calendar geometry — see
# astro_market_study.py) and shipped INTO each job as plain arrays, so the Modal image stays light:
# NO ephem, NO DB, NO network inside the container — just numpy/scipy/scikit-learn/lightgbm doing
# pure walk-forward CV + permutation null. Every job is READ-ONLY and deterministic given its seed.
#
# The CV is kept IDENTICAL to the local study (astro_market_study._cv_auc / _date_folds):
#   - expanding-window, date-respecting folds (test strictly later than train),
#   - HistGradientBoostingClassifier(max_depth=3, ...) — or a lightgbm variant when model=='lgbm',
#   - pooled OOS ROC-AUC over the test folds,
#   - p = (1 + #{null >= real}) / (1 + #null)  — the same one-sided permutation p-value.
# `_cv_auc_core` / `_perm_cv_core` are plain helpers (no Modal, no DB) so the local joblib fallback
# and the Modal container run the EXACT same compute.
#
# NO FABRICATION: this harness moves no money, writes nothing, fakes no data. The arrays it receives
# are the caller's responsibility to fill with REAL features/labels; the synthetic self-test below is
# clearly random noise used ONLY to prove the pipeline wiring end-to-end (it should score AUC≈0.5).

from __future__ import annotations

import numpy as np

# ── App + light image (numpy/scipy/scikit-learn/lightgbm/pandas only — NO ephem, NO DB) ───────────
import modal

app = modal.App("cosmu-astro-research")
image = modal.Image.debian_slim(python_version="3.12").pip_install(
    "numpy", "scipy", "scikit-learn", "lightgbm", "pandas"
)


# ── Shared pure-compute CV (identical local + Modal; no Modal/DB imports needed) ───────────────────


def _date_folds(
    dates: np.ndarray, n_splits: int = 5
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Expanding-window, date-respecting folds for a POOLED matrix (test strictly later than train).

    Identical to astro_market_study._date_folds: cut the unique sorted dates at quantiles 0.4..0.9,
    train on everything strictly before each cut, test on the next slab. Keeps any rows sharing a date
    on the SAME side of the split (no intra-day leakage when several assets are pooled).
    """
    uniq = np.unique(dates)
    cuts = np.quantile(np.arange(len(uniq)), np.linspace(0.4, 0.9, n_splits + 1)).astype(int)
    folds: list[tuple[np.ndarray, np.ndarray]] = []
    for a, b in zip(cuts[:-1], cuts[1:], strict=True):
        tr_end, te_end = uniq[a], uniq[min(b, len(uniq) - 1)]
        tr = np.where(dates < tr_end)[0]
        te = np.where((dates >= tr_end) & (dates < te_end))[0]
        if len(tr) > 200 and len(te) > 50:
            folds.append((tr, te))
    return folds


def _make_clf(model: str, seed: int):
    """The classifier under test. 'hgb' = HistGradientBoosting (study default); 'lgbm' = LightGBM twin.

    Both are depth-3 gradient-boosted trees with matched regularization so the model axis of the sweep
    compares implementations, not hyper-grids. Imports are LOCAL so this module imports with only numpy
    present (the heavy libs only need to exist inside the Modal container / the local fallback env).
    """
    if model == "lgbm":
        from lightgbm import LGBMClassifier

        return LGBMClassifier(
            max_depth=3,
            num_leaves=8,
            n_estimators=80,
            learning_rate=0.06,
            reg_lambda=1.0,
            min_child_samples=80,
            subsample=1.0,
            colsample_bytree=1.0,
            random_state=seed,
            n_jobs=1,
            verbose=-1,
        )
    from sklearn.ensemble import HistGradientBoostingClassifier

    return HistGradientBoostingClassifier(
        max_depth=3,
        max_iter=80,
        learning_rate=0.06,
        l2_regularization=1.0,
        min_samples_leaf=120,
        random_state=seed,
    )


def _informative_cols(X: np.ndarray) -> np.ndarray:
    """Indices of columns with >=2 distinct FINITE values. A constant / all-NaN / single-value feature carries
    NO information and crashes some sklearn HGB binners ('window shape cannot be larger than input array shape'
    — the binner's sliding-window midpoint over <2 distinct values). Dropping it is correct and version-safe;
    it uses no label, so there is no leakage."""
    keep = []
    for j in range(X.shape[1]):
        fin = X[:, j][np.isfinite(X[:, j])]
        if fin.size >= 2 and np.unique(fin).size >= 2:
            keep.append(j)
    return np.asarray(keep, dtype=int)


def _cv_auc_core(
    X: np.ndarray, y: np.ndarray, folds, model: str = "hgb", seed: int = 0
) -> float:
    """Pooled walk-forward out-of-sample ROC-AUC. Mirrors astro_market_study._cv_auc exactly."""
    from sklearn.metrics import roc_auc_score

    preds, truth = [], []
    for tr, te in folds:
        if len(np.unique(y[tr])) < 2:
            continue
        # PER-FOLD column selection: keep only features with >=2 distinct finite values IN THIS training window.
        # A real feature that only starts mid-history (funding 2023, social 2020) is all-NaN in the earliest
        # expanding fold → the sklearn HGB binner crashes ('window shape ...'); dropping it for that fold is both
        # the fix AND correct walk-forward practice (you can't train on a feature that has no data yet). Uses no
        # label and only the training slice, so there is no look-ahead.
        cols = _informative_cols(X[tr])
        if cols.size == 0:
            continue
        clf = _make_clf(model, seed)
        clf.fit(X[tr][:, cols], y[tr])
        preds.append(clf.predict_proba(X[te][:, cols])[:, 1])
        truth.append(y[te])
    if not truth:
        return float("nan")
    yt = np.concatenate(truth)
    if len(np.unique(yt)) < 2:
        return float("nan")
    return float(roc_auc_score(yt, np.concatenate(preds)))


def _perm_cv_core(payload: dict) -> dict:
    """The ONE pure-compute kernel both run_sweep_modal and run_sweep_local call (per job).

    payload keys:
      asset  : str          — label only (carried through to the result)
      group  : str          — feature-group label only (e.g. 'astro'|'calendar'|'all')
      model  : str          — 'hgb' (HistGradientBoosting) or 'lgbm' (LightGBM)
      X      : list[list]    — feature matrix, shape (n, d), REAL features (caller's responsibility)
      y      : list[int]     — binary labels, length n (e.g. fwd_return > 0)
      dates  : list[int]     — epoch-DAYS per row (for date-respecting folds); same length n
      n_perm : int           — number of label permutations for the null
      seed   : int           — master seed (fully determines real fit + the permutation draws)

    returns: {asset, group, model, auc, null_mean, null_p95, p, n, n_perm}
      where p = (1 + #{null >= real_auc}) / (1 + #finite-null) — one-sided permutation p-value.

    Pure, deterministic given (payload, seed). READ-ONLY: touches no DB, writes nothing.
    """
    import warnings

    # Inputs are plain numpy arrays (no column names) — silence sklearn's cosmetic
    # "X does not have valid feature names" notice; it does not affect the compute.
    warnings.filterwarnings("ignore", message="X does not have valid feature names")

    asset = payload.get("asset", "?")
    group = payload.get("group", "?")
    model = payload.get("model", "hgb")
    n_perm = int(payload.get("n_perm", 0))
    seed = int(payload.get("seed", 0))

    X = np.asarray(payload["X"], dtype=float)
    y = np.asarray(payload["y"], dtype=int)
    dates = np.asarray(payload["dates"])

    # Require a finite LABEL only; KEEP NaN in X (HistGradientBoosting / LightGBM both handle missing
    # values natively). Dropping rows with any NaN feature would gut the real/all groups (funding is NaN
    # pre-2023, social pre-2020) and silently disagree with the local path — never impute, never fabricate.
    ok = np.isfinite(y)
    X, y, dates = X[ok], y[ok], dates[ok]
    cols = _informative_cols(X)  # drop constant/all-NaN columns (version-safe; no leakage)
    X = X[:, cols] if cols.size else X[:, :0]

    base = dict(
        asset=asset, group=group, model=model,
        auc=float("nan"), null_mean=float("nan"), null_p95=float("nan"),
        p=float("nan"), n=int(len(y)), n_perm=0, n_feat=int(X.shape[1]),
    )

    folds = _date_folds(dates)
    if not folds or len(np.unique(y)) < 2 or X.shape[1] == 0:
        return base

    real = _cv_auc_core(X, y, folds, model=model, seed=seed)
    if not np.isfinite(real):
        return base

    # Deterministic permutation seeds derived from the master seed (reproducible null).
    rng = np.random.default_rng(seed)
    perm_seeds = rng.integers(0, 2**31 - 1, size=n_perm)
    null = []
    for s in perm_seeds:
        r = np.random.default_rng(int(s))
        v = _cv_auc_core(X, r.permutation(y), folds, model=model, seed=int(s) % 1000)
        if np.isfinite(v):
            null.append(v)
    null = np.asarray(null, dtype=float)

    if len(null):
        p = (1 + int(np.sum(null >= real))) / (1 + len(null))
        base.update(
            auc=float(real),
            null_mean=float(np.mean(null)),
            null_p95=float(np.quantile(null, 0.95)),
            p=float(p),
            n_perm=int(len(null)),
        )
    else:
        base.update(auc=float(real))
    return base


def _incr_cv_core(payload: dict) -> dict:
    """INCREMENTAL test kernel (shares _cv_auc_core). Does X_extra add OOS information ON TOP OF X_base?

    real = AUC([base|extra]); null = AUC([base | ROW-SHUFFLED extra]) — the base signal is preserved, only the
    extra block's information is destroyed. p<0.05 AND lift>0 ⇒ the extra block carries incremental signal.

    payload keys: added (label), horizon (label), model, Xb (n×db), Xe (n×de), y (n), dates (n), n_perm, seed.
    returns: {added, horizon, model, auc_base, auc_full, lift, null_mean, p, n, n_perm}. Pure, READ-ONLY, NaN-safe.
    """
    import warnings

    warnings.filterwarnings("ignore", message="X does not have valid feature names")
    added = payload.get("added", "?")
    horizon = int(payload.get("horizon", 0))
    model = payload.get("model", "hgb")
    n_perm = int(payload.get("n_perm", 0))
    seed = int(payload.get("seed", 0))
    Xb = np.asarray(payload["Xb"], dtype=float)
    Xe = np.asarray(payload["Xe"], dtype=float)
    y = np.asarray(payload["y"], dtype=int)
    dates = np.asarray(payload["dates"])
    ok = np.isfinite(y)  # keep NaN in features (trees handle it); require a finite label
    Xb, Xe, y, dates = Xb[ok], Xe[ok], y[ok], dates[ok]
    cb = _informative_cols(Xb); Xb = Xb[:, cb] if cb.size else Xb[:, :0]  # drop constant/all-NaN (version-safe)
    ce = _informative_cols(Xe); Xe = Xe[:, ce] if ce.size else Xe[:, :0]

    base = dict(added=added, horizon=horizon, model=model, auc_base=float("nan"),
                auc_full=float("nan"), lift=float("nan"), null_mean=float("nan"),
                p=float("nan"), n=int(len(y)), n_perm=0, n_base=int(Xb.shape[1]), n_extra=int(Xe.shape[1]))
    folds = _date_folds(dates)
    if not folds or len(np.unique(y)) < 2 or Xe.shape[1] == 0 or Xb.shape[1] == 0:
        return base
    auc_base = _cv_auc_core(Xb, y, folds, model=model, seed=seed)
    auc_full = _cv_auc_core(np.hstack([Xb, Xe]), y, folds, model=model, seed=seed)
    rng = np.random.default_rng(seed)
    perm_seeds = rng.integers(0, 2**31 - 1, size=n_perm)
    null = []
    for s in perm_seeds:
        r = np.random.default_rng(int(s))
        v = _cv_auc_core(np.hstack([Xb, Xe[r.permutation(len(Xe))]]), y, folds, model=model, seed=int(s) % 1000)
        if np.isfinite(v):
            null.append(v)
    null = np.asarray(null, dtype=float)
    if len(null) and np.isfinite(auc_full):
        p = (1 + int(np.sum(null >= auc_full))) / (1 + len(null))
        base.update(auc_base=float(auc_base), auc_full=float(auc_full), lift=float(auc_full - auc_base),
                    null_mean=float(np.mean(null)), p=float(p), n_perm=int(len(null)))
    return base


# ── Modal entrypoints: one container per job (read-only, scale-to-zero) ─────────────────────────────


@app.function(image=image, timeout=3600, cpu=8.0, memory=16384)
def perm_cv(payload: dict) -> dict:
    """Modal-side wrapper around the shared kernel. Pure compute, deterministic, READ-ONLY.

    payload = {asset, group, model, X (n×d float), y (n), dates (n epoch-days), n_perm, seed}
    returns  = {asset, group, model, auc, null_mean, null_p95, p, n, n_perm}
    """
    return _perm_cv_core(payload)


@app.function(image=image, timeout=3600, cpu=8.0, memory=16384)
def incr_cv(payload: dict) -> dict:
    """Modal-side wrapper around the incremental kernel. Pure compute, deterministic, READ-ONLY."""
    return _incr_cv_core(payload)


# ── Drivers ───────────────────────────────────────────────────────────────────────────────────────


def run_sweep_modal(jobs: list[dict]) -> list[dict]:
    """Fan out one ephemeral Modal container per job and collect the result dicts.

    Uses an ephemeral `app.run()` context (no deployment, scale-to-zero) so nothing is left running.
    Returns a list of {asset, group, model, auc, null_mean, null_p95, p, n, n_perm} — same shape as
    run_sweep_local. Order follows .map() (input order).
    """
    if not jobs:
        return []
    with app.run():
        return list(perm_cv.map(jobs))


def run_sweep_local(jobs: list[dict], n_jobs: int = -1) -> list[dict]:
    """Identical compute to run_sweep_modal, parallelized locally with joblib (Modal-unavailable fallback).

    Returns the SAME dict shape. Each job is independent → process-parallel is safe and deterministic.
    n_jobs is capped by the CALLER (e.g. 3) when the goal is to NOT saturate a small local machine.
    """
    if not jobs:
        return []
    from joblib import Parallel, delayed

    return list(
        Parallel(n_jobs=n_jobs, prefer="processes")(delayed(_perm_cv_core)(j) for j in jobs)
    )


def run_incr_modal(jobs: list[dict]) -> list[dict]:
    """Fan the INCREMENTAL-test jobs out to Modal (one container each, ephemeral, scale-to-zero)."""
    if not jobs:
        return []
    with app.run():
        return list(incr_cv.map(jobs))


def run_incr_local(jobs: list[dict], n_jobs: int = -1) -> list[dict]:
    """Local joblib fallback for the incremental jobs — identical compute, same dict shape."""
    if not jobs:
        return []
    from joblib import Parallel, delayed

    return list(Parallel(n_jobs=n_jobs, prefer="processes")(delayed(_incr_cv_core)(j) for j in jobs))


# ── Job-builder helper (convenience; the caller supplies REAL X/y/dates) ───────────────────────────


def make_job(
    asset: str,
    group: str,
    model: str,
    X,
    y,
    dates,
    n_perm: int,
    seed: int,
) -> dict:
    """Pack one sweep job into the JSON-serializable payload `perm_cv` / `_perm_cv_core` expect.

    X → list[list[float]], y → list[int], dates → list[int] (epoch-days). Everything that crosses the
    Modal boundary must be plain Python lists, not numpy arrays.
    """
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=int)
    dates = np.asarray(dates)
    # Normalize dates to integer epoch-days (datetime64 → ints; already-int passes through).
    if np.issubdtype(dates.dtype, np.datetime64):
        dates = dates.astype("datetime64[D]").astype(np.int64)
    return dict(
        asset=str(asset),
        group=str(group),
        model=str(model),
        X=X.tolist(),
        y=y.astype(int).tolist(),
        dates=np.asarray(dates).astype(np.int64).tolist(),
        n_perm=int(n_perm),
        seed=int(seed),
    )


def _epoch_days(dates) -> np.ndarray:
    d = np.asarray(dates)
    if np.issubdtype(d.dtype, np.datetime64):
        d = d.astype("datetime64[D]").astype(np.int64)
    return d.astype(np.int64)


def make_job_np(asset: str, group: str, model: str, X, y, dates, n_perm: int, seed: int) -> dict:
    """Like make_job but ships X as a float32 ndarray (Modal cloudpickle serializes raw buffers — far
    smaller/faster than list[list[float]] for big pooled matrices, so the local M2 just uploads and idles)."""
    return dict(asset=str(asset), group=str(group), model=str(model),
                X=np.ascontiguousarray(X, dtype=np.float32), y=np.asarray(y, dtype=np.int8),
                dates=_epoch_days(dates), n_perm=int(n_perm), seed=int(seed))


def make_incr_job(added: str, horizon: int, model: str, Xb, Xe, y, dates, n_perm: int, seed: int) -> dict:
    """Pack one incremental-test job (base block + extra block) as float32 arrays for Modal incr_cv."""
    return dict(added=str(added), horizon=int(horizon), model=str(model),
                Xb=np.ascontiguousarray(Xb, dtype=np.float32), Xe=np.ascontiguousarray(Xe, dtype=np.float32),
                y=np.asarray(y, dtype=np.int8), dates=_epoch_days(dates), n_perm=int(n_perm), seed=int(seed))


# ── Self-test: TINY synthetic noise, proves wiring only (expects AUC≈0.5) ─────────────────────────


def _synthetic_jobs(n_perm: int = 20) -> list[dict]:
    """Two trivial random jobs (X 500x5 noise, random y) — NOT real data, only pipeline proof.

    Dates are shaped like the REAL pooled matrix (several rows share each epoch-day, as when ~assets
    are pooled) so the date-respecting expanding folds actually form; the X/y are pure random noise,
    so the kernel should still score AUC≈0.5.
    """
    rng = np.random.default_rng(7)
    n = 600  # > the local study's ~min so the 0.4..0.9 expanding cuts clear the >200-train gate
    jobs = []
    for i, model in enumerate(("hgb", "lgbm")):
        X = rng.standard_normal((n, 5))
        y = rng.integers(0, 2, size=n)
        dates = np.arange(n)  # one row per epoch-day, strictly increasing
        jobs.append(
            make_job(
                asset=f"SYNTH{i}",
                group="all",
                model=model,
                X=X,
                y=y,
                dates=dates,
                n_perm=n_perm,
                seed=100 + i,
            )
        )
    return jobs


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Astro permutation-null sweep harness (Modal fan-out)")
    ap.add_argument(
        "--mode",
        choices=("local", "modal", "both"),
        default="local",
        help="local=joblib fallback · modal=ephemeral Modal fan-out · both=run+compare shapes",
    )
    ap.add_argument("--n-perm", type=int, default=20, help="permutations for the synthetic smoke jobs")
    args = ap.parse_args()

    jobs = _synthetic_jobs(n_perm=args.n_perm)
    print(f"[self-test] {len(jobs)} synthetic noise jobs (X 500x5, random y, n_perm={args.n_perm})")
    print("[self-test] EXPECT AUC≈0.5 and p not significant — this is random noise, only proving wiring.\n")

    if args.mode in ("local", "both"):
        loc = run_sweep_local(jobs, n_jobs=2)
        print("LOCAL (joblib) results:")
        for r in loc:
            print("  ", json.dumps(r))

    if args.mode in ("modal", "both"):
        mod = run_sweep_modal(jobs)
        print("\nMODAL (ephemeral fan-out) results:")
        for r in mod:
            print("  ", json.dumps(r))

    if args.mode == "both":
        same_shape = all(set(a) == set(b) for a, b in zip(loc, mod, strict=True))
        print(f"\n[self-test] local/modal dict shapes match: {same_shape}")
