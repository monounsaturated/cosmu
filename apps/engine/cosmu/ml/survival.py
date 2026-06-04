# intent: the tabular SURVIVAL model — it predicts an edge-persistence score in [0,1] for each screen-survivor
# and uses it ONLY to ORDER which candidates get full validation first (prioritize scarce compute). It NEVER
# vetoes: ranking is a permutation, count-in == count-out, no candidate is ever dropped. The deterministic
# scorer/gate (master/scorer.py) remain the sole survival authority and are never reached from here. Cold-start:
# until >= min_train_labels labeled outcomes exist in the store, the model returns trained=False and a cheap
# deterministic heuristic ordering (a useless early model cannot strangle discovery). Past the threshold it
# trains on LABELED outcomes (passed-gate/survived vs killed) drawn from backtests joined to strategy_versions,
# and is OOS-checked (reports an AUROC-ish number). XGBoost/LightGBM are used if importable; otherwise a
# pure-Python deterministic logistic regression with the SAME interface keeps CI green with no lib installed.
# invariants: point-in-time (trains only on already-labeled past outcomes), deterministic for fixed inputs,
# no look-ahead, no magic numbers in the gate path, offline with zero required dependency.

from __future__ import annotations

import math
from dataclasses import dataclass

from cosmu.knowledge.store import Store
from cosmu.master.scorer import BacktestMetrics

# How many labeled outcomes must exist before the model trains + takes over ordering. Below this we order by a
# cheap deterministic heuristic so a thin/biased early model never gets to prioritize compute.
MIN_TRAIN_LABELS = 30

# The ordered feature vocabulary the model reads off a screen's BacktestMetrics. Stable order => stable vectors.
FEATURE_NAMES = (
    "sharpe_per_obs",
    "num_trades",
    "max_dd",
    "folds_positive_pct",
    "pbo",
    "skew",
    "kurt_excess",
    "n_obs",
    "regime_spread",
)


@dataclass(frozen=True)
class SurvivalFeatures:
    """The point-in-time feature row for one screen-survivor. All fields come from the cheap screen's metrics —
    nothing from the full validation we are about to order, so there is no leakage from the label into the rank."""

    sharpe_per_obs: float
    num_trades: float
    max_dd: float
    folds_positive_pct: float
    pbo: float
    skew: float
    kurt_excess: float  # kurtosis - 3 (excess; normal == 0)
    n_obs: float
    regime_spread: float  # how many distinct regimes the strategy made positive PnL in (regime breadth)

    def vector(self) -> list[float]:
        return [getattr(self, name) for name in FEATURE_NAMES]


@dataclass(frozen=True)
class SurvivalRanking:
    """One candidate's place in the validation queue. `score` is edge-persistence in [0,1]; higher = validate
    sooner. `trained` says whether a trained model produced the score or the cold-start heuristic did."""

    key: str
    score: float
    trained: bool


def features_from_metrics(metrics: BacktestMetrics) -> SurvivalFeatures:
    """Project a screen's BacktestMetrics onto the survival feature row. Reuses the scorer's own metric names
    (sharpe_per_obs, folds_positive_pct, pbo, skew/kurt, n_obs, regime spread) — composing, not duplicating."""
    regime_spread = float(sum(1 for pnl in metrics.regime_returns.values() if pnl > 0))
    return SurvivalFeatures(
        sharpe_per_obs=float(metrics.sharpe_per_obs),
        num_trades=float(metrics.num_trades),
        max_dd=float(metrics.max_drawdown),
        folds_positive_pct=float(metrics.folds_positive_pct),
        pbo=float(metrics.pbo),
        skew=float(metrics.skew),
        kurt_excess=float(metrics.kurtosis) - 3.0,
        n_obs=float(metrics.n_obs),
        regime_spread=regime_spread,
    )


# --------------------------------------------------------------------------- cold-start heuristic


