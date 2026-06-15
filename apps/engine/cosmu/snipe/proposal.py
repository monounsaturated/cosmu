# intent: the typed bet an agent (or human) PROPOSES on a prediction market — the ONLY artifact the snipe-lane
# agent emits. It carries the economic case (fair_prob, edge, confidence) + a MANDATORY rationale and
# disconfirmer; it executes nothing itself. inputs: agent/human reasoning over data; outputs: a validated
# proposal the deterministic ConvictionGate (gate.py) disposes. invariants: pure data; size/prices bounded by
# Pydantic; rationale + disconfirmer required (no naked conviction); the LLM PROPOSES — it never fires. Lean +
# venue-independent of the Binance lane (single venue = Polymarket for now).

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(tz=UTC)


class ConvictionProposal(BaseModel):
    """One proposed prediction-market bet. The agent reasons over data + memory and emits THIS; the deterministic
    gate (never an LLM) decides whether a dollar moves. Every field that touches money is bounded here so a
    malformed/hallucinated proposal can't even be constructed out of range."""

    proposal_id: str = Field(default_factory=lambda: uuid4().hex)
    venue: Literal["polymarket"] = "polymarket"  # lean: one event venue; NOT linked to the Binance lane
    market_id: str                                # Polymarket condition/market id
    market_question: str                          # human-readable question (audit + UI)
    outcome: str                                  # the outcome bet on, e.g. "Yes" / "Spain"
    token_id: str                                 # the CLOB token (ERC-1155 asset id) for `outcome`
    side: Literal["buy", "sell"] = "buy"
    size_usd: Decimal = Field(gt=0)               # notional USDC to stake
    limit_price: Decimal = Field(ge=0, le=1)      # price in probability units [0,1]: max for buy / min for sell
    fair_prob: Decimal = Field(ge=0, le=1)        # the agent's estimated fair probability of `outcome`
    confidence: Decimal = Field(ge=0, le=1)       # the agent's confidence in its own estimate
    rationale: str = Field(min_length=1)          # the economic WHY (required — no naked conviction)
    disconfirmer: str = Field(min_length=1)       # what would prove this WRONG (required — the skeptic's hook)
    expiry: datetime                              # do not act on this proposal after this instant
    source: str = "agent"                         # agent run id, or "human" for a hand-authored conviction bet
    created_at: datetime = Field(default_factory=_now)

    def edge_prob(self) -> Decimal:
        """The probability edge the proposal claims: how much cheaper-than-fair the price is, in [−1, 1]. For a
        BUY it's fair − price (you pay `price`, you think it's worth `fair`); for a SELL it's price − fair."""
        return (self.fair_prob - self.limit_price) if self.side == "buy" else (self.limit_price - self.fair_prob)

    def edge_bps(self) -> Decimal:
        """The claimed edge in basis points (probability edge × 1e4) — the headline number the gate's min-edge
        cap reads."""
        return self.edge_prob() * Decimal("10000")

    def is_expired(self, now: datetime | None = None) -> bool:
        return (now or _now()) > self.expiry
