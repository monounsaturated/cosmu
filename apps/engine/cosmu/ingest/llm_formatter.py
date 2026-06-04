# intent: the GENERIC LLM data-formatter — turn ANY raw text (news headline, social post, scraped snippet)
# into ONE validated, typed feature (sign ∈ {-1,0,1} / magnitude ∈ [0,1] / category / confidence) via a cheap
# OpenRouter model, ONCE, at ingest; inputs: raw text + an injectable chat seam; outputs: a TypedFeature (or
# None on no-key / invalid output); invariants: KEY-GATED (no OPENROUTER_API_KEY → None, deterministic
# lexicon fallback runs instead — the system degrades honestly), the LLM output is Pydantic-validated with
# `extra="forbid"` (a model that smuggles an extra field is REJECTED, not silently stripped), it runs cheap
# + temperature 0 + retry-on-invalid, and it is NEVER on the gate / scoring / money path — it only standardizes
# text at ingest, exactly like the deterministic lexicon it sits beside. Offline-testable: inject a chat seam.

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from cosmu.data.altdata import NewsItem
from cosmu.ingest.standardize import (
    NewsEventScore,
    ScoredNewsEvent,
    score_news_events,
)
from cosmu.lab.llm import ChatFn, _extract_json, openrouter_chat

# Frozen, versioned transform — pinned into any feature standardized by the formatter so a gate-passed
# survivor stays reproducible. Bump when the prompt or schema changes.
LLM_FORMATTER_TRANSFORM_VERSION = "llm-formatter-v1"

# A CHEAP OpenRouter model — formatting text into a tiny typed JSON object needs no frontier tier.
# Configurable per call; the daily USD cap + the OpenRouter account spend limit bound the cost.
DEFAULT_FORMATTER_MODEL = "openai/gpt-4o-mini"

# The category taxonomy the formatter must pick from. A closed set keeps the feature stable across runs and
# lets the gate group by category later; an out-of-set value is coerced to "other" (never rejected outright).
ALLOWED_CATEGORIES: tuple[str, ...] = (
    "macro", "regulatory", "adoption", "security", "market", "technology", "other",
)


class TypedFeature(BaseModel):
    """The ONE validated, typed row a messy piece of text collapses to.

    `sign` is direction (+1 bullish, -1 bearish, 0 neutral); `magnitude` ∈ [0,1] is strength; `category` is
    one of ALLOWED_CATEGORIES; `confidence` ∈ [0,1] is the model's self-assessed certainty. `extra="forbid"`
    is the typed boundary: a model that adds any field outside this schema is rejected (retry), so it can
    never smuggle an unvalidated value into the feature."""

    model_config = ConfigDict(extra="forbid")

    sign: Literal[-1, 0, 1]
    magnitude: float = Field(ge=0.0, le=1.0)
    category: str
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("category")
    @classmethod
    def _known_category(cls, v: str) -> str:
        v = (v or "").strip().lower()
        return v if v in ALLOWED_CATEGORIES else "other"

    @property
    def score(self) -> float:
        """Signed magnitude in [-1, 1] — the gate-readable numeric value."""
        return float(self.sign) * self.magnitude


def _format_prompt(text: str) -> str:
    return (
        "You are a market-data formatter. Read the text below and output its market signal as STRICT JSON.\n"
        "Reply with ONLY a JSON object, no prose, matching EXACTLY these four fields:\n"
        '{"sign": <-1|0|1>, "magnitude": <float 0..1>, '
        '"category": "<one of: ' + "|".join(ALLOWED_CATEGORIES) + '>", '
        '"confidence": <float 0..1>}\n'
        "sign: +1 bullish / 0 neutral / -1 bearish. magnitude: how strong (0 weak, 1 maximum). "
        "Add NO other fields.\n\n"
        f"Text:\n{text.strip()}"
    )


