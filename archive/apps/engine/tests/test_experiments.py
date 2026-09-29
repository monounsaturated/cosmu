# Tests for the experiments registry (cosmu/experiments): the data-version fingerprint, the append-only
# registry + its readers, the thin finder/gate call-site hooks, and the soft-label bridge that gives the ML
# survival ranker a continuous forward-P&L gradient BEFORE any candidate has passed the deterministic gate.

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.data.market import Bar
from cosmu.evolution.seeder import seed_orb_fvg_spec
from cosmu.experiments import (
    EMPTY_DATA_VERSION,
    ExperimentRecord,
    KIND_FINDER,
    count_experiments,
    data_version,
    fingerprint,
    log_experiment,
    log_experiments,
    recent_experiments,
    soft_label_training_set,
    soft_labeled_outcomes,
)
from cosmu.knowledge.store import Store
from cosmu.lab.finder import StrategyFinder
from cosmu.master.scorer import BacktestMetrics
from cosmu.ml.survival import load_survival_model
from cosmu.research.fixtures import edge_bearing_screen_market, synthetic_ablation_inputs
from cosmu.research.gate import evaluate_ablation


def _store(tmp_path, name="exp") -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3", openrouter_api_key=None))


def _bars(n: int, *, close0: float = 100.0, step: float = 1.0) -> list[Bar]:
    base = datetime(2023, 1, 1, tzinfo=UTC)
    out: list[Bar] = []
    for i in range(n):
        c = Decimal(str(close0 + i * step))
        out.append(Bar(ts=base + timedelta(hours=i), open=c, high=c, low=c, close=c, volume=Decimal("1")))
    return out


# --------------------------------------------------------------------------- data_version


def test_data_version_is_deterministic_and_sensitive():
    a = {"BTCUSDT": _bars(50), "ETHUSDT": _bars(40, close0=2000)}
    # same data → same fingerprint string (comparable + regenerable)
    assert data_version(a) == data_version({"BTCUSDT": _bars(50), "ETHUSDT": _bars(40, close0=2000)})
    # order-independent (dict key order must not matter)
    assert data_version(a) == data_version({"ETHUSDT": _bars(40, close0=2000), "BTCUSDT": _bars(50)})
    # any change to the window or contents changes the version
    assert data_version(a) != data_version({"BTCUSDT": _bars(51), "ETHUSDT": _bars(40, close0=2000)})
    assert data_version(a) != data_version({"BTCUSDT": _bars(50, step=2.0), "ETHUSDT": _bars(40, close0=2000)})
    assert data_version(a).startswith("data:")


def test_data_version_empty_market():
    assert data_version({}) == EMPTY_DATA_VERSION
    assert data_version({"BTCUSDT": []}) == EMPTY_DATA_VERSION


def test_data_version_accepts_cross_asset_shape():
    nested = {"crypto": {"BTCUSDT": _bars(30)}, "equity": {"SPY": _bars(30, close0=400)}}
    flat = {"crypto/BTCUSDT": _bars(30), "equity/SPY": _bars(30, close0=400)}
    # the nested cross-asset shape fingerprints the same as the equivalent flattened single-asset shape
    assert data_version(nested) == data_version(flat)
    fp = fingerprint(nested)
    assert set(fp) == {"crypto/BTCUSDT", "equity/SPY"}
    assert fp["crypto/BTCUSDT"]["n"] == 30


# --------------------------------------------------------------------------- registry CRUD


def _metrics(sharpe_per_obs: float, oos: float, trades: int = 40) -> BacktestMetrics:
    return BacktestMetrics(
        oos_return=Decimal(str(oos)),
        sharpe=Decimal(str(sharpe_per_obs * 16)),
        sortino=Decimal("0"),
        max_drawdown=Decimal("0.05"),
        win_rate=Decimal("0.5"),
        num_trades=trades,
        sharpe_per_obs=Decimal(str(sharpe_per_obs)),
        n_obs=200,
        folds_positive_pct=Decimal("0.6"),
    )


def test_log_and_read_back():
    import tempfile

    store = _store(tempfile.mkdtemp(), "crud")
    rec = ExperimentRecord(
        kind=KIND_FINDER,
        source="finder",
        label="abc123",
        config={"lookback": 14, "config_tag": "abc123"},
        metrics=_metrics(0.05, 0.1).model_dump(mode="json"),
        seed=7,
        data_version="data:deadbeef",
        code_hash="hash1",
        soft_label=0.1,
        gate_passed=False,
    )
    rid = log_experiment(store, rec)
    assert rid

    rows = recent_experiments(store)
    assert len(rows) == 1
    row = rows[0]
    assert row["kind"] == KIND_FINDER
    assert row["label"] == "abc123"
    assert row["seed"] == 7
    assert row["data_version"] == "data:deadbeef"
    assert float(row["soft_label"]) == 0.1
    # JSON columns come back decoded
    assert row["config"]["config_tag"] == "abc123"
    assert "oos_return" in row["metrics"]
    # the batch emitted an audit event
    events = store.rows("SELECT * FROM events WHERE kind = 'experiments_logged'")
    assert events


