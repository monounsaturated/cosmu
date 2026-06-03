# intent: the autonomous agent — the brain that drives the self-learning loop (ingest → signals → ML → gate →
# allocate → trade), monitors, iterates, and stays inside a safety envelope; invariants: the deterministic gate is
# the sole promote authority, no live order without the live toggle, a kill-switch halts everything, and every
# cycle is auditable. Stages are pluggable so Qlib/RD-Agent/Nautilus workers slot in behind typed contracts.

from __future__ import annotations

from cosmu.orchestrator.agent import (
    AutonomyEnvelope,
    CycleContext,
    Stage,
    TradingAgent,
    allocate_stage,
    execute_stage,
    execution_plan_stage,
    gate_stage,
)
from cosmu.orchestrator.efficiency import EfficiencyMeter
from cosmu.orchestrator.loop import TrackFundingReport, fund_tracks_from_survivors, mark_tracks

__all__ = [
    "AutonomyEnvelope",
    "CycleContext",
    "EfficiencyMeter",
    "Stage",
    "TrackFundingReport",
    "TradingAgent",
    "allocate_stage",
    "execute_stage",
    "execution_plan_stage",
    "fund_tracks_from_survivors",
    "gate_stage",
    "mark_tracks",
]
