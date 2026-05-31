# intent: route model work through configured tiers and spend caps; inputs: task difficulty/confidence/budget; outputs: model tier decision; invariants: OpenRouter only, cheapest sufficient tier, no secret values in task payloads.

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from cosmu.config.settings import SpendSettings


class RouteRequest(BaseModel):
    task: str
    difficulty: Literal["cheap", "mid", "frontier"]
    confidence: Decimal = Decimal("1")
    estimated_cost: Decimal


class RouteDecision(BaseModel):
    accepted: bool
    tier: Literal["cheap", "mid", "frontier"] | None
    reason: str


ORDER: tuple[str, ...] = ("cheap", "mid", "frontier")


def route_model(request: RouteRequest, spend: SpendSettings, spent_today: Decimal) -> RouteDecision:
    if spent_today + request.estimated_cost > spend.daily_cap_usd:
        return RouteDecision(accepted=False, tier=None, reason="daily_cap_exhausted")
    target_index = ORDER.index(request.difficulty)
    if request.confidence < Decimal("0.55") and target_index < len(ORDER) - 1:
        target_index += 1
    return RouteDecision(accepted=True, tier=ORDER[target_index], reason="routed")

