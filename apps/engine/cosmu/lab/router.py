# intent: route model work through configured tiers and spend caps AND wire the actual model call; inputs: task
# difficulty/confidence/budget + a brief + an injectable chat seam; outputs: a tier decision and (when a key is
# set) a STRUCTURED, schema-validated LlmProposal; invariants: OpenRouter only, cheapest sufficient tier, no
# secret values in task payloads, the model only PROPOSES structure (the deterministic Gate alone disposes), and
# everything is LLM-OPTIONAL + OFFLINE-testable (no key/seam → no call, the caller uses the deterministic path).

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from cosmu.config.settings import SpendSettings
from cosmu.lab.llm import ChatFn, ProposalResult, openrouter_chat, propose_structure


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

# Tier → OpenRouter model id. The router already decides the TIER from difficulty/confidence/budget; this maps
# that decision onto the actual model the LLM seam calls. Cheapest sufficient tier wins (the ROI lens).
TIER_MODELS: dict[str, str] = {
    "cheap": "openai/gpt-4o-mini",
    "mid": "anthropic/claude-3.5-sonnet",
    "frontier": "anthropic/claude-3.7-sonnet",
}


def route_model(request: RouteRequest, spend: SpendSettings, spent_today: Decimal) -> RouteDecision:
    if spent_today + request.estimated_cost > spend.daily_cap_usd:
        return RouteDecision(accepted=False, tier=None, reason="daily_cap_exhausted")
    target_index = ORDER.index(request.difficulty)
    if request.confidence < Decimal("0.55") and target_index < len(ORDER) - 1:
        target_index += 1
    return RouteDecision(accepted=True, tier=ORDER[target_index], reason="routed")


def route_and_propose(
    brief: str,
    *,
    valid_features: list[str],
    spend: SpendSettings,
    spent_today: Decimal = Decimal("0"),
    difficulty: Literal["cheap", "mid", "frontier"] = "mid",
    confidence: Decimal = Decimal("1"),
    estimated_cost: Decimal = Decimal("0.02"),
    api_key: str | None = None,
    chat: ChatFn | None = None,
) -> ProposalResult:
    """Compose the tier router with the REAL model call: decide the tier under the spend cap, map it to a model
    id, then ask that model for a STRUCTURED, schema-validated proposal. The HTTP transport is injectable
    (`chat`) so CI runs offline; with no key the default OpenRouter seam yields None → deterministic fallback.
    The proposal is STRUCTURE only — the deterministic Gate still disposes."""
    decision = route_model(
        RouteRequest(task="author", difficulty=difficulty, confidence=confidence, estimated_cost=estimated_cost),
        spend,
        spent_today,
    )
    if not decision.accepted or decision.tier is None:
        return ProposalResult(proposal=None, model_id=None, attempts=0, notes=[f"router declined: {decision.reason}"])
    model_id = TIER_MODELS[decision.tier]
    seam = chat if chat is not None else openrouter_chat(api_key)
    result = propose_structure(brief, model_id=model_id, valid_features=valid_features, chat=seam)
    result.notes.insert(0, f"router tier={decision.tier} model={model_id}")
    return result

