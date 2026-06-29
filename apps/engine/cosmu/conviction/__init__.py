# intent: the AUTHORITY-CONVICTION CONSUMER — turn a HIGH-AUTHORITY account's fresh, actionable asset-calls into
# propose-only LLM/Conviction trade proposals (asset, direction, size, max-loss, expiry + the authority evidence).
# This is the consumer half of the Authority feature: Authority SCORES accounts (cosmu/mind/authority.py — the
# in-tree scaffolding the shipped cosmu/authority/ package supersedes); this package READS that score and, when a
# followed account posts a fresh directional call, emits a sized, capped conviction proposal. It routes through the
# LLM/Conviction lane (guardrails + hard max-loss cap + small size + HUMAN-armed) — NOT the deterministic quant
# Gate. NOTHING here arms or moves money: every proposal is status='proposed' and a human reviews + arms it.
#
# The pieces (each a small module): models (the proposal + caps + evidence), authority_source (the clean interface
# to the authority score + the adapter over the in-tree AuthorityState), sizing (authority×EV → a capped bet),
# disconfirmer (echo + actionability), template (the per-account subscriber that emits a proposal), lane (the
# clean STUB interface to master/conviction.py until it merges), run (the orchestration).

from __future__ import annotations

from cosmu.conviction.authority_source import (
    AccountAuthority,
    AssetCall,
    AuthoritySource,
    AuthorityStateSource,
)
from cosmu.conviction.disconfirmer import DisconfirmResult, disconfirm
from cosmu.conviction.lane import ConvictionLane, InMemoryConvictionLane, route_to_conviction_lane
from cosmu.conviction.models import (
    AuthorityEvidence,
    ConvictionCaps,
    ConvictionProposal,
    Direction,
    TopMover,
)
from cosmu.conviction.producer import recent_returns, refresh_conviction_proposals
from cosmu.conviction.run import propose_from_authority
from cosmu.conviction.sizing import conviction_weight, size_conviction
from cosmu.conviction.store import read_proposals, upsert_proposals
from cosmu.conviction.template import AuthorityConvictionTemplate, ProposalDecision

__all__ = [
    "AccountAuthority",
    "AssetCall",
    "AuthorityConvictionTemplate",
    "AuthorityEvidence",
    "AuthoritySource",
    "AuthorityStateSource",
    "ConvictionCaps",
    "ConvictionLane",
    "ConvictionProposal",
    "DisconfirmResult",
    "Direction",
    "InMemoryConvictionLane",
    "ProposalDecision",
    "TopMover",
    "conviction_weight",
    "disconfirm",
    "propose_from_authority",
    "read_proposals",
    "recent_returns",
    "refresh_conviction_proposals",
    "route_to_conviction_lane",
    "size_conviction",
    "upsert_proposals",
]
