# intent: spine backtest trigger; inputs: none; outputs: run summary dict; invariants: sim-only, never arms live.

from __future__ import annotations

from fastapi import APIRouter

from cosmu.api._shared import settings
from cosmu.spine.engine import EngineFacade

router = APIRouter()


@router.post("/spine/backtest")
def spine_backtest() -> dict[str, str | int | bool]:
    return EngineFacade.create(settings).run_backtest(seed=13)
