# intent: the Mind's LLM-as-JUDGE seam. Given a pillar's RUBRIC + its point-in-time evidence, ask a model for a
# typed Verdict (instructor-style: prompt the shape, validate with Pydantic, retry once on invalid). LLM-OPTIONAL
# and OFFLINE-testable: no key (the chat seam yields None) or invalid output → returns None and the caller keeps
# the deterministic heuristic stance unchanged. The judge only SCORES a pillar; it can never abstain (a no-data
# abstain is decided in Python before any judge runs, so the model is never handed an empty pillar) and it never
# funds — the deterministic gate alone disposes of money. Secrets stay in the HTTP transport, never in the prompt.

from __future__ import annotations

import json
from collections.abc import Callable

from pydantic import ValidationError

from cosmu.lab.llm import ChatFn  # reuse the existing OpenAI-compatible (OpenRouter / xAI) chat seam type
from cosmu.mind.rubric import Rubric, Verdict

# A judge seam: (rubric, evidence lines, the deterministic heuristic lean) -> a typed Verdict, or None when no
# model ran / every attempt failed validation. Threaded into the analyst panel; None everywhere keeps the Mind
# fully deterministic and offline (the default in CI and in prod unless the operator opts in).
JudgeFn = Callable[[Rubric, list[str], str], "Verdict | None"]

# The hard rule, restated INSIDE the prompt so the model knows the bounds of its job.
_RAILGUARD = (
    "You only SCORE this one pillar. A deterministic gate — which you cannot see or influence — decides what "
    "gets funded. You never move money. Do not invent data: judge ONLY the evidence given."
)


def _system_prompt(rubric: Rubric) -> str:
    criteria = "; ".join(rubric.criteria)
    return (
        f"You are the {rubric.pillar} analyst on a trading committee.\n"
        f"Your prior (the edge you encode): {rubric.prior}\n"
        f"Weigh these criteria: {criteria}.\n"
        f"Score scale: {rubric.scale}\n"
        f"{_RAILGUARD}\n"
        "Reply with ONLY a JSON object, no prose, matching exactly:\n"
        '{"lean": "<bullish|bearish|neutral>", "score": <number in -1..1>, '
        '"confidence": <number in 0..1>, "rationale": "<one short sentence>"}\n'
        "score is the signed directional strength; confidence is how sure you are. "
        "Never include any other field, any threshold, price, quantity, or money instruction."
    )


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of the model text (models sometimes wrap it in prose / markdown fences)."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object in model response")
    return json.loads(text[start : end + 1])


def judge_pillar(
    rubric: Rubric,
    evidence: list[str],
    heuristic_lean: str,
    *,
    chat: ChatFn,
    model_id: str,
    max_retries: int = 1,
) -> Verdict | None:
    """Ask the model for a typed Verdict on ONE pillar, validate with Pydantic, retry on invalid (instructor
    -style). Returns None when the seam yields no model (no key) or every attempt fails validation — the caller
    then keeps the deterministic heuristic stance. The model is handed the evidence + a heuristic anchor; it may
    agree or disagree, but it can only ever return the typed Verdict shape."""
    if not evidence:
        # Defence in depth: an empty pillar should already have abstained upstream — never judge a no-data read.
        return None
    system = _system_prompt(rubric)
    facts = "\n".join(f"- {e}" for e in evidence)
    user = (
        f"Point-in-time evidence:\n{facts}\n\n"
        f"A deterministic heuristic reads this as: {heuristic_lean}. "
        "Score the pillar under your rubric (agree or disagree on the evidence). Return the JSON verdict."
    )
    last_err = ""
    for attempt in range(max(1, max_retries) + 1):
        prompt = system + "\n\n" + user
        if last_err:
            prompt += f"\n\nYour previous reply was invalid ({last_err}). Reply with corrected JSON only."
        try:
            raw = chat(model_id, prompt)
        except Exception:  # noqa: BLE001 — any transport failure degrades to the deterministic heuristic
            return None
        if raw is None:
            return None  # no model available (no key) → deterministic fallback
        try:
            data = _extract_json(raw)
            return Verdict.model_validate(data)
        except (ValueError, ValidationError) as exc:
            last_err = str(exc)[:160]
            continue
    return None


def build_judge(chat: ChatFn, model_id: str, *, max_retries: int = 1) -> JudgeFn:
    """Close a ChatFn + model id into the JudgeFn the analyst panel calls. Keeps analysts.py decoupled from the
    HTTP transport (and lets tests inject a mock chat)."""

    def judge(rubric: Rubric, evidence: list[str], heuristic_lean: str) -> Verdict | None:
        return judge_pillar(rubric, evidence, heuristic_lean, chat=chat, model_id=model_id, max_retries=max_retries)

    return judge


def judge_from_settings(settings, *, model_id: str | None = None) -> JudgeFn | None:  # noqa: ANN001
    """Build the REAL judge seam from settings, or None when no LLM key is configured (→ the Mind stays fully
    deterministic). Mirrors the lab router's provider choice: xAI (Grok) when keyed, else OpenRouter, on the
    same free model tier so the committee costs nothing on the 24/7 loop. The seam degrades gracefully — any
    transport / parse failure falls back to the heuristic — so enabling it can never crash or stall the Mind."""
    from cosmu.lab.llm import OPENROUTER_URL, XAI_URL, openrouter_chat
    from cosmu.lab.router import TIER_MODELS, XAI_TIER_MODELS

    provider = settings.llm_provider
    if provider is None:
        return None
    if provider == "xai":
        url, models = XAI_URL, XAI_TIER_MODELS
    else:
        url, models = OPENROUTER_URL, TIER_MODELS
    chat = openrouter_chat(settings.llm_api_key, url=url)
    return build_judge(chat, model_id or models["cheap"])
