# intent: route model work through configured tiers and spend caps AND wire the actual model call; inputs: task
# difficulty/confidence/budget + a brief + an injectable chat seam; outputs: a tier decision and (when a key is
# set) a STRUCTURED, schema-validated LlmProposal; invariants: OpenRouter only, cheapest sufficient tier, no
# secret values in task payloads, the model only PROPOSES structure (the deterministic Gate alone disposes), and
# everything is LLM-OPTIONAL + OFFLINE-testable (no key/seam → no call, the caller uses the deterministic path).

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel

from cosmu.config.settings import SpendSettings
from cosmu.lab.llm import OPENROUTER_URL, XAI_URL, ChatFn, ProposalResult, openrouter_chat, propose_structure

if TYPE_CHECKING:
    pass


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

# Tier → OpenRouter model id. The router decides the TIER from difficulty/confidence/budget; this maps that
# decision onto the actual model the LLM seam calls. Cheapest sufficient tier wins (the ROI lens).
# COST POLICY: all three tiers use OpenRouter ":free" models → $0 spend on the 24/7 loop (the account's >=$10
# top-up unlocks 1000 free requests/day, 20/min). A stale ":free" id just 404s → graceful degrade to the
# deterministic template author (no crash, no spend). To escalate to a paid model on hard/low-confidence work,
# swap a tier here for a paid id (e.g. "anthropic/claude-3.7-sonnet"); the daily USD cap + the OpenRouter key
# spend limit then bound the cost. Refresh ids any time from https://openrouter.ai/api/v1/models (filter :free).
TIER_MODELS: dict[str, str] = {
    "cheap": "meta-llama/llama-3.3-70b-instruct:free",
    "mid": "deepseek/deepseek-chat-v3-0324:free",
    "frontier": "deepseek/deepseek-r1:free",
}

# xAI (Grok) model ids — used when XAI_API_KEY is set (preferred, already on Railway). Single stable
# alias across tiers to avoid a wrong-id 404; a wrong id degrades gracefully to the template author.
# Override here if you want per-tier Grok models.
XAI_TIER_MODELS: dict[str, str] = {
    "cheap": "grok-2-latest",
    "mid": "grok-2-latest",
    "frontier": "grok-2-latest",
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
    provider: str | None = None,
    chat: ChatFn | None = None,
    store: Any = None,
    strategy_version_id: str | None = None,
) -> ProposalResult:
    """Compose the tier router with the REAL model call: decide the tier under the spend cap, map it to a model
    id, then ask that model for a STRUCTURED, schema-validated proposal. The HTTP transport is injectable
    (`chat`) so CI runs offline; with no key the default OpenRouter seam yields None → deterministic fallback.
    The proposal is STRUCTURE only — the deterministic Gate still disposes.

    `store` is optional — if provided, every model call is recorded in `llm_calls` (best-effort; never blocks).
    `strategy_version_id` attributes the call to a specific strategy version when known.
    """
    decision = route_model(
        RouteRequest(task="author", difficulty=difficulty, confidence=confidence, estimated_cost=estimated_cost),
        spend,
        spent_today,
    )
    if not decision.accepted or decision.tier is None:
        return ProposalResult(proposal=None, model_id=None, attempts=0, notes=[f"router declined: {decision.reason}"])
    models = XAI_TIER_MODELS if provider == "xai" else TIER_MODELS
    url = XAI_URL if provider == "xai" else OPENROUTER_URL
    model_id = models[decision.tier]
    seam = chat if chat is not None else openrouter_chat(api_key, url=url)

    # Wrap the seam with a recording wrapper so every real HTTP call persists a llm_calls row.
    # Recording is best-effort: a write failure must never crash the proposal path.
    if store is not None:
        seam = _recording_seam(seam, store=store, tier=decision.tier, model_id=model_id,
                               task="author", strategy_version_id=strategy_version_id)

    result = propose_structure(brief, model_id=model_id, valid_features=valid_features, chat=seam)
    result.notes.insert(0, f"router tier={decision.tier} model={model_id} provider={provider or 'openrouter'}")
    return result


def _recording_seam(
    inner: ChatFn,
    *,
    store: Any,
    tier: str,
    model_id: str,
    task: str,
    strategy_version_id: str | None,
) -> ChatFn:
    """Wrap a ChatFn so each invocation records a row in llm_calls (best-effort, offline-safe)."""
    from cosmu.costs.writer import LlmCallRecorder

    def _chat(m: str, prompt: str) -> str | None:
        with LlmCallRecorder(
            store=store,
            task=task,
            tier=tier,
            model_id=m,
            strategy_version_id=strategy_version_id,
        ) as rec:
            result = inner(m, prompt)
            # Approximate token counts from character length (no tokenizer dependency).
            # These are rough but honest — the exact cost on :free models is $0 regardless.
            rec.tokens_in = len(prompt) // 4
            rec.tokens_out = len(result) // 4 if result else 0
        return result

    return _chat

