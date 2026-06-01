# intent: the REAL LLM seam — call OpenRouter over stdlib HTTP for a STRUCTURED, schema-validated proposal
# (instructor-style: prompt for the typed shape, validate with Pydantic, retry on invalid). The model only
# PROPOSES STRUCTURE (a base template + NAMED features + horizon/asset hints) — never thresholds, never code,
# never a money move; the deterministic spec builder turns the proposal into a magic-number-free StrategySpec
# and the deterministic Gate alone disposes. inputs: a brief + the valid feature/template vocab + a chat() seam;
# outputs: a validated LlmProposal. invariants: LLM-OPTIONAL + OFFLINE-testable — no key (or no chat seam) means
# the caller uses the deterministic template path unchanged; the HTTP transport is injectable so CI runs with no
# network/keys; secrets stay server-side and never enter the prompt; a magic-number / unknown-feature proposal is
# rejected (retry, then the caller falls back). The model NEVER reaches the scorer/Gate.

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# The base templates the model may pick from. These map 1:1 onto the deterministic seed builders in
# lab/author so the proposal only ever STEERS the existing magic-number-free templates — it cannot invent
# raw structure or thresholds.
ALLOWED_TEMPLATES: tuple[str, ...] = ("mean_reversion", "momentum", "carry", "breakout")
ALLOWED_BAR_SIZES: tuple[str, ...] = ("1h", "4h", "1d")

# A chat seam: (model_id, prompt) -> raw model text. Real default hits OpenRouter; tests inject a fake so CI
# stays offline. Returning None signals "no model available" (e.g. no key) → deterministic fallback.
ChatFn = Callable[[str, str], str | None]


class LlmProposal(BaseModel):
    """The TYPED, validated thing the model returns: a STRUCTURE proposal only. No thresholds (those stay in the
    deterministic param_space), no code, no money move. Unknown features and any numeric 'threshold' field are
    rejected so a model can never smuggle a magic number into the spec."""

    # extra="forbid": a model that adds ANY field outside this schema (e.g. a numeric "threshold"/"entry_rsi") is
    # rejected outright rather than silently stripped — the typed boundary is where magic numbers die.
    model_config = ConfigDict(extra="forbid")

    base_template: str = Field(description="one of the allowed strategy templates")
    features: list[str] = Field(default_factory=list, description="named features from the registry only")
    bar_size: str | None = Field(default=None, description="optional horizon hint: 1h|4h|1d")
    rationale: str = Field(default="", description="plain-language why")

    @field_validator("base_template")
    @classmethod
    def _known_template(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v not in ALLOWED_TEMPLATES:
            raise ValueError(f"unknown template: {v!r}")
        return v

    @field_validator("bar_size")
    @classmethod
    def _known_bar(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().lower()
        if v not in ALLOWED_BAR_SIZES:
            raise ValueError(f"unknown bar_size: {v!r}")
        return v


@dataclass
class ProposalResult:
    """What the seam returns to the author. `proposal` is None when no model ran (no key/seam) OR every attempt
    failed validation — the caller then uses the deterministic template path unchanged. `notes` is the audit
    trail (which tier/model, how many retries, why it fell back)."""

    proposal: LlmProposal | None
    model_id: str | None
    attempts: int
    notes: list[str]


def _system_prompt(valid_features: list[str]) -> str:
    return (
        "You are a quant research assistant for an automated trading lab. You PROPOSE only the STRUCTURE of a "
        "trading hypothesis — a base template and which named features to use. You do NOT choose thresholds, "
        "numbers, position sizes, or anything money-adjacent: those are fit later by a deterministic optimizer "
        "and judged by a deterministic gate that you cannot influence.\n"
        "Reply with ONLY a JSON object, no prose, matching exactly:\n"
        '{"base_template": "<one of: ' + "|".join(ALLOWED_TEMPLATES) + '>", '
        '"features": ["<named feature>", ...], '
        '"bar_size": "<1h|4h|1d or null>", "rationale": "<short why>"}\n'
        "features MUST be chosen ONLY from this allowed list: " + ", ".join(valid_features) + ".\n"
        "Never include any numeric threshold, price, quantity, or parameter value."
    )


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of the model text (models sometimes wrap it in prose/markdown fences)."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object in model response")
    return json.loads(text[start : end + 1])


def propose_structure(
    brief: str,
    *,
    model_id: str,
    valid_features: list[str],
    chat: ChatFn,
    max_retries: int = 2,
) -> ProposalResult:
    """Ask the model for a typed LlmProposal, validate with Pydantic, retry on invalid (instructor-style). The
    model only PROPOSES structure; the caller turns it into a magic-number-free spec and the Gate disposes.
    Returns proposal=None if the seam yields nothing or every attempt fails validation (→ deterministic fallback)."""
    notes: list[str] = []
    system = _system_prompt(valid_features)
    user = f"Brief: {brief.strip()}\nReturn the JSON proposal."
    attempts = 0
    last_err = ""
    for attempt in range(max(1, max_retries) + 1):
        attempts = attempt + 1
        prompt = system + "\n\n" + user
        if last_err:
            prompt += f"\n\nYour previous reply was invalid ({last_err}). Reply with corrected JSON only."
        try:
            raw = chat(model_id, prompt)
        except Exception as exc:  # noqa: BLE001 — a transport failure must degrade to the deterministic path
            notes.append(f"llm transport error on attempt {attempts}: {type(exc).__name__}")
            return ProposalResult(proposal=None, model_id=model_id, attempts=attempts, notes=notes)
        if raw is None:
            notes.append("llm seam returned no model (no key) — deterministic fallback")
            return ProposalResult(proposal=None, model_id=None, attempts=attempts, notes=notes)
        try:
            data = _extract_json(raw)
            proposal = LlmProposal.model_validate(data)
        except (ValueError, ValidationError) as exc:
            last_err = str(exc)[:160]
            notes.append(f"invalid proposal on attempt {attempts}: {last_err}")
            continue
        # Drop any feature the model invented that is not in the registry vocab (defence in depth — the spec
        # builder also validates, and an empty list just yields the template's own features).
        unknown = [f for f in proposal.features if f not in valid_features]
        if unknown:
            proposal.features = [f for f in proposal.features if f in valid_features]
            notes.append(f"dropped unknown proposed feature(s): {unknown}")
        notes.append(f"llm proposed structure via {model_id} (attempt {attempts})")
        return ProposalResult(proposal=proposal, model_id=model_id, attempts=attempts, notes=notes)
    notes.append("llm exhausted retries with invalid output — deterministic fallback")
    return ProposalResult(proposal=None, model_id=model_id, attempts=attempts, notes=notes)


def openrouter_chat(api_key: str | None, *, timeout: float = 30.0) -> ChatFn:
    """Build the REAL OpenRouter chat seam over stdlib urllib (no SDK). Returns a ChatFn that posts a single
    completion and returns the assistant text. With no key it returns a seam that always yields None so the
    caller uses the deterministic path. Secrets stay in the Authorization header — never in the prompt/payload."""

    def chat(model_id: str, prompt: str) -> str | None:
        if not api_key:
            return None
        body = json.dumps(
            {
                "model": model_id,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            OPENROUTER_URL,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "X-Title": "Cosmu Lab",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — fixed OpenRouter host
                payload = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            return None
        choices = payload.get("choices") or []
        if not choices:
            return None
        return choices[0].get("message", {}).get("content")

    return chat
