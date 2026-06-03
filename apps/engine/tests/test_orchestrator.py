# The autonomous agent: one cycle composes gate → allocate → execution-plan from the real modules; the safety
# envelope (kill-switch / pause / live toggle) governs autonomy; the efficiency meter tracks capability-per-dollar.

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from cosmu.config.settings import GateSettings, Settings
from cosmu.execution.costopt import FeeSchedule
from cosmu.knowledge.store import Store
from cosmu.master.cohort import Candidate
from cosmu.master.scorer import BacktestMetrics
from cosmu.orchestrator import (
    AutonomyEnvelope,
    EfficiencyMeter,
    TradingAgent,
    allocate_stage,
    execution_plan_stage,
    gate_stage,
)

AS_OF = datetime(2024, 6, 1, tzinfo=UTC)
FEE = FeeSchedule(maker_bps=-0.5, taker_bps=5.0)


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/agent.sqlite3"))


def _metrics(sharpe_per_obs: float, n_obs: int = 500, *, strong: bool = True) -> BacktestMetrics:
    return BacktestMetrics(
        oos_return=Decimal("0.1"), sharpe=Decimal(str(sharpe_per_obs * 19)), sortino=Decimal("0"),
        max_drawdown=Decimal("0.10") if strong else Decimal("0.30"), win_rate=Decimal("0.55"),
        num_trades=50, sharpe_per_obs=Decimal(str(sharpe_per_obs)), skew=Decimal("0"), kurtosis=Decimal("3"),
        n_obs=n_obs, pbo=Decimal("0.1"), trials_counted=1,
        folds_positive_pct=Decimal("0.80") if strong else Decimal("0.30"),
        holdout_deflated_sharpe=Decimal("0.05") if strong else Decimal("-0.1"),
    )


def _candidates() -> list[Candidate]:
    return [
        Candidate("strong", _metrics(0.4), net_profit=0.20, source="test", return_variance=0.04),
        Candidate("weak", _metrics(0.04, n_obs=200, strong=False), net_profit=0.5, source="test"),
    ]


def _agent(store, **envelope_kw) -> TradingAgent:
    stages = [
        gate_stage(store, GateSettings()),
        allocate_stage(),
        execution_plan_stage(FEE, edge_bps_of=lambda _id: 20.0),
    ]
    return TradingAgent(stages, envelope=AutonomyEnvelope(**envelope_kw))


def test_full_autonomous_cycle(tmp_path):
    agent = _agent(_store(tmp_path))
    ctx = agent.run_cycle(AS_OF, _candidates())
    promoted = {p.candidate_id for p in ctx.promotions if p.promoted}
    assert promoted == {"strong"}                                  # gate authority: only the real edge
    assert any(v.version_id == "strong" and v.funded for v in ctx.funded_tracks)
    assert len(ctx.plans) >= 1 and ctx.plans[0][1].order_type in ("maker", "market")
    assert agent.cycles_run == 1
    assert any("sim-only" in line for line in ctx.log)             # live off → not sent to a venue


def test_kill_switch_halts_everything(tmp_path):
    agent = _agent(_store(tmp_path))
    agent.kill()
    ctx = agent.run_cycle(AS_OF, _candidates())
    assert ctx.log == ["halted: kill_switch"]
    assert not ctx.promotions and agent.cycles_run == 0


def test_pause_skips_cycle(tmp_path):
    agent = _agent(_store(tmp_path))
    agent.pause()
    assert agent.run_cycle(AS_OF, _candidates()).log == ["paused"]
    agent.resume()
    assert agent.run_cycle(AS_OF, _candidates()).promotions  # resumes normally


def test_efficiency_meter_tracks_cost_per_accepted(tmp_path):
    meter = EfficiencyMeter()

    def on_cycle(ctx):
        accepted = sum(1 for p in ctx.promotions if p.promoted)
        meter.record(spend_usd=2.0, candidates=len(ctx.candidates), accepted=accepted)

    agent = TradingAgent(
        [gate_stage(_store(tmp_path), GateSettings())], envelope=AutonomyEnvelope(), on_cycle=on_cycle
    )
    agent.run_cycle(AS_OF, _candidates())
    assert meter.accepted == 1 and meter.candidates == 2
    assert meter.cost_per_accepted == 2.0
    assert meter.acceptance_rate == 0.5