def _heuristic_score(f: SurvivalFeatures) -> float:
    """A cheap, deterministic edge-persistence proxy for cold-start (before any model trains). Rewards
    per-obs Sharpe, fold breadth, regime breadth and trade count; penalizes overfit proxy (pbo) and drawdown.
    Squashed to [0,1]. This only ORDERS — it never vetoes — so a crude proxy is harmless: at worst compute is
    spent in a slightly different order while the deterministic gate still decides survival."""
    z = (
        1.2 * math.tanh(f.sharpe_per_obs * 8.0)
        + 0.8 * (f.folds_positive_pct - 0.5)
        + 0.5 * math.tanh(f.regime_spread - 1.0)
        + 0.3 * math.tanh(f.num_trades / 50.0)
        - 1.0 * (f.pbo - 0.5)
        - 0.6 * f.max_dd
    )
    return 1.0 / (1.0 + math.exp(-z))


# --------------------------------------------------------------------------- standardization + logistic


def _standardize(rows: list[list[float]]) -> tuple[list[float], list[float]]:
    """Per-feature mean and (non-zero) std so the pure-Python logistic trains stably. Deterministic."""
    n = len(rows)
    dim = len(rows[0])
    means = [sum(r[j] for r in rows) / n for j in range(dim)]
    stds: list[float] = []
    for j in range(dim):
        var = sum((r[j] - means[j]) ** 2 for r in rows) / n
        stds.append(math.sqrt(var) or 1.0)
    return means, stds


def _apply(vec: list[float], means: list[float], stds: list[float]) -> list[float]:
    return [(vec[j] - means[j]) / stds[j] for j in range(len(vec))]


def _train_logistic(rows: list[list[float]], labels: list[int], *, epochs: int = 400, lr: float = 0.1):
    """Pure-Python deterministic logistic regression (batch gradient descent, L2). Returns (weights, bias).
    Deterministic: fixed init (zeros), fixed iteration order, no randomness — same inputs => same model."""
    dim = len(rows[0])
    w = [0.0] * dim
    b = 0.0
    n = len(rows)
    lam = 1e-3
    for _ in range(epochs):
        gw = [0.0] * dim
        gb = 0.0
        for x, y in zip(rows, labels, strict=True):
            z = b + sum(w[j] * x[j] for j in range(dim))
            p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
            err = p - y
            for j in range(dim):
                gw[j] += err * x[j]
            gb += err
        for j in range(dim):
            w[j] -= lr * (gw[j] / n + lam * w[j])
        b -= lr * (gb / n)
    return w, b


def _auroc(scores: list[float], labels: list[int]) -> float:
    """Mann-Whitney AUROC. 0.5 == no skill. Returns 0.5 when one class is absent (cannot be estimated)."""
    pos = [s for s, y in zip(scores, labels, strict=True) if y == 1]
    neg = [s for s, y in zip(scores, labels, strict=True) if y == 0]
    if not pos or not neg:
        return 0.5
    wins = 0.0
    for p in pos:
        for q in neg:
            wins += 1.0 if p > q else 0.5 if p == q else 0.0
    return wins / (len(pos) * len(neg))


# --------------------------------------------------------------------------- the model


