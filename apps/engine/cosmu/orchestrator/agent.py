# intent: the autonomous trading agent — a pluggable stage pipeline run on a cadence, composing the modules already
# built (cohort gate · rotation · cost optimization) into one self-driving cycle with a safety envelope; inputs:
# candidates per cycle + an envelope; outputs: promotions, funded standalone tracks, execution plans, an audit log; invariants:
# the gate is the sole promote authority, no live order escapes the envelope (live toggle + kill-switch + pause),
# and every cycle is deterministic given its inputs. Generators (RD-Agent/Qlib) and execution (Nautilus) plug in as stages.

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from decimal import Decimal

from cosmu.config.settings import GateSettings, RiskSettings
from cosmu.execution.costopt import FeeSchedule, OrderPlan, choose_order
from cosmu.knowledge.store import Store
from cosmu.master.cohort import Candidate, Promotion, promote_cohort
from cosmu.master.execution import IntendedOrder, OrderOutcome, execute_orders
from cosmu.master.portfolio import Portfolio
from cosmu.portfolio.rotation import Track, TrackVerdict, select_tracks
from cosmu.spine.venue import VenueCatalog, default_catalog


@dataclass
class CycleContext:
    """The state passed through one cycle's stages, accumulating the cycle's decisions and an audit log."""

    as_of: datetime
    live_enabled: bool = False  # set by the agent from its envelope so the execute stage can route live
    kill_switch: bool = False
    candidates: list[Candidate] = field(default_factory=list)
    promotions: list[Promotion] = field(default_factory=list)
    funded_tracks: list[TrackVerdict] = field(default_factory=list)  # which standalone tracks stay funded
    plans: list[tuple[str, OrderPlan]] = field(default_factory=list)  # (version_id, execution plan)
    intents: list[IntendedOrder] = field(default_factory=list)
    outcomes: list[OrderOutcome] = field(default_factory=list)
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


def allocate_stage(*, max_tracks: int | None = None) -> Stage:
    """Open a STANDALONE forward-test track for each promoted candidate and defund decayed ones. There is no
    pooled wallet and no cross-track capital weighting — every survivor proves itself on its own track.
    `max_tracks` is an optional operational ceiling on concurrent tracks (None = no ceiling)."""

    def stage(ctx: CycleContext) -> CycleContext:
        by_id = {c.id: c for c in ctx.candidates}
        tracks = [
            Track(id=p.candidate_id, rolling_dsr=p.deflated_sharpe_prob)
            for p in ctx.promotions
            if p.promoted and p.candidate_id in by_id
        ]
        ctx.funded_tracks = select_tracks(tracks, max_tracks=max_tracks)
        funded = sum(1 for v in ctx.funded_tracks if v.funded)
        ctx.log.append(f"allocate: {funded} tracks funded")
        return ctx

    return stage


def execution_plan_stage(fee: FeeSchedule, *, edge_bps_of: Callable[[str], float], spread_bps: float = 4.0) -> Stage:
    """Plan the cheapest viable fill per funded track (maker/taker, net-of-cost). Plans only — orders are placed
    by a separate execute stage gated on the live toggle. `edge_bps_of` gives each track's gross edge in bps."""

    def stage(ctx: CycleContext) -> CycleContext:
        for v in ctx.funded_tracks:
            if not v.funded:
                continue
            plan = choose_order(edge_bps_of(v.version_id), fee, spread_bps)
            ctx.plans.append((v.version_id, plan))
        ctx.log.append(f"plan: {len(ctx.plans)} execution plans")
        return ctx

    return stage


def execute_stage(
    *,
    store: Store,
    portfolio: Portfolio,
    adapter,  # BinanceSpotExecutionAdapter or any core.ExecutionAdapter; None -> sim only
    risk: RiskSettings,
    order_of: Callable[[str, OrderPlan], IntendedOrder | None],
    catalog: VenueCatalog | None = None,
    marks_of: Callable[[], dict[str, Decimal]] | None = None,
) -> Stage:
    """The single execute stage — REPLACES the old 'sim-only: plans not sent' stub. Turns each funded plan into
    an IntendedOrder via `order_of`, then routes the whole batch through master/execution.execute_orders, which
    runs the risk gauntlet and submits live ONLY when (live toggle ON + adapter active + gate passed + caps +
    not killed); otherwise sim-fills. Marks-to-market after, so GET /overview reflects real state."""
    cat = catalog or default_catalog()

    def stage(ctx: CycleContext) -> CycleContext:
        intents: list[IntendedOrder] = []
        for version_id, plan in ctx.plans:
            intent = order_of(version_id, plan)
            if intent is not None:
                intents.append(intent)
        ctx.intents = intents
        ctx.outcomes = execute_orders(
            intents,
            live_enabled=ctx.live_enabled,
            kill_switch=ctx.kill_switch,
            adapter=adapter,
            store=store,
            portfolio=portfolio,
            risk=risk,
            catalog=cat,
        )
        if marks_of is not None:
            portfolio.mark_to_market(marks_of())
        routed = sum(1 for o in ctx.outcomes if o.routed_live)
        filled = sum(1 for o in ctx.outcomes if o.accepted)
        rejected = sum(1 for o in ctx.outcomes if not o.accepted)
        ctx.log.append(f"execute: {filled} filled ({routed} live), {rejected} rejected by gauntlet")
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
        ctx = CycleContext(
            as_of,
            live_enabled=self.envelope.live_enabled,
            kill_switch=self.envelope.kill_switch,
            candidates=list(candidates),
        )
        for stage in self.stages:
            ctx = stage(ctx)
        # The old sim-only note still fires when no execute stage ran (plans planned but not routed).
        if not self.envelope.live_enabled and ctx.plans and not ctx.outcomes:
            ctx.log.append("sim-only: live toggle off, plans not sent to a venue")
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
