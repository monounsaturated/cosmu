# intent: the DETERMINISTIC money envelope for the snipe lane — the "disposes" half of "LLM proposes,
# deterministic disposes". Given a ConvictionProposal + operator caps + the current bankroll state, it returns a
# yes/no with reasons. NO LLM, no network, no clock surprises: pure and total, so a hallucinated proposal can at
# worst place a bet INSIDE the operator's tiny caps — never blow up the account. inputs: proposal, caps, state;
# outputs: GateDecision. invariants: the gate only ever CAPS/REJECTS — it NEVER up-sizes a bet (no revenge/
# martingale path exists); it is the ONLY thing that may authorize execution, and even then only per the mode
# dial; kill_switch and the caps are the hard safety, out of any LLM's reach.

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum

from cosmu.snipe.proposal import ConvictionProposal


class ExecutionMode(str, Enum):
    """The autonomy dial — operator-owned. Even at the most autonomous, the LLM never fires: the deterministic
    gate fires a proposal that already cleared the deterministic caps."""

    PROPOSE_ONLY = "propose_only"            # surface proposals; execute NOTHING (default, safest)
    HUMAN_CONFIRM = "human_confirm"          # a passing proposal needs an explicit 2-click human confirm to fire
    BOUNDED_AUTONOMOUS = "bounded_autonomous"  # a passing proposal auto-fires — but ONLY within the caps below


@dataclass(frozen=True)
class ConvictionCaps:
    """The hard money envelope the operator sets. Conservative defaults; live only ever moves money inside
    these. All dollar caps are USDC notional."""

    per_bet_usd: Decimal = Decimal("25")          # max stake on any one bet
    daily_usd: Decimal = Decimal("100")           # max total staked per UTC day
    total_exposure_usd: Decimal = Decimal("250")  # max total open exposure across all bets
    max_open_bets: int = 10                       # max concurrent open positions
    min_edge_prob: Decimal = Decimal("0.05")      # require ≥ 5 percentage points of edge (fair vs price) to act
    min_confidence: Decimal = Decimal("0.60")     # require ≥ 60% agent confidence
    min_price: Decimal = Decimal("0.05")          # don't touch < 5c (lottery noise / illiquid tails)
    max_price: Decimal = Decimal("0.95")          # don't touch > 95c (near-certain, thin payoff, gap risk)
    max_book_fraction: Decimal = Decimal("0.10")  # a bet may take ≤ 10% of the available book depth
    mode: ExecutionMode = ExecutionMode.PROPOSE_ONLY
    kill_switch: bool = False                     # True = nothing executes, regardless of mode (panic stop)


@dataclass(frozen=True)
class GateState:
    """The deterministic bankroll state the gate enforces caps against — sourced from the real ledger, never an
    LLM. `book_depth_usd` is the available depth at the proposal's limit price (None = depth unknown → the
    book-fraction check is skipped, but every other cap still binds)."""

    staked_today_usd: Decimal = Decimal("0")
    open_exposure_usd: Decimal = Decimal("0")
    open_bets: int = 0
    book_depth_usd: Decimal | None = None
    now: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


@dataclass(frozen=True)
class GateDecision:
    """The verdict. `ok` = the proposal cleared every deterministic check. `would_execute` = it should fire NOW
    without a human (only true in BOUNDED_AUTONOMOUS, kill off). `requires_human` = it's eligible but needs a
    confirm (HUMAN_CONFIRM). In PROPOSE_ONLY a passing proposal is `ok` but neither executes nor asks."""

    ok: bool
    reasons: list[str]
    would_execute: bool
    requires_human: bool


class ConvictionGate:
    """Deterministic disposer. `evaluate` is a pure function of (proposal, caps, state) — same inputs → same
    verdict, always. It NEVER sizes a bet (the proposal carries its own size); it only caps/rejects, so there is
    structurally no revenge/martingale path. This is the single authority that may green-light a real order."""

    def evaluate(self, proposal: ConvictionProposal, caps: ConvictionCaps, state: GateState) -> GateDecision:
        reasons: list[str] = []

        # Hard stops first (any one of these alone blocks).
        if caps.kill_switch:
            reasons.append("kill_switch_on")
        if proposal.is_expired(state.now):
            reasons.append("proposal_expired")

        # Per-bet + portfolio caps.
        if proposal.size_usd > caps.per_bet_usd:
            reasons.append(f"size_over_per_bet_cap({proposal.size_usd}>{caps.per_bet_usd})")
        if state.staked_today_usd + proposal.size_usd > caps.daily_usd:
            reasons.append(f"over_daily_cap({state.staked_today_usd}+{proposal.size_usd}>{caps.daily_usd})")
        if state.open_exposure_usd + proposal.size_usd > caps.total_exposure_usd:
            reasons.append(
                f"over_total_exposure({state.open_exposure_usd}+{proposal.size_usd}>{caps.total_exposure_usd})"
            )
        if state.open_bets >= caps.max_open_bets:
            reasons.append(f"too_many_open_bets({state.open_bets}>={caps.max_open_bets})")

        # Quality / price-band caps.
        if proposal.confidence < caps.min_confidence:
            reasons.append(f"confidence_below_min({proposal.confidence}<{caps.min_confidence})")
        if not (caps.min_price <= proposal.limit_price <= caps.max_price):
            reasons.append(f"price_out_of_band({proposal.limit_price}~[{caps.min_price},{caps.max_price}])")
        if proposal.edge_prob() < caps.min_edge_prob:
            reasons.append(f"edge_below_min({proposal.edge_prob()}<{caps.min_edge_prob})")

        # Capacity: never take more than a slice of the available book (only when depth is known).
        if state.book_depth_usd is not None and proposal.size_usd > caps.max_book_fraction * state.book_depth_usd:
            reasons.append(
                f"over_book_fraction({proposal.size_usd}>{caps.max_book_fraction}×{state.book_depth_usd})"
            )

        ok = not reasons
        would_execute = ok and caps.mode == ExecutionMode.BOUNDED_AUTONOMOUS and not caps.kill_switch
        requires_human = ok and caps.mode == ExecutionMode.HUMAN_CONFIRM
        return GateDecision(
            ok=ok,
            reasons=reasons or ["pass"],
            would_execute=would_execute,
            requires_human=requires_human,
        )
