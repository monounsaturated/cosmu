# intent: the CLEAN interface the conviction consumer reads — an account's authority composite (AccountAuthority)
# and its fresh actionable calls (AssetCall) — plus the ADAPTER that maps the in-tree authority scaffolding
# (cosmu/mind/authority.py's AuthorityState + Phase-2 ResolvedClaims) onto it. Decoupling here is deliberate: the
# consumer (sizing / disconfirmer / template) depends ONLY on this interface, so when the shipped cosmu/authority/
# package lands with its own AuthorityScore, we swap THIS adapter and nothing downstream changes. PURE + offline.
#
# The authority COMPOSITE we gate + size on is the deterministic, panel-size-independent `skill` (deflated Brier-
# skill vs base, sample-shrunk) — a spammer who only reproduces the base rate scores ~0 and never clears the gate,
# while a genuinely-calibrated voice scores high. The citation-PageRank `author_authority` (influence) is carried
# alongside for the human, NOT used as the gate (influence != authority). EV-per-call (excess-hit × magnitude) is
# the PROFIT axis — it makes a few-but-huge caller worth a bigger bet on its big calls (profit > hit-rate).

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from cosmu.conviction.models import TopMover
from cosmu.data.market import Bar
from cosmu.mind.authority import AuthorityState, Event, compute_authority
from cosmu.mind.claims import Claim, VoicePost
from cosmu.mind.outcomes import ResolvedClaim, resolve_claims

_MAX_TOP_MOVERS = 3


@dataclass(frozen=True)
class AccountAuthority:
    """An account's authority snapshot — exactly what the consumer needs to gate + size a conviction bet. Maps
    1:1 onto the shipped cosmu/authority/ AuthorityScore (composite EV + Brier + magnitude + top-3 movers); here
    it is adapted from the in-tree AuthorityState + track record."""

    account: str
    authority_score: float       # the composite the lane gates + sizes on (here: skill — deterministic [0,1])
    skill: float                 # deflated Brier-skill vs base, sample-shrunk
    ev_per_call: float           # excess_hit_rate × avg_hit_magnitude — the profit proxy (>= 0)
    brier_skill_score: float
    avg_hit_magnitude: float
    n_resolved: int
    citation_authority: float    # citation-PageRank (influence), carried for display — NOT the gate
    top_movers: tuple[TopMover, ...]


@dataclass(frozen=True)
class AssetCall:
    """A fresh directional call by an account on one asset — distilled from a Claim + its primacy/lead-lag
    context. The disconfirmer + template decide whether it becomes a proposal."""

    account: str
    asset: str            # the claim's entity, e.g. "BTC"
    direction: str        # "up" | "down" | "flat" (claim vocabulary; only up/down are actionable)
    conviction: float     # how strongly the call was asserted [0, 1]
    ts: datetime          # the call's point-in-time availability (== the post's ts)
    quote: str            # the verbatim post text
    url: str              # provenance
    is_primary: bool      # primacy: first to make this (entity, direction) call (not an echo)
    lead_lag: str         # "evidence" | "echo" | "none"


class AuthoritySource(Protocol):
    """What the consumer needs from 'whatever computes authority'. Two reads: the account's authority composite,
    and its fresh actionable calls in a recency window. Honest: an unknown / untested account → None / []."""

    def account_authority(self, account: str) -> AccountAuthority | None: ...

    def fresh_calls(self, account: str, *, now: datetime, max_age_hours: float) -> list[AssetCall]: ...


@dataclass
class AuthorityStateSource:
    """The ADAPTER over the in-tree authority scaffolding. Holds a point-in-time AuthorityState (Phase-3) and the
    Phase-2 ResolvedClaims (for the top-movers evidence). Build it from raw claims+bars via `.build(...)`, or
    inject a precomputed state+resolved (tests). When cosmu/authority/ ships, replace this class — the consumer is
    unaffected."""

    state: AuthorityState
    resolved: list[ResolvedClaim]

    @classmethod
    def build(
        cls,
        claims: list[Claim],
        *,
        bars_by_entity: dict[str, list[Bar]],
        posts: list[VoicePost] | None = None,
        events: list[Event] | None = None,
        as_of: datetime,
    ) -> AuthorityStateSource:
        """Compute the authority snapshot + resolved claims from the raw inputs, as-of a time (no look-ahead)."""
        state = compute_authority(claims, bars_by_entity=bars_by_entity, posts=posts, events=events, as_of=as_of)
        resolved = resolve_claims(claims, bars_by_entity, now=as_of)
        return cls(state=state, resolved=resolved)

    def account_authority(self, account: str) -> AccountAuthority | None:
        rec = self.state.track_records.get(account)
        if rec is None:
            return None
        # EV proxy = how often the account beats the base rate × how big its correct moves are. Floored at 0 so a
        # below-base-rate account contributes no positive EV (it will also fail the skill gate). This is the
        # PROFIT axis that lets a few-but-huge caller size bigger than an equally-calibrated small-move caller.
        ev = max(0.0, rec.excess_hit_rate) * rec.avg_hit_magnitude
        return AccountAuthority(
            account=account,
            authority_score=rec.skill,
            skill=rec.skill,
            ev_per_call=ev,
            brier_skill_score=rec.brier_skill_score,
            avg_hit_magnitude=rec.avg_hit_magnitude,
            n_resolved=rec.n_resolved,
            citation_authority=self.state.author_authority.get(account, 0.0),
            top_movers=self._top_movers(account),
        )

    def fresh_calls(self, account: str, *, now: datetime, max_age_hours: float) -> list[AssetCall]:
        """The account's calls inside [now - max_age_hours, now], newest first. Point-in-time: never a call from
        after `now`. Each carries its primacy + lead-lag so the disconfirmer can spot an echo."""
        cutoff = now - timedelta(hours=max_age_hours)
        out: list[AssetCall] = []
        for ctx in self.state.contexts:
            c = ctx.claim
            if c.handle != account or c.ts > now or c.ts < cutoff:
                continue
            out.append(
                AssetCall(
                    account=account,
                    asset=c.entity,
                    direction=c.direction,
                    conviction=c.conviction,
                    ts=c.ts,
                    quote=c.quote,
                    url=c.url,
                    is_primary=ctx.is_primary,
                    lead_lag=ctx.lead_lag,
                )
            )
        return sorted(out, key=lambda k: (k.ts, k.asset), reverse=True)

    def _top_movers(self, account: str) -> tuple[TopMover, ...]:
        """The account's top correct, resolved calls by magnitude — the 'has it called big moves before' evidence."""
        rows = [
            r
            for r in self.resolved
            if r.claim.handle == account and r.status == "resolved" and r.hit and r.realized_return is not None
        ]
        rows.sort(key=lambda r: abs(r.realized_return or 0.0), reverse=True)
        return tuple(
            TopMover(
                entity=r.claim.entity,
                direction=r.claim.direction,
                realized_return=float(r.realized_return or 0.0),
                ts=r.claim.ts,
            )
            for r in rows[:_MAX_TOP_MOVERS]
        )
