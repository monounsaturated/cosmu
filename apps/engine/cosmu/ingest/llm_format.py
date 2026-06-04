# intent: LLM data-formatting layer — turn RAW unstructured inputs (news headlines / social text / scraped
# snippets) into a TYPED, point-in-time feature: {ts, source, category, sign, magnitude, rationale}. This
# standardizes weak signals so they can later be stored point-in-time and fed to ML. NEVER in the gate /
# scoring / money path — it is a CANDIDATE feature only, produced at ingest time, carrying the event
# timestamp (no look-ahead). If no LLM provider is configured the function degrades safely (returns None),
# never raises into a caller. LLM calls go through the injectable ChatFn seam so tests run offline with a
# mock provider. inputs: raw text + event ts + source label + injectable chat seam; outputs: a FormattedFeature
# (or None on no-key / invalid / exhausted retries); invariants: KEY-GATED (no key → None, honest degrade),
# extra="forbid" rejects any field outside the schema (no smuggled values), sign clamped to {-1,0,+1},
# magnitude clamped to [0,1], ts is the EVENT timestamp passed in (no look-ahead), offline-testable via inject.

from __future__ import annotations

import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from cosmu.lab.llm import ChatFn, _extract_json, openrouter_chat

# A cheap :free OpenRouter model — formatting raw text into a small typed JSON object needs no frontier tier.
# :free tier keeps spend at $0 on the autonomous loop. Configurable per call.
DEFAULT_FORMAT_MODEL = "meta-llama/llama-3.3-70b-instruct:free"

# The closed category taxonomy the formatter must pick from. A stable set lets consumers group by category
# across runs; unknown values are coerced to "other" (never rejected outright so a slightly off label never
# silently drops an event).
ALLOWED_CATEGORIES: tuple[str, ...] = (
    "macro",
    "regulatory",
    "adoption",
    "security",
    "market",
    "technology",
    "social",
    "other",
)

# Sign constants — named so no magic integers leak into specs or prompts.
SIGN_BULLISH: Literal[1] = 1
SIGN_NEUTRAL: Literal[0] = 0
SIGN_BEARISH: Literal[-1] = -1


class FormattedFeature(BaseModel):
    """The ONE typed, validated row that a raw text input collapses to.

    This is a CANDIDATE feature only — it standardizes unstructured text at ingest time and is NEVER used
    directly in the gate / scoring / money path. It carries the EVENT timestamp (not the processing time) to
    guarantee point-in-time correctness: no future information leaks in through a delayed processing clock.

    Fields:
    - ts: the event's own timestamp (passed in from the caller — the formatter cannot invent or shift it).
    - source: a caller-supplied label for the data origin (e.g. "cryptopanic", "twitter", "gdelt").
    - category: one of ALLOWED_CATEGORIES; unknown values coerced to "other".
    - sign: market direction — +1 bullish, -1 bearish, 0 neutral.
    - magnitude: signal strength in [0, 1] (0 = negligible, 1 = maximum).
    - rationale: the model's short plain-language explanation (audit trail, never used for scoring).

    `extra="forbid"` is the typed boundary: a model that smuggles any field outside this schema is rejected
    (retry) rather than silently stripped, so no unvalidated value can enter the feature store.
    """

    model_config = ConfigDict(extra="forbid")

    ts: datetime
    source: str
    category: str
    sign: Literal[-1, 0, 1]
    magnitude: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(default="")

    @field_validator("category")
    @classmethod
    def _coerce_category(cls, v: str) -> str:
        v = (v or "").strip().lower()
        return v if v in ALLOWED_CATEGORIES else "other"

    @field_validator("sign", mode="before")
    @classmethod
    def _clamp_sign(cls, v: object) -> int:
        """Clamp any numeric sign value to {-1, 0, +1} so a model that returns 0.5 or 2 is corrected rather
        than rejected — we'd rather have a softly-clamped feature than a retry loop on a nearly-valid response."""
        try:
            n = int(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0
        if n > 0:
            return 1
        if n < 0:
            return -1
        return 0

    @field_validator("magnitude", mode="before")
    @classmethod
    def _clamp_magnitude(cls, v: object) -> float:
        """Clamp magnitude to [0, 1]. Models occasionally return 1.05 or -0.02; hard clamp is safer than
        a retry loop when the value is otherwise meaningful."""
        try:
            f = float(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, f))