class OpenRouterFormatter:
    """The cheap-OpenRouter text→TypedFeature formatter. KEY-GATED: with no key (and no injected chat seam) a
    call returns None so the caller falls back to the deterministic lexicon — the system degrades honestly.
    Validated with `extra="forbid"` + retry-on-invalid. The LLM ONLY standardizes text here; it is NEVER on
    the gate / scoring / money path. Offline-testable: inject `chat=(model_id, prompt) -> str | None`."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        model: str = DEFAULT_FORMATTER_MODEL,
        chat: ChatFn | None = None,
        max_retries: int = 2,
    ) -> None:
        self.model = model
        self.max_retries = max_retries
        # No injected seam → the real OpenRouter transport (which itself returns None without a key).
        self._chat: ChatFn = chat if chat is not None else openrouter_chat(api_key)

    def __call__(self, text: str) -> TypedFeature | None:
        """Format one piece of text. Returns None on no-key / transport error / exhausted-invalid retries —
        the caller then uses its deterministic fallback (never a fabricated feature)."""
        last_err = ""
        for _ in range(max(1, self.max_retries) + 1):
            prompt = _format_prompt(text)
            if last_err:
                prompt += f"\n\nYour previous reply was invalid ({last_err}). Reply with corrected JSON only."
            try:
                raw = self._chat(self.model, prompt)
            except Exception:  # noqa: BLE001 — a transport failure degrades to the deterministic path
                return None
            if raw is None:
                return None  # no key / no model available → deterministic fallback
            try:
                return TypedFeature.model_validate(_extract_json(raw))
            except (ValueError, ValidationError) as exc:
                last_err = str(exc)[:160]
                continue
        return None


# --------------------------------------------------------------------------- adapters into the ingest seam
# The TypedFeature maps 1:1 onto the existing typed NewsEventScore (sign × magnitude), so the formatter slots
# in as the `llm=` argument to `score_news_events` / `ingest_news_event_score` — the SAME ingest seam the
# deterministic lexicon uses. This is the only place the formatter touches the pipeline: at ingest, never the
# money path.


def typed_feature_to_event_score(tf: TypedFeature, headline: str) -> NewsEventScore:
    """Adapt a TypedFeature into the pipeline's typed NewsEventScore (carries the source text for audit)."""
    event_type: Literal["bullish", "bearish", "neutral"] = (
        "bullish" if tf.sign == 1 else "bearish" if tf.sign == -1 else "neutral"
    )
    return NewsEventScore(
        sign=tf.sign,
        magnitude=tf.magnitude,
        event_type=event_type,
        confidence=tf.confidence,
        headline=headline,
    )


def make_event_score_llm(formatter: OpenRouterFormatter) -> Callable[[str], NewsEventScore]:
    """Wrap an OpenRouterFormatter as the `llm=` scorer `score_news_events` expects. Falls back to the
    deterministic lexicon scorer when the formatter returns None (no key / invalid) — so a keyless run is
    byte-identical to today and a keyed run upgrades accuracy without changing the contract."""
    from cosmu.ingest.standardize import _score_headline

    def score(headline: str) -> NewsEventScore:
        tf = formatter(headline)
        return typed_feature_to_event_score(tf, headline) if tf is not None else _score_headline(headline)

    return score


def build_event_formatter_from_settings(settings) -> Callable[[str], NewsEventScore] | None:  # noqa: ANN001
    """Build the LLM event-score formatter from settings — ONLY when OPENROUTER_API_KEY is set (key-gated).
    Returns None otherwise, so the ingest pass uses the deterministic lexicon (no LLM, no spend)."""
    key = getattr(settings, "openrouter_api_key", None)
    if not key:
        return None
    return make_event_score_llm(OpenRouterFormatter(key))


def format_text_records(
    items: list[NewsItem],
    *,
    formatter: OpenRouterFormatter | None = None,
) -> list[ScoredNewsEvent]:
    """Convenience: format a batch of raw-text NewsItems into typed, point-in-time ScoredNewsEvents (sign ×
    magnitude), content-hash cached. With no formatter (or no key) the deterministic lexicon runs — same
    contract. This is a thin pass-through to `score_news_events`; nothing here reaches the money path."""
    llm = make_event_score_llm(formatter) if formatter is not None else None
    return score_news_events(items, llm=llm)