def test_recent_experiments_filters_and_counts():
    import tempfile

    store = _store(tempfile.mkdtemp(), "filter")
    log_experiments(
        store,
        [
            ExperimentRecord(kind="finder", source="finder", config={}, metrics={}, seed=7, data_version="dv1"),
            ExperimentRecord(kind="edge_gate", source="edge_gate", config={}, metrics={}, seed=7, data_version="dv2"),
            ExperimentRecord(kind="finder", source="finder", config={}, metrics={}, seed=7, data_version="dv1"),
        ],
    )
    assert count_experiments(store) == 3
    assert count_experiments(store, kind="finder") == 2
    assert len(recent_experiments(store, kind="finder")) == 2
    assert len(recent_experiments(store, data_version="dv2")) == 1


# --------------------------------------------------------------------------- finder hook


class _FixtureBars:
    def __init__(self) -> None:
        full = edge_bearing_screen_market(n=280)
        self._by = {sym: full[sym][-280:] for sym in ("BTCUSDT", "ETHUSDT")}
        self._default = self._by["BTCUSDT"]

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        return self._by.get(symbol, self._default)[-limit:]


def test_finder_logs_one_experiment_per_screened_variant(tmp_path):
    store = _store(tmp_path, "finder")
    finder = StrategyFinder(settings=store.settings, store=store, market_data=_FixtureBars())
    report = finder.find(seed_orb_fvg_spec(), max_variants=12)

    rows = recent_experiments(store, kind=KIND_FINDER, limit=10_000)
    # one registry row per screened variant — the run is fully captured, not just the winners
    assert len(rows) == report.screened
    # every finder row carries the regeneration key (config_tag + seed + data_version) and a soft-label
    assert all(r["config"].get("config_tag") for r in rows)
    assert all(r["seed"] == int(store.settings.evolution.default_seed) for r in rows)
    assert all(r["soft_label"] is not None for r in rows)
    # a single run consumed ONE data window → exactly one distinct data_version
    assert len({r["data_version"] for r in rows}) == 1


# --------------------------------------------------------------------------- gate hook


def test_ablation_logs_arm_experiments(tmp_path):
    store = _store(tmp_path, "abl")
    market, alt, news = synthetic_ablation_inputs(edge=True, seed=7)
    evaluate_ablation(market, alt, news, store)
    rows = recent_experiments(store, kind="ablation", limit=1000)
    # the counted arms (price_only, alt_full, + drop arms) are each logged with a forward-P&L soft-label
    assert rows
    labels = {r["label"] for r in rows}
    assert "price_only" in labels and "alt_full" in labels
    assert all(r["soft_label"] is not None for r in rows)


# --------------------------------------------------------------------------- soft labels → ranker


def _seed_soft_experiments(store: Store, n: int = 40) -> None:
    """Log n finder experiments with MIXED forward-P&L (half winners, half losers) and NO gate-pass — exactly
    the cold-start state where the binary survival label is single-class but a soft-label gradient exists."""
    recs = []
    for i in range(n):
        win = i % 2 == 0
        pnl = 0.02 + i * 0.001 if win else -(0.02 + i * 0.001)
        recs.append(
            ExperimentRecord(
                kind=KIND_FINDER,
                source="finder",
                label=f"v{i}",
                config={"config_tag": f"v{i}"},
                metrics=_metrics(0.04 if win else -0.04, pnl).model_dump(mode="json"),
                seed=7,
                data_version="data:fixed",
                soft_label=pnl,
                gate_passed=False,  # nothing has passed → binary label is single-class
            )
        )
    log_experiments(store, recs)


def test_soft_labeled_outcomes_and_training_set(tmp_path):
    store = _store(tmp_path, "soft")
    _seed_soft_experiments(store, 40)
    outcomes = soft_labeled_outcomes(store)
    assert len(outcomes) == 40
    # outcomes carry the continuous forward-P&L and a feature row projected onto the survival vocabulary
    assert any(o.forward_pnl > 0 for o in outcomes) and any(o.forward_pnl < 0 for o in outcomes)
    vectors, labels = soft_label_training_set(store)
    assert len(vectors) == 40
    assert set(labels) == {0, 1}  # both classes present → a real gradient


def test_survival_model_cold_starts_on_soft_labels(tmp_path):
    store = _store(tmp_path, "cold")
    # No backtests rows exist (no gate-pass yet) → the binary path is single-class and would stay heuristic.
    _seed_soft_experiments(store, 40)
    model = load_survival_model(store, min_train_labels=30)
    # the ranker now TRAINS on the forward-P&L soft-labels instead of falling back to the blind heuristic.
    # backend tier varies with what's importable (xgboost/lightgbm/logistic), but the "_soft" suffix records
    # that the forward-P&L soft-labels were the training signal.
    assert model.trained is True
    assert model.backend.endswith("_soft")
    assert model.n_labels == 40


def test_survival_model_stays_heuristic_without_soft_labels(tmp_path):
    store = _store(tmp_path, "nolabels")
    # empty store: no backtests, no experiments → nothing to learn from → honest cold-start heuristic
    model = load_survival_model(store, min_train_labels=30)
    assert model.trained is False
    assert model.backend == "heuristic"
