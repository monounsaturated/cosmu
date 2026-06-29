# intent: typed contract for the AUTHORITY-CONVICTION review queue — the propose-only conviction proposals served
# over GET /conviction/proposals; inputs: conviction_proposals rows written by the producer in the voices pass;
# outputs: ConvictionProposalsResponse for the generated TS contract; invariants: PROPOSE-ONLY — every row's
# status is 'proposed' and the API has NO arm/execute path (a human arms off this surface); read-only; honest-
# empty queue when nothing has been produced (never a fabricated proposal); the LLM/Gate/money path is separate.

from __future__ import annotations

from pydantic import BaseModel


class ConvictionTopMover(BaseModel):
    """One of the account's prior correct, resolved calls — magnitude evidence behind its authority."""

    entity: str
    direction: str          # "up" | "down"
    realized_return: float   # signed move the call caught
    ts: str


class ConvictionEvidence(BaseModel):
    """Why this account, why now — the thesis evidence the human reviews. The authority composite (skill-anchored)
    + the EV/magnitude profile (profit, not just hit-rate) + the source post + the disconfirmer context."""

    account: str
    authority_score: float       # the composite the lane gated + sized on
    skill: float
    ev_per_call: float           # excess-hit × magnitude — the profit proxy
    brier_skill_score: float
    avg_hit_magnitude: float
    n_resolved: int
    citation_authority: float    # citation-PageRank (influence) — shown alongside, not the gate
    is_primary: bool             # primacy: first call, not an echo
    lead_lag: str                # "evidence" | "echo" | "none"
    source_quote: str
    source_url: str
    top_movers: list[ConvictionTopMover]


class ConvictionProposalRow(BaseModel):
    """One propose-only conviction trade proposal for a human to review + arm. `size_usd`/`max_loss_usd` are
    strings (exact decimal). `status` is always 'proposed' — this surface NEVER arms or moves money."""

    proposal_id: str
    account: str
    asset: str
    direction: str               # "long" | "short"
    size_usd: str
    max_loss_usd: str
    authority_score: float
    expiry: str
    thesis: str
    status: str                  # always "proposed"
    source: str
    created_at: str
    evidence: ConvictionEvidence


class ConvictionProposalsResponse(BaseModel):
    """The conviction review queue, highest-authority first. `count` is the number of open proposals; an empty
    queue (`count` 0) is the honest state until the voices-pass producer fills it. `armed` is ALWAYS false here —
    the surface is propose-only and exists so a human can review the evidence before arming anything."""

    count: int
    armed: bool = False
    proposals: list[ConvictionProposalRow]
