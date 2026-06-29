# intent: the typed domain objects of the authority-conviction lane — the propose-only ConvictionProposal (an
# ASSET call: asset, direction, size, max-loss, expiry + the authority evidence), the hard money envelope
# (ConvictionCaps), and the evidence carried for the human reviewer. NO LLM, no I/O — pure data. The proposal's
# `status` is FROZEN at 'proposed': nothing in this lane arms it (a human does, off this path), so a proposal can
# at worst sit in the review queue. Mirrors the snipe lane's "LLM proposes, deterministic disposes, human arms"
# discipline but for a directional asset bet rather than a Polymarket outcome.

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Literal

# Reuse the snipe lane's autonomy dial — ONE vocabulary for "how autonomous". Even the most autonomous mode never
# lets the LLM fire; here we only ever build PROPOSE_ONLY proposals (the human arms). Importing it (rather than
# redefining) keeps the two conviction lanes coherent.
from cosmu.snipe.gate import ExecutionMode

_CENTS = Decimal("0.01")


def _q(value: Decimal) -> Decimal:
    """Quantize a USD amount to cents (deterministic, half-even)."""
    return value.quantize(_CENTS)


class Direction(str, Enum):
    """A directional asset bet. An account's 'up' call → LONG, 'down' → SHORT (a 'flat'/neutral call is not
    actionable and never becomes a proposal — see disconfirmer)."""

    LONG = "long"
    SHORT = "short"


@dataclass(frozen=True)
class TopMover:
    """One of the account's prior CORRECT, resolved calls — a piece of the evidence its authority is built on.
    `realized_return` is the signed move the call caught; the human sees these to judge 'has this account actually
    called big moves before'."""

    entity: str
    direction: str          # "up" | "down" (the resolved claim's direction)
    realized_return: float  # signed return the call realized over its horizon
    ts: datetime


@dataclass(frozen=True)
class AuthorityEvidence:
    """Why this account, why now — the thesis evidence shown to the human reviewer. Carries the account's
    authority composite (skill-anchored), its EV/magnitude profile (profit, not just hit-rate), the source post,
    and the disconfirmer context (primacy / lead-lag). The proposal is only as trustworthy as this evidence."""

    account: str
    authority_score: float       # the authority composite the lane gates + sizes on (skill-anchored, [0,1])
    skill: float                 # deterministic deflated Brier-skill vs base, sample-shrunk ([0,1])
    ev_per_call: float           # excess_hit_rate × avg_hit_magnitude — the PROFIT proxy (magnitude, not hit-rate)
    brier_skill_score: float     # > 0 beats the base rate
    avg_hit_magnitude: float     # mean |move| on the account's correct calls
    n_resolved: int              # how many calls have been scored against the tape (sample behind the score)
    citation_authority: float    # citation-PageRank (influence) — shown alongside, NOT the gate
    top_movers: tuple[TopMover, ...]  # up to 3 prior correct big calls
    source_quote: str            # the verbatim post the call was extracted from
    source_url: str              # provenance
    is_primary: bool             # primacy: this call is FIRST (not an echo of an earlier identical call)
    lead_lag: str                # "evidence" (led an event) | "echo" (reacted) | "none"


@dataclass(frozen=True)
class ConvictionCaps:
    """The hard money envelope for the authority-conviction lane — small, conservative defaults. Live can only
    ever move money INSIDE these, and even then only after a human arms a proposal (mode stays PROPOSE_ONLY here).
    `max_loss_usd` is the absolute hard stop: a proposal can NEVER carry a max-loss above it, whatever the size."""

    per_bet_usd: Decimal = Decimal("25")     # max stake on any one conviction bet
    max_loss_usd: Decimal = Decimal("15")    # HARD max-loss cap — a proposal's max-loss is always <= this
    floor_usd: Decimal = Decimal("2")        # below this a bet isn't worth proposing
    min_authority: float = 0.15              # the account's authority composite must clear this to be followed
    min_ev: float = 0.0                      # require a non-negative EV proxy (no negative-edge accounts)
    min_conviction: float = 0.4              # the call itself must be asserted at least this strongly
    stop_loss_frac: float = 0.5              # directional stop: max-loss = size × this, then capped to max_loss_usd
    expiry_hours: float = 24.0               # a fresh call is actionable for this long after it was posted
    mode: ExecutionMode = ExecutionMode.PROPOSE_ONLY  # surface only; the human arms (never auto-fires)


