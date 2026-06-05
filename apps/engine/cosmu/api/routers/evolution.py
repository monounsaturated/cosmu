# intent: run an evolution cohort; inputs: CohortRunRequest; outputs: CohortSummaryResponse; invariants: refuses to run without a live data path.

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from cosmu.api._shared import _summary_to_response, settings, store
from cosmu.api.models import CohortRunRequest, CohortSummaryResponse
from cosmu.evolution.loop import FarmLoop
from cosmu.spine.universe import has_live_data

router = APIRouter()


@router.post("/evolution/run", response_model=CohortSummaryResponse)
def evolution_run(request: CohortRunRequest) -> CohortSummaryResponse:
    if not has_live_data(store):
        raise HTTPException(
            status_code=400,
            detail="No venue with a live data path is enabled. Enable Binance (Crypto) in Settings to run cohorts.",
        )
    loop = FarmLoop(settings=settings, store=store)
    summary = loop.run_cohort(
        seed=request.seed,
        cohort_size=request.cohort_size,
        explore_pct=request.explore_pct,
        pine_scripts=request.pine_scripts,
    )
    return _summary_to_response(summary)
