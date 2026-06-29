# intent: the CONVICTION STRATEGY TEMPLATE — a per-account subscriber. It follows ONE account; when that account
# (whose authority composite must clear the threshold) posts a FRESH, actionable, non-echo directional call, it
# emits ONE propose-only ConvictionProposal sized by authority × EV under the hard caps. Everything is checked in
# the open and the decision carries its REASONS, so the UI can show why a call did or did not become a proposal.
# NOTHING here arms or moves money — the proposal's status is 'proposed' and a human arms it (off this path). The
# LLM is upstream (it extracted the call); this template is pure, deterministic plumbing.

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from cosmu.conviction.authority_source import AccountAuthority, AssetCall
from cosmu.conviction.disconfirmer import disconfirm
from cosmu.conviction.models import (
    AuthorityEvidence,
    ConvictionCaps,
    ConvictionProposal,
    Direction,
    TopMover,
    make_proposal_id,
)
from cosmu.conviction.sizing import size_conviction

_DIRECTION = {"up": Direction.LONG, "down": Direction.SHORT}


@dataclass(frozen=True)
class ProposalDecision:
    """The outcome of evaluating one call: the proposal (or None) + the reasons. A None proposal with reasons is
    the HONEST 'we looked and declined, here's why' — never a silent drop."""

    proposal: ConvictionProposal | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class AuthorityConvictionTemplate:
    """A conviction strategy bound to ONE followed account. `propose` turns a single fresh call into a decision.
    The account-authority gate (composite >= caps.min_authority) is the first guard; then EV, then the
    disconfirmer (actionable + not echo); then sizing under the caps. The result is propose-only."""

    account: str
    caps: ConvictionCaps = field(default_factory=ConvictionCaps)

    def propose(
        self,
        *,
        authority: AccountAuthority,
        call: AssetCall,
        now: datetime,
        recent_return: float | None = None,
    ) -> ProposalDecision:
        """Evaluate ONE fresh call → a ConvictionProposal or a reasoned decline. `recent_return` is the asset's
        signed move since the call (the echo 'already over?' signal); pass None when unknown."""
        # 0. The call must belong to THIS account (the template is per-account).
        if call.account != self.account:
            return ProposalDecision(None, ("wrong_account",))

        # 1. Authority gate — the account's composite must clear the threshold (a spammer with skill ~0 never does).
        if authority.authority_score < self.caps.min_authority:
            return ProposalDecision(
                None, (f"below_min_authority({authority.authority_score:.3f}<{self.caps.min_authority:.3f})",)
            )
        # 2. EV gate — no negative-edge account (profit axis must be non-negative).
        if authority.ev_per_call < self.caps.min_ev:
            return ProposalDecision(None, (f"below_min_ev({authority.ev_per_call:.4f}<{self.caps.min_ev:.4f})",))

        # 3. Freshness — a call older than the actionable window has gone stale (the market has moved on).
        age_hours = (now - call.ts).total_seconds() / 3600.0
        if age_hours > self.caps.expiry_hours or call.ts > now:
            return ProposalDecision(None, (f"stale_call({age_hours:.1f}h>{self.caps.expiry_hours:.1f}h)",))

        # 4. Disconfirmer — actionable (confident, directional, not sarcasm) AND not an echo (move not over).
        dis = disconfirm(call, recent_return=recent_return, min_conviction=self.caps.min_conviction)
        if not dis.passes:
            return ProposalDecision(None, dis.reasons)

        # 5. Size by authority × EV, under the hard caps. A zero-weight size means no bet.
        size, max_loss = size_conviction(authority, self.caps)
        if size <= 0:
            return ProposalDecision(None, ("size_zero",))

        direction = _DIRECTION[call.direction]
        evidence = self._evidence(authority, call)
        proposal = ConvictionProposal(
            proposal_id=make_proposal_id(self.account, call.asset, direction, call.ts),
            account=self.account,
            asset=call.asset,
            direction=direction,
            size_usd=size,
            max_loss_usd=max_loss,
            expiry=call.ts + timedelta(hours=self.caps.expiry_hours),
            thesis=self._thesis(authority, call, direction),
            evidence=evidence,
            created_at=now,
            status="proposed",
        )
        return ProposalDecision(proposal, ("pass",))

    def _evidence(self, authority: AccountAuthority, call: AssetCall) -> AuthorityEvidence:
        return AuthorityEvidence(
            account=self.account,
            authority_score=authority.authority_score,
            skill=authority.skill,
            ev_per_call=authority.ev_per_call,
            brier_skill_score=authority.brier_skill_score,
            avg_hit_magnitude=authority.avg_hit_magnitude,
            n_resolved=authority.n_resolved,
            citation_authority=authority.citation_authority,
            top_movers=authority.top_movers,
            source_quote=call.quote,
            source_url=call.url,
            is_primary=call.is_primary,
            lead_lag=call.lead_lag,
        )

    def _thesis(self, authority: AccountAuthority, call: AssetCall, direction: Direction) -> str:
        movers = _summarize_movers(authority.top_movers)
        return (
            f"{self.account} called {call.asset} {call.direction} (conviction {call.conviction:.2f}). "
            f"Authority composite {authority.authority_score:.2f} (skill {authority.skill:.2f}, "
            f"EV/call {authority.ev_per_call:.3f}, {authority.n_resolved} resolved calls, "
            f"citation-authority {authority.citation_authority:.2f}). "
            f"Primacy={'first' if call.is_primary else 'echo'}, lead-lag={call.lead_lag}. "
            f"Proposing a {direction.value} conviction bet for human review.{movers}"
        )


def _summarize_movers(movers: tuple[TopMover, ...]) -> str:
    if not movers:
        return ""
    parts = [f"{m.entity} {m.direction} {m.realized_return:+.1%}" for m in movers]
    return " Top prior calls: " + ", ".join(parts) + "."
