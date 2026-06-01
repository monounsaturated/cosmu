# The orchestrator execute stage REPLACES the paper-only stub: a funded plan becomes an IntendedOrder, runs the
# gauntlet, and paper-fills with the live toggle OFF (no live route without toggle+keys+gate).

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from cosmu.adapters.exec.binance import BinanceSpotExecutionAdapter
from cosmu.config.settings import GateSettings, RiskSettings, Settings
from cosmu.execution.costopt import FeeSchedule, OrderPlan
from cosmu.knowledge.store import Store
from cosmu.master.cohort import Candidate
from cosmu.master.execution import IntendedOrder
from cosmu.master.portfolio import PaperPortfolio
from cosmu.master.scorer import BacktestMetrics
from cosmu.orchestrator import (
    AutonomyEnvelope,
    TradingAgent,
    allocate_stage,
    execute_stage,
    execution_plan_stage,
    gate_stage,
)

AS_OF = datetime(2024, 6, 1, tzinfo=UTC)
FEE = FeeSchedule(maker_bps=-0.5, taker_bps=5.0)


def _metrics(spo: float) -> BacktestMetrics:
    return BacktestMetrics(
        oos_return=Decimal("0.1"), sharpe=Decimal(str(spo * 19)), sortino=Decimal("0"), max_drawdown=Decimal("0.10"),
        win_rate=Decimal("0.55"), num_trades=50, sharpe_per_obs=Decimal(str(spo)), skew=Decimal("0"),
        kurtosis=Decimal("3"), n_obs=500, pbo=Decimal("0.1"), trials_counted=1, folds_positive_pct=Decimal("0.80"),
        holdout_deflated_sharpe=Decimal("0.05"),
    )


def test_execute_stage_paper_fills_live_off(tmp_path):
    store = Store(Settings(database_url=f"sqlite:///{tmp_path}/stage.sqlite3"))
    pf = PaperPortfolio(store)
    adapter = BinanceSpotExecutionAdapter(client=None, mode="disabled")

    def order_of(sleeve_id: str, plan: OrderPlan) -> IntendedOrder:
        return IntendedOrder(
            strategy_version_id=sleeve_id, symbol="BTCUSDT", venue_id="binance", side=1, qty=Decimal("0.05"),
            price=Decimal("65000"), stop_loss=Decimal("61000"), take_profit=Decimal("72000"),
            conviction=Decimal("0.6"), gate_passed=True, order_type=plan.order_type if plan.order_type == "market" else "market",
        )

    agent = TradingAgent(
        [
            gate_stage(store, GateSettings()),
            allocate_stage(),
            execution_plan_stage(FEE, edge_bps_of=lambda _id: 20.0),
            execute_stage(store=store, portfolio=pf, adapter=adapter, risk=RiskSettings(), order_of=order_of,
                          marks_of=lambda: {"btc-usdt-binance": Decimal("65500")}),
        ],
        envelope=AutonomyEnvelope(live_enabled=False),
    )
    ctx = agent.run_cycle(AS_OF, [Candidate("strong", _metrics(0.4), net_profit=0.20, source="t", return_variance=0.04)])
    assert ctx.outcomes and all(not o.routed_live for o in ctx.outcomes)
    assert any(o.accepted and o.venue == "paper" for o in ctx.outcomes)
    assert any("execute:" in line for line in ctx.log)
    # snapshot written -> portfolio reflects real state
    assert store.row("SELECT id FROM portfolio_snapshots") is not None
