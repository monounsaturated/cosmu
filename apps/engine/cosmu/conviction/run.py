# intent: the ORCHESTRATION — fan an AuthoritySource over a set of followed accounts and emit the propose-only
# conviction proposals for the fresh, actionable, non-echo calls. PURE + offline + deterministic: same inputs →
# same proposals (idempotent ids). Optionally routes each proposal through the conviction lane seam (still
# propose-only). NOTHING here arms or moves money. This is the function the producer (out-of-band, in the voices
# pass) and the tests call.

from __future__ import annotations

from datetime import datetime

from cosmu.conviction.authority_source import AuthoritySource
from cosmu.conviction.lane import ConvictionLane, route_to_conviction_lane
from cosmu.conviction.models import ConvictionCaps, ConvictionProposal
from cosmu.conviction.template import AuthorityConvictionTemplate


def propose_from_authority(
    source: AuthoritySource,
    accounts: list[str],
    *,
    caps: ConvictionCaps | None = None,
    now: datetime,
    recent_returns: dict[str, float] | None = None,
    lane: ConvictionLane | None = None,
) -> list[ConvictionProposal]:
    """For each followed account: read its authority, and for each of its fresh calls run the per-account template
    → a propose-only proposal when (authority gate + EV gate + disconfirmer + sizing) all pass. `recent_returns`
    maps asset → its signed recent move (the echo 'already over?' signal); missing assets pass None (echo check
    falls back to primacy/lead-lag). When `lane` is given, each emitted proposal is also submitted to it (still
    propose-only). Returns the proposals, highest authority first."""
    caps = caps or ConvictionCaps()
    recent_returns = recent_returns or {}
    out: list[ConvictionProposal] = []
    for account in accounts:
        authority = source.account_authority(account)
        if authority is None:
            continue  # untested / unknown account — honest skip
        template = AuthorityConvictionTemplate(account=account, caps=caps)
        for call in source.fresh_calls(account, now=now, max_age_hours=caps.expiry_hours):
            decision = template.propose(
                authority=authority,
                call=call,
                now=now,
                recent_return=recent_returns.get(call.asset),
            )
            if decision.proposal is not None:
                if lane is not None:
                    route_to_conviction_lane(decision.proposal, lane)
                out.append(decision.proposal)
    return sorted(out, key=lambda p: (-p.authority_score, p.asset, p.proposal_id))