@dataclass
class SurvivalModel:
    """Trained-or-cold survival model. Construct via `load_survival_model(store)` so it trains on the store's
    labeled outcomes. The public surface is `rank(...)` (order a queue, never drop) and `score_features(...)`."""

    trained: bool = False
    backend: str = "heuristic"  # "xgboost" | "lightgbm" | "logistic" | "heuristic"
    n_labels: int = 0
    auroc: float | None = None  # OOS-ish AUROC on a held-out split when training happened, else None
    _means: list[float] | None = None
    _stds: list[float] | None = None
    _weights: list[float] | None = None
    _bias: float = 0.0
    _booster: object | None = None  # xgboost/lightgbm booster when that backend is used

    def score_features(self, f: SurvivalFeatures) -> float:
        """Edge-persistence score in [0,1] for one feature row. Falls back to the cold-start heuristic when
        untrained, so the interface is identical in both regimes (cold-start vs trained)."""
        if not self.trained:
            return _heuristic_score(f)
        vec = f.vector()
        if self._booster is not None:
            return self._score_booster(vec)
        assert self._means is not None and self._stds is not None and self._weights is not None
        x = _apply(vec, self._means, self._stds)
        z = self._bias + sum(self._weights[j] * x[j] for j in range(len(x)))
        return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))

    def _score_booster(self, vec: list[float]) -> float:
        booster = self._booster
        try:  # xgboost
            import xgboost as xgb  # type: ignore[import-not-found]

            if isinstance(booster, xgb.Booster):
                return float(booster.predict(xgb.DMatrix([vec]))[0])
        except ImportError:
            pass
        # lightgbm
        return float(booster.predict([vec])[0])  # type: ignore[union-attr]

    def rank(self, items: list[tuple[str, SurvivalFeatures]]) -> list[SurvivalRanking]:
        """ORDER the validation queue by edge-persistence, descending. This is a PERMUTATION ONLY — every
        input appears exactly once in the output (count-in == count-out); nothing is filtered or vetoed. Ties
        break on the original key so the ordering is fully deterministic."""
        scored = [
            SurvivalRanking(key=key, score=round(self.score_features(f), 6), trained=self.trained)
            for key, f in items
        ]
        scored.sort(key=lambda r: (-r.score, r.key))
        return scored


def load_survival_model(store: Store, *, min_train_labels: int = MIN_TRAIN_LABELS) -> SurvivalModel:
    """Build the model from the store's LABELED outcomes. Cold-start (< min_train_labels labels) returns an
    untrained model (trained=False) that orders by the cheap heuristic. Past the threshold it trains (XGBoost/
    LightGBM if importable, else pure-Python logistic), OOS-checks on a held-out split, and takes over ordering."""
    rows, labels = _labeled_outcomes(store)
    n = len(rows)
    backend_label = "logistic"
    if n < min_train_labels or len(set(labels)) < 2:
        # Cold-start: no gate-pass exists yet, so the binary survival label is single-class (or too thin) and a
        # classifier cannot learn. Fall back to the experiments registry's continuous forward-P&L SOFT-LABELS
        # (label = "made money out-of-sample") so the ranker still gets a REAL gradient instead of the blind
        # heuristic. Ordering only — the deterministic gate stays the sole survival authority, never reached here.
        from cosmu.experiments.soft_labels import soft_label_training_set

        soft_rows, soft_labels = soft_label_training_set(store)
        if len(soft_rows) >= min_train_labels and len(set(soft_labels)) >= 2:
            rows, labels, n, backend_label = soft_rows, soft_labels, len(soft_rows), "logistic_soft"
        else:
            return SurvivalModel(trained=False, backend="heuristic", n_labels=n)

    # Deterministic chronological split: train on the older 75%, OOS-check on the most recent 25% (point-in-time
    # — we never validate the model on outcomes that predate its training set).
    split = max(1, int(n * 0.75))
    train_rows, train_y = rows[:split], labels[:split]
    test_rows, test_y = rows[split:], labels[split:]

    soft = backend_label == "logistic_soft"  # were forward-P&L soft-labels the training signal (cold-start)?
    booster = _try_boosted(train_rows, train_y)
    if booster is not None:
        model, backend = booster
        scores = [model._score_booster(r) for r in (test_rows or train_rows)]
        auroc = _auroc(scores, test_y or train_y)
        model.trained = True
        model.backend = backend + "_soft" if soft else backend
        model.n_labels = n
        model.auroc = round(auroc, 4)
        return model

    means, stds = _standardize(train_rows)
    std_train = [_apply(r, means, stds) for r in train_rows]
    w, b = _train_logistic(std_train, train_y)
    model = SurvivalModel(
        trained=True, backend=backend_label, n_labels=n, _means=means, _stds=stds, _weights=w, _bias=b
    )
    check_rows = test_rows or train_rows
    check_y = test_y or train_y
    scores = []
    for r in check_rows:
        x = _apply(r, means, stds)
        z = b + sum(w[j] * x[j] for j in range(len(x)))
        scores.append(1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z)))))
    model.auroc = round(_auroc(scores, check_y), 4)
    return model


