# intent: recommendation feed + actions; inputs: rec ids; outputs: RecommendationsResponse / action results; invariants: money-adjacent approvals stay gated, never move real capital.

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from cosmu.api._shared import _json, ensure_recommendations, store
from cosmu.api.models import (
    Recommendation,
    RecommendationActionResponse,
    RecommendationsResponse,
)
from cosmu.knowledge.store import utcnow

router = APIRouter()


@router.get("/recommendations", response_model=RecommendationsResponse)
def recommendations() -> RecommendationsResponse:
    ensure_recommendations()
    rows = store.rows("SELECT * FROM recommendations ORDER BY ts DESC LIMIT 10")
    return RecommendationsResponse(
        items=[
            Recommendation(id=row["id"], ts=row["ts"], kind=row["kind"], body=row["body"], state=row["state"], payload=_json(row["payload"]))
            for row in rows
        ]
    )


@router.post("/recommendations/{rec_id}/approve", response_model=RecommendationActionResponse)
def recommendation_approve(rec_id: str) -> RecommendationActionResponse:
    """Approve a recommendation: mark it approved and apply the validated action via policy + audit. Money-adjacent
    recommendations (live/funding/cap moves) are recorded as a policy that STAYS GATED — approval here never moves
    real money; that still requires the explicit 2-click live arming + a passed gate."""
    row = store.row("SELECT * FROM recommendations WHERE id = ?", (rec_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="recommendation not found")
    if row["state"] != "open":
        return RecommendationActionResponse(ok=False, applied=False, reason=f"already {row['state']}")
    payload = _json(row["payload"]) or {}
    kind = row["kind"]
    money_adjacent = kind in {"live_promotion", "fund_capital", "cap_change"} or bool(payload.get("requires_money_move"))
    store.rows("UPDATE recommendations SET state = 'approved' WHERE id = ?", (rec_id,))
    # The approved action is applied as a research-routing policy (auditable); money-adjacent stays gated.
    store.insert(
        "policies",
        {
            "ts": utcnow(),
            "source": "recommendation",
            "raw_text": row["body"],
            "parsed": {"recommendation_id": rec_id, "kind": kind, "requires_money_move": money_adjacent},
            "scope": "policy",
            "applied": int(not money_adjacent),
            "applied_at": utcnow() if not money_adjacent else None,
        },
    )
    store.append_event(actor="human", kind="recommendation_approved", ref_type="recommendation", ref_id=rec_id, payload={"kind": kind, "applied": not money_adjacent})
    if money_adjacent:
        return RecommendationActionResponse(ok=True, applied=False, reason="money-adjacent — recorded but stays gated until live is armed")
    return RecommendationActionResponse(ok=True, applied=True)


@router.post("/recommendations/{rec_id}/dismiss", response_model=RecommendationActionResponse)
def recommendation_dismiss(rec_id: str) -> RecommendationActionResponse:
    row = store.row("SELECT state FROM recommendations WHERE id = ?", (rec_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="recommendation not found")
    store.rows("UPDATE recommendations SET state = 'dismissed' WHERE id = ?", (rec_id,))
    store.append_event(actor="human", kind="recommendation_dismissed", ref_type="recommendation", ref_id=rec_id)
    return RecommendationActionResponse(ok=True)
