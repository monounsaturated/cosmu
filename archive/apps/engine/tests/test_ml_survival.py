"""The survival model: cold-start (random/heuristic, trained=False) before the label threshold; trains past
it; NEVER vetoes (count-in == count-out, ordering only); and runs fully offline with no xgboost/lightgbm
installed. The deterministic scorer/gate remain the sole survival authority — this model only orders compute."""

from __future__ import annotations

import builtins
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store, utcnow
from cosmu.master.scorer import BacktestMetrics
from cosmu.ml.survival import (
    MIN_TRAIN_LABELS,
    SurvivalFeatures,
    features_from_metrics,
    load_survival_model,
)


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/ml.sqlite3", openrouter_api_key=None))


def _metrics(*, sharpe_obs: float, trades: int, folds: float, pbo: float, regimes: dict[str, float]) -> BacktestMetrics:
    return BacktestMetrics(
        oos_return=Decimal("0.05"),
        sharpe=Decimal("1.5"),
        sortino=Decimal("2.0"),
        max_drawdown=Decimal("0.1"),
        win_rate=Decimal("0.55"),
        num_trades=trades,
        sharpe_per_obs=Decimal(str(sharpe_obs)),
        skew=Decimal("0.1"),
        kurtosis=Decimal("3.2"),
        n_obs=400,
        pbo=Decimal(str(pbo)),
        trials_counted=5,
        folds_positive_pct=Decimal(str(folds)),
        holdout_deflated_sharpe=Decimal("0.3"),
        regime_returns=regimes,
    )


def _features(score: float) -> SurvivalFeatures:
    # Monotone knob: higher `score` => stronger features => higher survival score.
    return SurvivalFeatures(
        sharpe_per_obs=0.1 * score,
        num_trades=40,
        max_dd=0.1,
        folds_positive_pct=0.5 + 0.4 * score,
        pbo=0.4,
        skew=0.0,
        kurt_excess=0.0,
        n_obs=400,
        regime_spread=2.0,
    )


def _seed_labeled_outcomes(store: Store, n: int) -> None:
    """Write n labeled screen backtests: strong-metric rows pass the gate, weak ones are killed — a learnable
    signal so a trained model separates the classes."""
    with store.batch() as b:
        for i in range(n):
            strong = i % 2 == 0
            sid = b.insert("strategies", {"name": f"s{i}", "thesis": "t", "origin": "seed", "created_at": utcnow()})
            vid = b.insert(
                "strategy_versions",
                {"strategy_id": sid, "spec": {}, "generated_code": "x", "code_hash": f"h{i}", "params": {}, "origin": "seed", "status": "paper" if strong else "killed", "created_at": utcnow()},
            )
            b.insert(
                "backtests",
                {
                    "strategy_version_id": vid, "kind": "screen",
                    "oos_return": "0.05" if strong else "-0.01", "sharpe": "2.0" if strong else "0.1",
                    "sortino": "2.0", "deflated_sharpe": "0.97" if strong else "0.2",
                    "max_dd": "0.08" if strong else "0.3", "win_rate": "0.6",
                    "num_trades": 50 if strong else 8, "pbo": "0.1" if strong else "0.7",
                    "trials_counted": 5, "regime_label": "mixed",
                    "folds_positive": 6 if strong else 1, "passed_gates": 1 if strong else 0,
                    "holdout_passed": 1 if strong else 0, "created_at": utcnow(),
                },
            )


def test_cold_start_is_untrained_and_heuristic(tmp_path):
    store = _store(tmp_path)
    model = load_survival_model(store)
    assert model.trained is False
    assert model.backend == "heuristic"
    assert model.auroc is None
    # the heuristic still produces a usable score in [0,1]
    s = model.score_features(_features(1.0))
    assert 0.0 <= s <= 1.0


def test_cold_start_below_threshold_stays_untrained(tmp_path):
    store = _store(tmp_path)
    _seed_labeled_outcomes(store, MIN_TRAIN_LABELS - 2)
    model = load_survival_model(store)
    assert model.trained is False


def test_trains_past_threshold_and_reports_auroc(tmp_path):
    store = _store(tmp_path)
    _seed_labeled_outcomes(store, MIN_TRAIN_LABELS + 20)
    model = load_survival_model(store)
    assert model.trained is True
    assert model.n_labels >= MIN_TRAIN_LABELS
    assert model.auroc is not None
    # an offline CI box has no xgboost/lightgbm => the pure-Python logistic backend
    assert model.backend in ("logistic", "xgboost", "lightgbm")
    # learnable signal => better-than-coin OOS separation
    assert model.auroc >= 0.5


def test_never_vetoes_count_in_equals_count_out(tmp_path):
    store = _store(tmp_path)
    model = load_survival_model(store)  # cold-start
    items = [(f"c{i}", _features(float(i % 5))) for i in range(11)]
    ranked = model.rank(items)
    assert len(ranked) == len(items)  # nothing filtered/vetoed
    assert {r.key for r in ranked} == {k for k, _ in items}  # exact same set — only reordered
    # ordering is descending by score (a permutation)
    scores = [r.score for r in ranked]
    assert scores == sorted(scores, reverse=True)


def test_ranking_is_monotone_in_features(tmp_path):
    store = _store(tmp_path)
    model = load_survival_model(store)
    ranked = model.rank([("weak", _features(0.0)), ("strong", _features(1.0))])
    assert ranked[0].key == "strong"  # the stronger feature row is validated first


def test_offline_with_no_xgboost(tmp_path, monkeypatch):
    """CI has no xgboost/lightgbm. Simulate that by making their import fail, and confirm training still
    succeeds via the pure-Python logistic fallback (same interface, green CI)."""
    real_import = builtins.__import__

    def _no_boost(name, *args, **kwargs):
        if name in ("xgboost", "lightgbm"):
            raise ImportError(f"{name} not available")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_boost)
    store = _store(tmp_path)
    _seed_labeled_outcomes(store, MIN_TRAIN_LABELS + 20)
    model = load_survival_model(store)
    assert model.trained is True
    assert model.backend == "logistic"  # the dependency-free fallback


def test_features_from_metrics_reads_regime_breadth():
    m = _metrics(sharpe_obs=0.1, trades=40, folds=0.8, pbo=0.2, regimes={"bull": 0.2, "bear": -0.1, "chop": 0.05})
    f = features_from_metrics(m)
    assert f.regime_spread == 2.0  # bull + chop positive, bear negative
    assert f.folds_positive_pct == 0.8
    assert abs(f.kurt_excess - 0.2) < 1e-9  # 3.2 - 3
