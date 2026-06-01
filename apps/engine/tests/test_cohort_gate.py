# The cohort promotion gate: distinct candidates judged together — every one registered as a trial, promotion
# needs stats-significance AND surviving BH-FDR, survivors ranked by NET-OF-COST PROFIT (not Sharpe).

from __future__ import annotations

from decimal import Decimal

from cosmu.config.settings import GateSettings, Settings
from cosmu.knowledge.store import Store
from cosmu.master.cohort import Candidate, promote_cohort
from cosmu.master.scorer import BacktestMetrics


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/cohort.sqlite3"))


def _metrics(sharpe_per_obs: float, n_obs: int = 500, *, strong: bool = True) -> BacktestMetrics:
    return BacktestMetrics(
        oos_return=Decimal("0.1"),
        sharpe=Decimal(str(sharpe_per_obs * 19)),
        sortino=Decimal("0"),
        max_drawdown=Decimal("0.10") if strong else Decimal("0.30"),
        win_rate=Decimal("0.55"),
        num_trades=50,
        sharpe_per_obs=Decimal(str(sharpe_per_obs)),
        skew=Decimal("0"),
        kurtosis=Decimal("3"),
        n_obs=n_obs,
        pbo=Decimal("0.1"),
        trials_counted=1,
        folds_positive_pct=Decimal("0.80") if strong else Decimal("0.30"),
        holdout_deflated_sharpe=Decimal("0.05") if strong else Decimal("-0.1"),
    )


def test_strong_promoted_weak_rejected_and_all_registered(tmp_path):
    store = _store(tmp_path)
    cands = [
        Candidate("strong", _metrics(0.4), net_profit=0.20, source="test"),
        Candidate("weak", _metrics(0.05, n_obs=200, strong=False), net_profit=0.01, source="test"),
    ]
    proms = {p.candidate_id: p for p in promote_cohort(store, cands, GateSettings())}
    assert proms["strong"].promoted and proms["strong"].rank == 1
    assert not proms["weak"].promoted
    assert "deflated_sharpe" in proms["weak"].reasons
    # every candidate registered as a trial (FDR validity) — choke point
    assert store.rows("SELECT COUNT(*) AS n FROM trials")[0]["n"] == 2


def test_survivors_ranked_by_net_profit_not_sharpe(tmp_path):
    store = _store(tmp_path)
    # A has the higher Sharpe; B has the higher NET PROFIT — B must rank first (we rank on money).
    cands = [
        Candidate("A_high_sharpe", _metrics(0.45), net_profit=0.08, source="test"),
        Candidate("B_high_profit", _metrics(0.30), net_profit=0.25, source="test"),
        Candidate("weak", _metrics(0.04, n_obs=200, strong=False), net_profit=0.5, source="test"),
    ]
    proms = {p.candidate_id: p for p in promote_cohort(store, cands, GateSettings())}
    assert proms["A_high_sharpe"].promoted and proms["B_high_profit"].promoted
    assert proms["B_high_profit"].rank == 1   # ranked on net profit, beats the higher-Sharpe A
    assert proms["A_high_sharpe"].rank == 2
    assert not proms["weak"].promoted          # high "profit" but no real edge → never promoted


def test_strong_candidate_survives_fdr(tmp_path):
    store = _store(tmp_path)
    proms = promote_cohort(store, [Candidate("s", _metrics(0.4), net_profit=0.2, source="test")], GateSettings())
    assert proms[0].survived_fdr and proms[0].promoted
