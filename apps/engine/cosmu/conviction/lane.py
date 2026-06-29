# intent: the CLEAN interface to the LLM/Conviction lane (master/conviction.py — from the conviction chip, not yet
# merged). The consumer ROUTES proposals through this seam instead of touching the gate/money path directly. The
# contract is PROPOSE-ONLY: submit() registers a proposal for HUMAN review; it NEVER arms, executes, or moves
# money. There is deliberately NO arm()/execute() method on this interface — arming is a separate, explicit human
# action that lives OUTSIDE this lane. When master/conviction.py lands, implement ConvictionLane over it (its
# store + its guardrails) and the consumer is unchanged.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from cosmu.conviction.models import ConvictionProposal


class ConvictionLane(Protocol):
    """The seam the consumer hands proposals to. PROPOSE-ONLY: `submit` queues a proposal for a human; the lane
    never arms it. `open_proposals` is the review queue. A real implementation (over master/conviction.py) keeps
    the same contract — the deterministic guardrails + the human-arm step live behind it, never on this path."""

    def submit(self, proposal: ConvictionProposal) -> None: ...

    def open_proposals(self) -> list[ConvictionProposal]: ...


@dataclass
class InMemoryConvictionLane:
    """The default offline STUB of the conviction lane — used until master/conviction.py is merged (and in tests).
    Holds proposals in memory, deterministically ordered by authority. Enforces propose-only at the boundary: a
    submitted proposal MUST be status='proposed' (asserted), and there is NO method to arm or execute one. So this
    stub structurally cannot move money — exactly the guarantee the real lane must also keep."""

    _proposals: dict[str, ConvictionProposal] = field(default_factory=dict)

    def submit(self, proposal: ConvictionProposal) -> None:
        if proposal.status != "proposed":
            raise ValueError(f"conviction lane is propose-only; refusing status={proposal.status!r}")
        self._proposals[proposal.proposal_id] = proposal

    def open_proposals(self) -> list[ConvictionProposal]:
        """The review queue — highest-authority first, then newest, then id (deterministic)."""
        return sorted(
            self._proposals.values(),
            key=lambda p: (-p.authority_score, p.created_at, p.proposal_id),
        )

    # NOTE: there is intentionally no arm()/execute()/fund() here. Arming is a human-only action off this lane.


def route_to_conviction_lane(proposal: ConvictionProposal, lane: ConvictionLane) -> None:
    """Hand a proposal to the conviction lane for human review. The single choke-point the consumer uses — keeps
    the 'never arms' guarantee in one place."""
    lane.submit(proposal)
