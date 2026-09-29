# intent: system-intelligence read-out ("is the machine getting smarter?"); inputs: none; outputs: IntelligenceResponse; invariants: read-only; computed by api/intelligence.py.

from __future__ import annotations

from fastapi import APIRouter

from cosmu.api._shared import store
from cosmu.api.models import IntelligenceResponse

router = APIRouter()


@router.get("/intelligence", response_model=IntelligenceResponse)
def intelligence() -> IntelligenceResponse:
    from cosmu.api.intelligence import compute_intelligence

    return IntelligenceResponse(**compute_intelligence(store))
