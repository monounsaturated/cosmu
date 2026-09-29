# Offline tests for the generic LLM data-formatter (raw text → typed feature). The chat seam is injected so
# no key / network is needed. Asserts: extra="forbid" rejects smuggled fields, key-gating returns None,
# retry-on-invalid, category coercion, and the adapter into the ingest event-score seam (with deterministic
# fallback). The formatter is ingest-only — these tests prove it never needs to touch the gate/money path.

from __future__ import annotations

import pytest
from pydantic import ValidationError

from cosmu.config.settings import Settings
from cosmu.ingest.llm_formatter import (
    ALLOWED_CATEGORIES,
    OpenRouterFormatter,
    TypedFeature,
    build_event_formatter_from_settings,
    make_event_score_llm,
    typed_feature_to_event_score,
)
from cosmu.ingest.standardize import NewsEventScore


def _chat(reply):
    """A chat seam that returns `reply` (str) or raises if `reply` is an Exception."""
    def chat(model_id: str, prompt: str):
        if isinstance(reply, Exception):
            raise reply
        return reply
    return chat


def test_typed_feature_forbids_extra_fields():
    with pytest.raises(ValidationError):
        TypedFeature(sign=1, magnitude=0.5, category="macro", confidence=0.9, threshold=0.3)  # type: ignore[call-arg]


def test_typed_feature_score_is_signed_magnitude():
    assert TypedFeature(sign=-1, magnitude=0.4, category="security", confidence=0.5).score == -0.4
    assert TypedFeature(sign=0, magnitude=0.9, category="macro", confidence=0.5).score == 0.0


def test_category_out_of_taxonomy_coerced_to_other():
    tf = TypedFeature(sign=1, magnitude=0.5, category="weather", confidence=0.5)
    assert tf.category == "other"
    assert "other" in ALLOWED_CATEGORIES


def test_formatter_parses_valid_json():
    fmt = OpenRouterFormatter(chat=_chat('{"sign": 1, "magnitude": 0.8, "category": "macro", "confidence": 0.9}'))
    tf = fmt("BTC ETF approved, massive inflows expected")
    assert tf is not None and tf.sign == 1 and tf.magnitude == 0.8 and tf.category == "macro"


def test_formatter_no_key_returns_none():
    # chat returns None (the real openrouter_chat behaviour with no key) → honest degradation
    fmt = OpenRouterFormatter(chat=lambda m, p: None)
    assert fmt("anything") is None


def test_formatter_retries_then_succeeds():
    replies = iter(["not json at all", '{"sign": -1, "magnitude": 0.6, "category": "security", "confidence": 0.7}'])

    def chat(model_id: str, prompt: str):
        return next(replies)

    fmt = OpenRouterFormatter(chat=chat, max_retries=2)
    tf = fmt("Exchange hacked")
    assert tf is not None and tf.sign == -1 and tf.category == "security"


def test_formatter_transport_error_degrades_to_none():
    fmt = OpenRouterFormatter(chat=_chat(RuntimeError("network down")))
    assert fmt("x") is None


def test_adapter_maps_to_event_score():
    tf = TypedFeature(sign=1, magnitude=0.7, category="adoption", confidence=0.8)
    ev = typed_feature_to_event_score(tf, "headline text")
    assert isinstance(ev, NewsEventScore)
    assert ev.sign == 1 and ev.event_type == "bullish" and ev.headline == "headline text"


def test_event_score_llm_falls_back_to_lexicon_when_formatter_none():
    # formatter returns None (no key) → the wrapper uses the deterministic lexicon scorer (byte-identical path)
    llm = make_event_score_llm(OpenRouterFormatter(chat=lambda m, p: None))
    ev = llm("Bitcoin surges to record on ETF approval")
    assert isinstance(ev, NewsEventScore)
    assert ev.sign == 1  # the lexicon scores the bullish words


def test_event_score_llm_uses_formatter_when_available():
    fmt = OpenRouterFormatter(chat=_chat('{"sign": -1, "magnitude": 0.9, "category": "security", "confidence": 0.95}'))
    llm = make_event_score_llm(fmt)
    ev = llm("totally neutral words here")  # lexicon would say neutral; the LLM overrides
    assert ev.sign == -1 and ev.magnitude == 0.9


def test_build_from_settings_is_key_gated():
    assert build_event_formatter_from_settings(Settings(openrouter_api_key=None)) is None
    assert build_event_formatter_from_settings(Settings(openrouter_api_key="sk-test")) is not None
