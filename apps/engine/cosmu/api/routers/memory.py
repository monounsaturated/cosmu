# intent: long-term memory insights (graveyard/research RAG); inputs: none; outputs: MemoryInsightsResponse; invariants: read straight off persisted notes — no recompute, no LLM.

from __future__ import annotations

from fastapi import APIRouter

from cosmu.api._shared import store
from cosmu.api.models import MemoryInsight, MemoryInsightsResponse

router = APIRouter()


@router.get("/memory/insights", response_model=MemoryInsightsResponse)
def memory_insights_route() -> MemoryInsightsResponse:
    """What the brain has LEARNED from long-term memory (graveyard/research RAG): dead-end structures to avoid +
    winning patterns to reuse. Read straight off the persisted notes — no recompute, no LLM."""
    from cosmu.knowledge.memory import memory_insights

    return MemoryInsightsResponse(
        insights=[MemoryInsight(kind=i["kind"], text=i["text"], ref=i["ref"]) for i in memory_insights(store)]
    )
