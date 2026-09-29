# intent: pine translation endpoints; inputs: pine source; outputs: typed spec previews; invariants: translate-only, never persists or funds.

from __future__ import annotations

from fastapi import APIRouter

from cosmu.api.models import (
    PineSample,
    PineSamplesResponse,
    PineTranslateRequest,
    PineTranslateResponse,
)
from cosmu.strategy.pine import translate_pine
from cosmu.strategy.pine_samples import PINE_SAMPLES

router = APIRouter()


@router.post("/strategy/pine", response_model=PineTranslateResponse)
def strategy_pine(request: PineTranslateRequest) -> PineTranslateResponse:
    tr = translate_pine(request.source)
    return PineTranslateResponse(
        name=tr.spec.name,
        param_count=len(tr.spec.param_space),
        indicators=tr.indicators,
        conditions=tr.conditions,
        notes=tr.notes,
        lifted_params=tr.lifted_params,
        spec=tr.spec.model_dump(mode="json"),
    )


@router.get("/strategy/pine/samples", response_model=PineSamplesResponse)
def strategy_pine_samples() -> PineSamplesResponse:
    return PineSamplesResponse(samples=[PineSample(name=name, source=source) for name, source in PINE_SAMPLES.items()])