def _try_boosted(rows: list[list[float]], labels: list[int]) -> tuple[SurvivalModel, str] | None:
    """Train an XGBoost/LightGBM model IF the lib is importable. Returns None when neither is installed (the
    CI/offline path), so the caller falls back to the pure-Python logistic. Both classes present is guaranteed
    by the caller."""
    try:
        import xgboost as xgb  # type: ignore[import-not-found]

        dtrain = xgb.DMatrix(rows, label=labels)
        params = {"objective": "binary:logistic", "max_depth": 3, "eta": 0.2, "seed": 0, "verbosity": 0}
        booster = xgb.train(params, dtrain, num_boost_round=40)
        return SurvivalModel(_booster=booster), "xgboost"
    except ImportError:
        pass
    try:
        import lightgbm as lgb  # type: ignore[import-not-found]

        dataset = lgb.Dataset(rows, label=labels)
        params = {"objective": "binary", "max_depth": 3, "learning_rate": 0.2, "seed": 0, "verbose": -1}
        booster = lgb.train(params, dataset, num_boost_round=40)
        return SurvivalModel(_booster=booster), "lightgbm"
    except ImportError:
        return None


def _labeled_outcomes(store: Store) -> tuple[list[list[float]], list[int]]:
    """Read LABELED outcomes from the store: every screen backtest joined to its strategy_version, labeled
    1 if it passed the gate (survived → forward-test/live track) and 0 if it was killed. Ordered oldest-first so the
    chronological train/OOS split is point-in-time. The label is the deterministic gate's verdict — the model
    learns to PREDICT the gate's survival call, never to override it."""
    rows = store.rows(
        """
        SELECT b.sharpe AS sharpe, b.num_trades AS num_trades, b.max_dd AS max_dd,
               b.folds_positive AS folds_positive, b.pbo AS pbo, b.passed_gates AS passed_gates,
               b.created_at AS created_at, b.regime_label AS regime_label, b.oos_return AS oos_return
        FROM backtests b
        WHERE b.kind = 'screen'
        ORDER BY b.created_at ASC, b.id ASC
        """
    )
    vectors: list[list[float]] = []
    labels: list[int] = []
    for r in rows:
        # Reconstruct the survival feature row from the persisted screen columns. folds_positive is stored as a
        # count out of 6 folds (loop.py writes int(folds_positive_pct * 6)), so /6 recovers the pct.
        folds_pct = float(r["folds_positive"] or 0) / 6.0
        # We persist sharpe (annualized) not sharpe_per_obs on the backtests row; the per-obs proxy used for the
        # heuristic+model is the annualized sharpe scaled down — monotone, which is all the ranker needs.
        sharpe_proxy = float(r["sharpe"] or 0) / 16.0  # ~sqrt(252) de-annualization proxy; monotone in SR
        vectors.append(
            [
                sharpe_proxy,
                float(r["num_trades"] or 0),
                float(r["max_dd"] or 0),
                folds_pct,
                float(r["pbo"] or 0),
                0.0,  # skew not persisted on the screen row — neutral
                0.0,  # excess kurtosis not persisted — neutral
                0.0,  # n_obs not persisted — neutral (the live ranker uses the full feature row)
                0.0,  # regime_spread not persisted per-regime — neutral
            ]
        )
        labels.append(1 if int(r["passed_gates"] or 0) else 0)
    return vectors, labels
