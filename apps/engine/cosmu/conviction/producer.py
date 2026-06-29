# intent: the PRODUCER — the out-of-band step that turns the authority pipeline's output into the propose-only
# conviction queue and persists it. It is called by the voices pass (which already holds the claims, bars, posts
# and events) right after it computes the authority snapshot, so there is no second pipeline. Schema-probe gated
# via the store layer: when the `conviction_proposals` table is absent the upsert no-ops (honest-empty queue).
# PURE of money: it only builds + stores PROPOSALS; a human arms them. Offline-testable (inject the data + now).

from __future__ import annotations

from datetime import datetime

from cosmu.conviction.authority_source import AuthorityStateSource
from cosmu.conviction.lane import ConvictionLane
from cosmu.conviction.models import ConvictionCaps, ConvictionProposal
from cosmu.conviction.run import propose_from_authority
from cosmu.conviction.store import upsert_proposals
from cosmu.data.market import Bar
from cosmu.knowledge.store import Store
from cosmu.mind.authority import Event
from cosmu.mind.claims import Claim, VoicePost

# How many trailing bars define "recently" for the echo 'already moved?' check. A lean asset-level proxy: if the
# asset has already run hard in the call's direction over this window, the move is treated as played-out. Policy
# constant (the disconfirmer owns the magnitude threshold).
_ECHO_LOOKBACK_BARS = 7


def recent_returns(bars_by_entity: dict[str, list[Bar]], *, lookback_bars: int = _ECHO_LOOKBACK_BARS) -> dict[str, float]:
    """Per-entity signed return over the last `lookback_bars` bars — the echo 'has it already moved?' signal fed
    to the disconfirmer. Entities with too few bars are omitted (None → that arm of the echo check is skipped)."""
    out: dict[str, float] = {}
    for entity, bars in bars_by_entity.items():
        if not bars or len(bars) < lookback_bars + 1:
            continue
        ordered = sorted(bars, key=lambda b: b.ts)
        start = float(ordered[-(lookback_bars + 1)].close)
        end = float(ordered[-1].close)
        if start <= 0:
            continue
        out[entity] = (end - start) / start
    return out


def refresh_conviction_proposals(
    store: Store,
    *,
    claims: list[Claim],
    bars_by_entity: dict[str, list[Bar]],
    accounts: list[str],
    now: datetime,
    posts: list[VoicePost] | None = None,
    events: list[Event] | None = None,
    caps: ConvictionCaps | None = None,
    lane: ConvictionLane | None = None,
) -> list[ConvictionProposal]:
    """Build the propose-only conviction queue from the authority pipeline's inputs and upsert it. Returns the
    proposals (empty when no account clears the gate or the table is absent). NOTHING here arms or moves money."""
    caps = caps or ConvictionCaps()
    if not claims or not accounts:
        return []
    source = AuthorityStateSource.build(
        claims, bars_by_entity=bars_by_entity, posts=posts, events=events, as_of=now
    )
    proposals = propose_from_authority(
        source, accounts, caps=caps, now=now, recent_returns=recent_returns(bars_by_entity), lane=lane
    )
    upsert_proposals(store, proposals)
    return proposals
