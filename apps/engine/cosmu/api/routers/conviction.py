# intent: serve the AUTHORITY-CONVICTION review queue — GET /conviction/proposals returns the propose-only
# conviction trade proposals (built by the voices-pass producer from high-authority accounts' fresh asset-calls)
# for a HUMAN to review + arm. inputs: none; outputs: ConvictionProposalsResponse; invariants: READ-ONLY +
# PROPOSE-ONLY — there is NO arm/execute route here; a proposal's status is always 'proposed' and arming is a
# separate human action off this surface. Honest-empty queue (count 0) when nothing produced or the table is
# absent (pre-migration prod) — never a fabricated proposal. No LLM, no money on this path.

from __future__ import annotations

from fastapi import APIRouter

from cosmu.api._shared import store
from cosmu.api.models import (
    ConvictionEvidence,
    ConvictionProposalRow,
    ConvictionProposalsResponse,
    ConvictionTopMover,
)

router = APIRouter()


@router.get("/conviction/proposals", response_model=ConvictionProposalsResponse)
def conviction_proposals(limit: int = 50) -> ConvictionProposalsResponse:
    """The conviction review queue — highest-authority first. Each row carries the asset + direction, the capped
    size + hard max-loss + expiry, the plain-language thesis, and the full authority evidence (composite + EV +
    top-3 movers + the source post) so the operator can review before arming. PROPOSE-ONLY: nothing here arms or
    moves money. Defensive like /mind/credibility — a not-yet-migrated prod (no `conviction_proposals` table) or
    an unfilled queue yields count=0, never an error and never a fabricated row."""
    from cosmu.conviction.store import read_proposals

    proposals = read_proposals(store, limit=limit)
    rows = [
        ConvictionProposalRow(
            proposal_id=p.proposal_id,
            account=p.account,
            asset=p.asset,
            direction=p.direction.value,
            size_usd=str(p.size_usd),
            max_loss_usd=str(p.max_loss_usd),
            authority_score=p.authority_score,
            expiry=p.expiry.isoformat(),
            thesis=p.thesis,
            status=p.status,
            source=p.source,
            created_at=p.created_at.isoformat(),
            evidence=ConvictionEvidence(
                account=p.evidence.account,
                authority_score=p.evidence.authority_score,
                skill=p.evidence.skill,
                ev_per_call=p.evidence.ev_per_call,
                brier_skill_score=p.evidence.brier_skill_score,
                avg_hit_magnitude=p.evidence.avg_hit_magnitude,
                n_resolved=p.evidence.n_resolved,
                citation_authority=p.evidence.citation_authority,
                is_primary=p.evidence.is_primary,
                lead_lag=p.evidence.lead_lag,
                source_quote=p.evidence.source_quote,
                source_url=p.evidence.source_url,
                top_movers=[
                    ConvictionTopMover(
                        entity=m.entity,
                        direction=m.direction,
                        realized_return=m.realized_return,
                        ts=m.ts.isoformat(),
                    )
                    for m in p.evidence.top_movers
                ],
            ),
        )
        for p in proposals
    ]
    return ConvictionProposalsResponse(count=len(rows), armed=False, proposals=rows)