def _build_prompt(text: str) -> str:
    categories_str = " | ".join(ALLOWED_CATEGORIES)
    return (
        "You are a market-data formatter. Read the text below and classify its market signal as STRICT JSON.\n"
        "Reply with ONLY a JSON object, no prose, matching EXACTLY these four fields:\n"
        '{"sign": <-1|0|1>, "magnitude": <float 0..1>, '
        f'"category": "<one of: {categories_str}>", '
        '"rationale": "<short plain-language explanation, ≤120 chars>"}\n'
        "sign: +1 bullish / 0 neutral / -1 bearish. magnitude: signal strength (0 negligible, 1 maximum).\n"
        "Add NO other fields. Be concise in rationale.\n\n"
        f"Text:\n{text.strip()}"
    )


class LLMFormatter:
    """Injectable LLM data-formatter: raw text → FormattedFeature.

    KEY-GATED: with no key (and no injected chat seam) a call returns None — the system degrades honestly
    rather than raising. With an injected `chat` seam (a callable `(model_id, prompt) -> str | None`) the
    real network is never touched, so CI tests run fully offline.

    The formatter is NEVER on the gate / scoring / money path. It only standardizes raw text at ingest time
    and emits a CANDIDATE feature carrying the caller-supplied event timestamp (point-in-time, no look-ahead).
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        model: str = DEFAULT_FORMAT_MODEL,
        chat: ChatFn | None = None,
        max_retries: int = 2,
    ) -> None:
        self.model = model
        self.max_retries = max_retries
        # No injected seam → the real OpenRouter transport (returns None without a key, so key-gating holds).
        self._chat: ChatFn = chat if chat is not None else openrouter_chat(api_key)

    def format(
        self,
        text: str,
        *,
        ts: datetime,
        source: str,
    ) -> FormattedFeature | None:
        """Format one raw-text input into a FormattedFeature.

        Returns None on: no key, transport error, or exhausted-invalid retries — the caller then decides
        whether to skip or fall back to a deterministic signal (never a fabricated feature).

        `ts` is the event's own timestamp — the formatter cannot alter it, guaranteeing point-in-time
        correctness (no look-ahead through a delayed processing clock). `source` is the caller-supplied
        label for the data origin (audit + later grouping — never used for scoring).
        """
        last_err = ""
        for _ in range(max(1, self.max_retries) + 1):
            prompt = _build_prompt(text)
            if last_err:
                prompt += f"\n\nYour previous reply was invalid ({last_err}). Reply with corrected JSON only."
            try:
                raw = self._chat(self.model, prompt)
            except Exception:  # noqa: BLE001 — transport failure degrades honestly
                return None
            if raw is None:
                return None  # no key / no model available
            try:
                data = _extract_json(raw)
                # Inject the caller-controlled fields — the LLM must not supply or override ts/source.
                data["ts"] = ts
                data["source"] = source
                return FormattedFeature.model_validate(data)
            except (ValueError, ValidationError) as exc:
                last_err = str(exc)[:160]
                continue
        return None


def format_text(
    text: str,
    *,
    ts: datetime,
    source: str,
    api_key: str | None = None,
    chat: ChatFn | None = None,
    model: str = DEFAULT_FORMAT_MODEL,
    max_retries: int = 2,
) -> FormattedFeature | None:
    """Convenience top-level function: format one raw-text input into a typed FormattedFeature.

    CANDIDATE FEATURE ONLY — never in the gate / scoring / money path.
    Returns None gracefully when no LLM provider is configured (key-gated) or on any error.

    Args:
        text:        The raw unstructured input (news headline, social post, scraped snippet).
        ts:          The event's own timestamp — passed through unchanged (point-in-time, no look-ahead).
        source:      Caller-supplied data-origin label (e.g. "cryptopanic", "twitter", "gdelt").
        api_key:     Optional OpenRouter API key. When None AND no `chat` seam is injected, returns None.
        chat:        Injectable ChatFn seam for offline/test use. When provided, `api_key` is ignored.
        model:       OpenRouter model id. Defaults to a cheap :free model.
        max_retries: How many times to retry on an invalid (non-JSON / schema-violating) response.
    """
    formatter = LLMFormatter(api_key=api_key, model=model, chat=chat, max_retries=max_retries)
    return formatter.format(text, ts=ts, source=source)
