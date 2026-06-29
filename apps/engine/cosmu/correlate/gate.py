# intent: the DETERMINISTIC money envelope for the correlation-conviction lane — the "disposes" half of "LLM
# proposes, deterministic disposes", the cross-asset sibling of cosmu/snipe/gate.py. Given a CorrelationProposal
# (a trade on a CORRELATED ASSET driven by a Polymarket event move) + operator caps + bankroll state, it returns
# a yes/no with reasons. NO LLM, no network, pure + total. It only ever CAPS/REJECTS — never up-sizes (no
# revenge/martingale path). Two things make it STRICTER than the snipe gate, because a cross-asset move is far
# more CONFOUNDED than a same-market bet: (1) a mandatory non-trivial disconfirmer, and (2) a HUMAN-ARMED
# interlock — this lane NEVER auto-fires, even in BOUNDED_AUTONOMOUS, so the realistic ceiling is "requires a
# human confirm". Reuses the snipe lane's ExecutionMode + GateDecision so the autonomy dial is one concept.

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from cosmu.snipe.gate import ExecutionMode, GateDecision

if TYPE_CHECKING:  # type-only — breaks the proposal<->gate import cycle (proposal.py imports CorrelationCaps)
    from cosmu.correlate.proposal import CorrelationProposal


@dataclass(frozen=True)
class CorrelationCaps:
    """The hard money envelope the operator sets for the correlation-conviction lane. Conservative defaults; live
    only ever moves money inside these. All dollar caps are USD notional. `human_armed_required` is the lane's
    defining safety: True (default) means a passing proposal can AT MOST ask for a human confirm — it never
    auto-fires, regardless of `mode`. This lane trades a confounded cross-asset move, so it is deliberately
    stricter than the same-market snipe lane."""

    per_trade_usd: Decimal = Decimal("25")        # max stake on any one correlated-asset trade (small by design)
    daily_usd: Decimal = Decimal("100")           # max total staked per UTC day across this lane
    total_exposure_usd: Decimal = Decimal("250")  # max total open exposure across all open correlation trades
    max_open_trades: int = 8                      # max concurrent open positions
    min_confidence: Decimal = Decimal("0.55")     # require ≥ 55% proposal confidence
    min_move: Decimal = Decimal("0.05")           # require ≥ 5pp of |PM probability move| to act
    max_loss_pct: Decimal = Decimal("0.50")       # the stop: max_loss_usd must be ≤ this fraction of the stake
    require_disconfirmer: bool = True             # a non-trivial confound disconfirmer is mandatory
    min_disconfirmer_len: int = 20                # "n/a" is not a disconfirmer — demand a real one
    mode: ExecutionMode = ExecutionMode.PROPOSE_ONLY
    human_armed_required: bool = True             # this lane NEVER auto-fires; the ceiling is requires_human
    kill_switch: bool = False                     # True = nothing executes, regardless of mode (panic stop)


@dataclass(frozen=True)
class CorrelationState:
    """The deterministic bankroll state the gate enforces caps against — sourced from the real ledger, never an
    LLM."""

    staked_today_usd: Decimal = Decimal("0")
    open_exposure_usd: Decimal = Decimal("0")
    open_trades: int = 0
    now: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


class CorrelationConvictionGate:
    """Deterministic disposer for the correlation lane. `evaluate` is a pure function of (proposal, caps, state).
    It NEVER sizes a trade (the proposal carries its own size); it only caps/rejects. With `human_armed_required`
    (default), `would_execute` is structurally always False — the strongest verdict a proposal can earn is
    `requires_human`. This is the single authority that may mark a trade eligible."""

    def evaluate(
        self, proposal: CorrelationProposal, caps: CorrelationCaps, state: CorrelationState
    ) -> GateDecision:
        reasons: list[str] = []

        # Hard stops first (any one alone blocks).
        if caps.kill_switch:
            reasons.append("kill_switch_on")
        if proposal.is_expired(state.now):
            reasons.append("proposal_expired")

        # Per-trade + portfolio caps.
        if proposal.size_usd > caps.per_trade_usd:
            reasons.append(f"size_over_per_trade_cap({proposal.size_usd}>{caps.per_trade_usd})")
        if state.staked_today_usd + proposal.size_usd > caps.daily_usd:
            reasons.append(f"over_daily_cap({state.staked_today_usd}+{proposal.size_usd}>{caps.daily_usd})")
        if state.open_exposure_usd + proposal.size_usd > caps.total_exposure_usd:
            reasons.append(
                f"over_total_exposure({state.open_exposure_usd}+{proposal.size_usd}>{caps.total_exposure_usd})"
            )
        if state.open_trades >= caps.max_open_trades:
            reasons.append(f"too_many_open_trades({state.open_trades}>={caps.max_open_trades})")

        # The max-loss cap (the stop) — must be a positive fraction of the stake, never larger than it. A stop
        # bigger than the stake is structurally impossible for a propose-only spot trade and is rejected.
        loss_cap = caps.max_loss_pct * proposal.size_usd
        if proposal.max_loss_usd <= 0:
            reasons.append("max_loss_not_positive")
        if proposal.max_loss_usd > proposal.size_usd:
            reasons.append(f"max_loss_over_stake({proposal.max_loss_usd}>{proposal.size_usd})")
        if proposal.max_loss_usd > loss_cap:
            reasons.append(f"max_loss_over_cap({proposal.max_loss_usd}>{caps.max_loss_pct}×{proposal.size_usd})")

        # Quality caps.
        if proposal.confidence < caps.min_confidence:
            reasons.append(f"confidence_below_min({proposal.confidence}<{caps.min_confidence})")
        if abs(proposal.pm_delta) < caps.min_move:
            reasons.append(f"move_below_min(|{proposal.pm_delta}|<{caps.min_move})")

        # The mandatory confound disconfirmer — the whole point of routing this lane through a human. Pydantic
        # already requires min_length=1; the gate demands a SUBSTANTIVE one (a confounded cross-asset attribution
        # with no real disconfirmer is exactly the trade we must not take).
        if caps.require_disconfirmer and len(proposal.disconfirmer.strip()) < caps.min_disconfirmer_len:
            reasons.append(f"disconfirmer_too_thin(<{caps.min_disconfirmer_len}chars)")

        ok = not reasons
        # HUMAN-ARMED interlock: with human_armed_required, this lane never auto-fires — would_execute is forced
        # False and a passing proposal can at most require a human confirm. Only an operator who explicitly turns
        # human_armed_required OFF *and* selects BOUNDED_AUTONOMOUS can auto-fire (deliberately hard to reach).
        autonomous = caps.mode == ExecutionMode.BOUNDED_AUTONOMOUS and not caps.kill_switch
        would_execute = ok and autonomous and not caps.human_armed_required
        requires_human = ok and (
            caps.mode == ExecutionMode.HUMAN_CONFIRM or (autonomous and caps.human_armed_required)
        )
        return GateDecision(
            ok=ok,
            reasons=reasons or ["pass"],
            would_execute=would_execute,
            requires_human=requires_human,
        )


__all__ = [
    "CorrelationCaps",
    "CorrelationConvictionGate",
    "CorrelationState",
]