@dataclass(frozen=True)
class ConvictionProposal:
    """ONE propose-only authority-conviction bet for a human to review + arm. Carries everything the reviewer
    needs: the asset + direction, the capped size + hard max-loss, the expiry, the human-readable thesis, and the
    full authority evidence. `status` is FROZEN at 'proposed' — this lane has no arm path; arming is an explicit,
    separate human action. So a hallucinated or stale proposal can at worst sit unarmed in the queue."""

    proposal_id: str
    account: str                 # the source account being followed
    asset: str                   # the asset the call is about (entity, e.g. "BTC")
    direction: Direction
    size_usd: Decimal            # the conviction stake, sized by authority × EV, capped to per_bet_usd
    max_loss_usd: Decimal        # the hard stop — always <= caps.max_loss_usd
    expiry: datetime             # do not act after this instant
    thesis: str                  # the economic WHY, in plain language (built from the evidence)
    evidence: AuthorityEvidence
    created_at: datetime
    status: Literal["proposed"] = "proposed"  # NEVER armed from this path
    source: str = "authority-conviction"

    def is_expired(self, now: datetime | None = None) -> bool:
        return (now or datetime.now(tz=UTC)) >= self.expiry

    @property
    def authority_score(self) -> float:
        """The account's authority composite — surfaced top-level so the lane/UI can rank proposals by it."""
        return self.evidence.authority_score

    def to_dict(self) -> dict:
        """Serialize for persistence / the API. Decimals → str (exactness), datetimes → ISO."""
        ev = self.evidence
        return {
            "proposal_id": self.proposal_id,
            "account": self.account,
            "asset": self.asset,
            "direction": self.direction.value,
            "size_usd": str(self.size_usd),
            "max_loss_usd": str(self.max_loss_usd),
            "expiry": self.expiry.isoformat(),
            "thesis": self.thesis,
            "created_at": self.created_at.isoformat(),
            "status": self.status,
            "source": self.source,
            "authority_score": ev.authority_score,
            "evidence": {
                "account": ev.account,
                "authority_score": ev.authority_score,
                "skill": ev.skill,
                "ev_per_call": ev.ev_per_call,
                "brier_skill_score": ev.brier_skill_score,
                "avg_hit_magnitude": ev.avg_hit_magnitude,
                "n_resolved": ev.n_resolved,
                "citation_authority": ev.citation_authority,
                "is_primary": ev.is_primary,
                "lead_lag": ev.lead_lag,
                "source_quote": ev.source_quote,
                "source_url": ev.source_url,
                "top_movers": [
                    {
                        "entity": m.entity,
                        "direction": m.direction,
                        "realized_return": m.realized_return,
                        "ts": m.ts.isoformat(),
                    }
                    for m in ev.top_movers
                ],
            },
        }


def make_proposal_id(account: str, asset: str, direction: Direction, call_ts: datetime) -> str:
    """A deterministic id from (account, asset, direction, call timestamp) — so re-running a pass over the SAME
    call yields the SAME proposal_id (idempotent upsert, no duplicate proposals), with no clock/randomness."""
    raw = f"{account}|{asset}|{direction.value}|{call_ts.isoformat()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]  # noqa: S324 — id only, not security


def quantize_usd(value: Decimal) -> Decimal:
    """Public cents-quantizer (sizing emits cent-exact USD)."""
    return _q(value)
