# Durable experiment-memory: every cohort Gate verdict is persisted to gate_verdicts (queryable), the persist
# is opt-in on promote_cohort (pure by default), and a persist failure NEVER breaks the research/gate path.

from __future__ import annotations

import json
from decimal import Decimal

from cosmu.config.settings import GateSettings, Settings
from cosmu.knowledge.store import Store
from cosmu.master.cohort import Candidate, promote_cohort
from cosmu.master.scorer import BacktestMetrics
from cosmu.master.verdict_log import CohortPersist, persist_cohort_verdict


def _store(tmp_path, name="vlog") -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3"))


def _metrics(sharpe_per_obs: float, n_obs: int = 500, *, strong: bool = True) -> BacktestMetrics:
    return BacktestMetrics(
        oos_return=Decimal("0.1"),
        sharpe=Decimal(str(sharpe_per_obs * 19)),
        sortino=Decimal("0"),
        max_drawdown=Decimal("0.10") if strong else Decimal("0.30"),
        win_rate=Decimal("0.55"),
        num_trades=50,
        sharpe_per_obs=Decimal(str(sharpe_per_obs)),
        n_obs=n_obs,
        folds_positive_pct=Decimal("0.80") if strong else Decimal("0.30"),
        holdout_deflated_sharpe=Decimal("0.05") if strong else Decimal("-0.1"),
    )


def _persist(store, run_id="run-1", source="test-cohort") -> CohortPersist:
    return CohortPersist(store=store, run_id=run_id, hypothesis="a real edge?", source=source,
                         audit_trustworthy="yes", extra={"universe": 30})


def test_promote_cohort_is_pure_without_persist(tmp_path):
    """Default promote_cohort writes ZERO gate_verdicts rows — the math path stays side-effect-free."""
    store = _store(tmp_path)
    promote_cohort(store, [Candidate("s", _metrics(0.4), net_profit=0.2, source="t")], GateSettings())
    assert store.rows("SELECT COUNT(*) AS n FROM gate_verdicts")[0]["n"] == 0


def test_persist_writes_one_queryable_cohort_row_and_event(tmp_path):
    store = _store(tmp_path)
    cands = [
        Candidate("strong", _metrics(0.4), net_profit=0.20, source="t", label="the winner"),
        Candidate("weak", _metrics(0.05, n_obs=200, strong=False), net_profit=0.01, source="t"),
    ]
    promote_cohort(store, cands, GateSettings(), persist=_persist(store))

    rows = store.rows("SELECT ts, decision, data_source, payload FROM gate_verdicts")
    assert len(rows) == 1
    row = rows[0]
    assert row["decision"] == "PASS"          # the strong candidate promoted → cohort PASS
    assert row["data_source"] == "live"
    p = json.loads(row["payload"])
    assert p["kind"] == "cohort" and p["run_id"] == "run-1" and p["source"] == "test-cohort"
    assert p["passed"] is True and p["n_candidates"] == 2 and p["n_promoted"] == 1
    assert p["promoted_ids"] == ["strong"]
    assert p["audit_trustworthy"] == "yes" and p["universe"] == 30   # extra is flattened in
    # per-candidate verdicts are stored, queryable
    by_id = {c["id"]: c for c in p["candidates"]}
    assert by_id["strong"]["promoted"] is True and by_id["strong"]["label"] == "the winner"
    assert by_id["weak"]["promoted"] is False and "deflated_sharpe" in by_id["weak"]["reasons"]
    # the REAL holdout DSR is persisted per candidate (OOS-decay visible without a re-run)
    assert by_id["strong"]["holdout_deflated_sharpe"] == 0.05 and by_id["weak"]["holdout_deflated_sharpe"] == -0.1
    assert p["best_deflated_sharpe_prob"] == max(c["deflated_sharpe_prob"] for c in p["candidates"])
    # the cohort_gate_run event is emitted alongside
    ev = store.rows("SELECT kind, ref_id FROM events WHERE kind = 'cohort_gate_run'")
    assert len(ev) == 1 and ev[0]["ref_id"] == "run-1"


def test_failing_cohort_persists_fail_decision(tmp_path):
    store = _store(tmp_path)
    cands = [Candidate("weak", _metrics(0.04, n_obs=200, strong=False), net_profit=0.01, source="t")]
    persist_cohort_verdict(_persist(store, run_id="r-fail"), cands,
                           promote_cohort(store, cands, GateSettings()))
    row = store.rows("SELECT decision, payload FROM gate_verdicts")[-1]
    assert row["decision"] == "FAIL"
    assert json.loads(row["payload"])["passed"] is False


def test_persist_is_best_effort_never_raises(tmp_path):
    """A DB hiccup must not break a research run — persist swallows + reports False, never raises."""
    class _BrokenStore:
        def rows(self, *_a, **_k):
            raise RuntimeError("db down")

        def append_event(self, *_a, **_k):
            raise RuntimeError("db down")

    cands = [Candidate("s", _metrics(0.4), net_profit=0.2, source="t")]
    real = _store(tmp_path)
    proms = promote_cohort(real, cands, GateSettings())
    ok = persist_cohort_verdict(CohortPersist(store=_BrokenStore(), run_id="x", hypothesis="h", source="s"),
                                cands, proms)
    assert ok is False  # failure reported, not raised


def test_empty_cohort_persists_nothing(tmp_path):
    """promote_cohort short-circuits on empty candidates (before persist) → no row written."""
    store = _store(tmp_path)
    promote_cohort(store, [], GateSettings(), persist=_persist(store))
    assert store.rows("SELECT COUNT(*) AS n FROM gate_verdicts")[0]["n"] == 0
