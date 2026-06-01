# intent: the autonomous trading agent — a pluggable stage pipeline run on a cadence, composing the modules already
# built (cohort gate · rotation · cost optimization) into one self-driving cycle with a safety envelope; inputs:
# candidates per cycle + an envelope; outputs: promotions, allocations, execution plans, an audit log; invariants:
# the gate is the sole promote authority, no live order escapes the envelope (live toggle + kill-switch + pause),
# and every cycle is deterministic given its inputs. Generators (RD-Agent/Qlib) and execution (Nautilus) plug in as stages.

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from cosmu.config.settings import GateSettings
from cosmu.execution.costopt import FeeSchedule, OrderPlan, choose_order
from cosmu.knowledge.store import Store
from cosmu.master.cohort import Candidate, Promotion, promote_cohort
from cosmu.portfolio.rotation import Allocation, Sleeve, rotate


@dataclass
class CycleContext:
    """The state passed through one cycle's stages, accumulating the cycle's decisions and an audit log."""

    as_of: datetime
    candidates: list[Candidate] = field(default_factory=list)
    promotions: list[Promotion] = field(default_factory=list)
    allocations: list[Allocation] = field(default_factory=list)
    plans: list[tuple[str, OrderPlan]] = field(default_factory=list)  # (sleeve_id, execution plan)
    log: list[str] = field(default_factory=list)


# A stage transforms the cycle context. Generators, signal producers, the gate, allocation, execution all are stages.
Stage = Callable[[CycleContext], CycleContext]


# --- stages that compose the already-built modules ------------------------------------------------

def gate_stage(store: Store, gates: GateSettings, *, fdr_q: float = 0.10) -> Stage:
    """The promotion gate: every candidate registered as a trial, promoted only if it passes stats AND FDR,
    ranked by net-of-cost profit. The sole promote authority — out of any generator's reach."""

    def stage(ctx: CycleContext) -> CycleContext:
        ctx.promotions = promote_cohort(store, ctx.candidates, gates, fdr_q=fdr_q)
        n = sum(1 for p in ctx.promotions if p.promoted)
        ctx.log.append(f"gate: {n}/{len(ctx.candidates)} promoted")
        return ctx

    return stage


def allocate_stage(*, max_positions: int = 3, kelly_cap: float = 0.25) -> Stage:
    """Turn promoted candidates into capital weights — capped-Kelly, concentrated, decayed sleeves defunded."""

    def stage(ctx: CycleContext) -> CycleContext:
        by_id = {c.id: c for c in ctx.candidates}
        sleeves = [
            Sleeve(
                id=p.candidate_id, edge=by_id[p.candidate_id].net_profit,
                variance=by_id[p.candidate_id].return_variance, rolling_dsr=p.deflated_sharpe_prob,
            )
            for p in ctx.promotions
            if p.promoted and p.candidate_id in by_id
        ]
        ctx.allocations = rotate(sleeves, max_positions=max_positions, kelly_cap=kelly_cap)
        funded = sum(1 for a in ctx.allocations if a.weight > 0)
        ctx.log.append(f"allocate: {funded} sleeves funded")
        return ctx

    return stage


def execution_plan_stage(fee: FeeSchedule, *, edge_bps_of: Callable[[str], float], spread_bps: float = 4.0) -> Stage:
    """Plan the cheapest viable fill per funded sleeve (maker/taker, net-of-cost). Plans only — orders are placed
    by a separate execute stage gated on the live toggle. `edge_bps_of` gives each sleeve's gross edge in bps."""

    def stage(ctx: CycleContext) -> CycleContext:
        for a in ctx.allocations:
            if a.weight <= 0:
                continue
            plan = choose_order(edge_bps_of(a.sleeve_id), fee, spread_bps)
            ctx.plans.append((a.sleeve_id, plan))
        ctx.log.append(f"plan: {len(ctx.plans)} execution plans")
        return ctx

    return stage


# --- the autonomous agent -------------------------------------------------------------------------

@dataclass
class AutonomyEnvelope:
    """The safety envelope around full autonomy. `live_enabled` gates real orders; `kill_switch` halts everything;
    `paused` skips cycles. Defaults are the safe ones (no live, not killed) — autonomy is opt-in, not assumed."""

    live_enabled: bool = False
    kill_switch: bool = False
    paused: bool = False


class TradingAgent:
    """Runs the stage pipeline each cycle, inside the envelope, with an optional per-cycle callback for monitoring/
    persistence. The 'huge autonomous agent' is this loop + its pluggable stages — not a model in the hot path."""

    def __init__(
        self,
        stages: list[Stage],
        *,
        envelope: AutonomyEnvelope | None = None,
        on_cycle: Callable[[CycleContext], None] | None = None,
    ) -> None:
        self.stages = stages
        self.envelope = envelope or AutonomyEnvelope()
        self.on_cycle = on_cycle
        self.cycles_run = 0

    def run_cycle(self, as_of: datetime, candidates: list[Candidate]) -> CycleContext:
        if self.envelope.kill_switch:
            return CycleContext(as_of, log=["halted: kill_switch"])
        if self.envelope.paused:
            return CycleContext(as_of, log=["paused"])
        ctx = CycleContext(as_of, candidates=list(candidates))
        for stage in self.stages:
            ctx = stage(ctx)
        if not self.envelope.live_enabled and ctx.plans:
            ctx.log.append("paper-only: live toggle off, plans not sent to a venue")
        self.cycles_run += 1
        if self.on_cycle is not None:
            self.on_cycle(ctx)
        return ctx

    def pause(self) -> None:
        self.envelope.paused = True

    def resume(self) -> None:
        self.envelope.paused = False

    def kill(self) -> None:
        """Trip the kill-switch — every subsequent cycle halts until explicitly revived."""
        self.envelope.kill_switch = True

    def revive(self) -> None:
        self.envelope.kill_switch = False
