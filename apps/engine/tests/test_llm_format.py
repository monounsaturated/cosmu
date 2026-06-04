# Offline tests for the LLM data-formatting layer (raw text → typed point-in-time FormattedFeature).
# The ChatFn seam is injected for every test — no API key, no network. Covers:
#   - correct typed parsing from canned JSON
#   - sign clamping ({-1, 0, +1} and out-of-range inputs)
#   - magnitude clamping ([0, 1])
#   - category coercion (unknown → "other")
#   - extra="forbid" rejects smuggled fields
#   - abstain / offline path: chat seam returns None → format() returns None
#   - transport-error path: chat seam raises → format() returns None (never re-raises)
#   - point-in-time ts passthrough: the caller's ts is preserved unchanged
#   - retry-on-invalid: bad JSON on first attempt, valid on second
#   - exhaust-retries path: all attempts invalid → returns None
#   - convenience top-level format_text function
# The formatter is NEVER in the gate/scoring/money path — these tests prove it purely as a text→feature transform.

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from cosmu.ingest.llm_format import (
    ALLOWED_CATEGORIES,
    DEFAULT_FORMAT_MODEL,
    LLMFormatter,
    FormattedFeature,
    SIGN_BEARISH,
    SIGN_BULLISH,
    SIGN_NEUTRAL,
    format_text,
)

# A fixed event timestamp — used across tests to verify point-in-time passthrough.
_EVENT_TS = datetime(2024, 3, 15, 12, 0, 0, tzinfo=UTC)
_SOURCE = "cryptopanic"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _chat_returning(reply: str | None | Exception):
    """Build a ChatFn stub that always returns `reply` (or raises if it is an Exception)."""

    def chat(model_id: str, prompt: str) -> str | None:
        if isinstance(reply, Exception):
            raise reply
        return reply

    return chat


def _canned(sign: int = 1, magnitude: float = 0.8, category: str = "macro", rationale: str = "test") -> str:
    """JSON string the stub will return for a single successful call."""
    return json.dumps({"sign": sign, "magnitude": magnitude, "category": category, "rationale": rationale})


# ---------------------------------------------------------------------------
# FormattedFeature schema tests (no LLM call)
# ---------------------------------------------------------------------------


def test_formatted_feature_has_required_fields():
    """The output type carries ts, source, category, sign, magnitude, and rationale — the full contract."""
    ff = FormattedFeature(
        ts=_EVENT_TS,
        source=_SOURCE,
        category="market",
        sign=1,
        magnitude=0.7,
        rationale="Strong inflow surge.",
    )
    assert ff.ts == _EVENT_TS
    assert ff.source == _SOURCE
    assert ff.category == "market"
    assert ff.sign == 1
    assert ff.magnitude == 0.7
    assert ff.rationale == "Strong inflow surge."


def test_formatted_feature_forbids_extra_fields():
    """extra="forbid" ensures no model can smuggle an unvalidated field into the feature."""
    with pytest.raises(ValidationError):
        FormattedFeature(  # type: ignore[call-arg]
            ts=_EVENT_TS,
            source=_SOURCE,
            category="macro",
            sign=1,
            magnitude=0.5,
            rationale="ok",
            threshold=0.9,  # ← smuggled field — must be rejected
        )


def test_sign_clamping_positive():
    ff = FormattedFeature(ts=_EVENT_TS, source=_SOURCE, category="macro", sign=2, magnitude=0.5, rationale="")
    assert ff.sign == SIGN_BULLISH


def test_sign_clamping_negative():
    ff = FormattedFeature(ts=_EVENT_TS, source=_SOURCE, category="macro", sign=-5, magnitude=0.5, rationale="")
    assert ff.sign == SIGN_BEARISH


def test_sign_zero():
    ff = FormattedFeature(ts=_EVENT_TS, source=_SOURCE, category="macro", sign=0, magnitude=0.0, rationale="")
    assert ff.sign == SIGN_NEUTRAL


def test_magnitude_clamped_above_one():
    ff = FormattedFeature(ts=_EVENT_TS, source=_SOURCE, category="macro", sign=1, magnitude=1.5, rationale="")
    assert ff.magnitude == 1.0


def test_magnitude_clamped_below_zero():
    ff = FormattedFeature(ts=_EVENT_TS, source=_SOURCE, category="macro", sign=1, magnitude=-0.2, rationale="")
    assert ff.magnitude == 0.0


def test_category_coerced_to_other_when_unknown():
    ff = FormattedFeature(ts=_EVENT_TS, source=_SOURCE, category="weather", sign=0, magnitude=0.0, rationale="")
    assert ff.category == "other"
    assert "other" in ALLOWED_CATEGORIES


def test_category_known_values_accepted():
    for cat in ALLOWED_CATEGORIES:
        ff = FormattedFeature(ts=_EVENT_TS, source=_SOURCE, category=cat, sign=0, magnitude=0.0, rationale="")
        assert ff.category == cat


# ---------------------------------------------------------------------------
# LLMFormatter — correct typed parsing from canned JSON
# ---------------------------------------------------------------------------


def test_formatter_parses_canned_bullish_json():
    fmt = LLMFormatter(chat=_chat_returning(_canned(sign=1, magnitude=0.8, category="macro", rationale="ETF approved")))
    ff = fmt.format("Bitcoin ETF approved", ts=_EVENT_TS, source=_SOURCE)
    assert ff is not None
    assert ff.sign == 1
    assert ff.magnitude == 0.8
    assert ff.category == "macro"
    assert ff.rationale == "ETF approved"


def test_formatter_parses_canned_bearish_json():
    fmt = LLMFormatter(chat=_chat_returning(_canned(sign=-1, magnitude=0.9, category="security", rationale="Exchange hacked")))
    ff = fmt.format("Major exchange hacked", ts=_EVENT_TS, source=_SOURCE)
    assert ff is not None
    assert ff.sign == -1
    assert ff.magnitude == 0.9
    assert ff.category == "security"


def test_formatter_parses_neutral_json():
    fmt = LLMFormatter(chat=_chat_returning(_canned(sign=0, magnitude=0.1, category="other", rationale="routine update")))
    ff = fmt.format("Routine software update released", ts=_EVENT_TS, source=_SOURCE)
    assert ff is not None
    assert ff.sign == 0


# ---------------------------------------------------------------------------
# Point-in-time ts passthrough
# ---------------------------------------------------------------------------


def test_ts_passthrough_unchanged():
    """The formatter must carry the caller's ts unchanged — point-in-time correctness."""
    specific_ts = datetime(2023, 7, 4, 9, 30, tzinfo=UTC)
    fmt = LLMFormatter(chat=_chat_returning(_canned()))
    ff = fmt.format("any text", ts=specific_ts, source="test")
    assert ff is not None
    assert ff.ts == specific_ts


def test_source_passthrough_unchanged():
    """The formatter must carry the caller's source label unchanged."""
    fmt = LLMFormatter(chat=_chat_returning(_canned()))
    ff = fmt.format("any text", ts=_EVENT_TS, source="gdelt")
    assert ff is not None
    assert ff.source == "gdelt"


# ---------------------------------------------------------------------------
# Abstain / offline / no-key path
# ---------------------------------------------------------------------------


def test_no_key_no_chat_returns_none():
    """Without an injected chat seam AND without an api_key, format() returns None — honest degrade."""
    fmt = LLMFormatter(api_key=None, chat=_chat_returning(None))
    result = fmt.format("any text", ts=_EVENT_TS, source=_SOURCE)
    assert result is None


def test_chat_returning_none_degrades_to_none():
    """chat seam returning None (the real openrouter_chat behaviour with no key) → None, never raises."""
    fmt = LLMFormatter(chat=lambda m, p: None)
    assert fmt.format("anything", ts=_EVENT_TS, source=_SOURCE) is None


def test_transport_error_degrades_to_none():
    """A RuntimeError from the chat seam is caught and degraded to None — the caller is never surprised."""
    fmt = LLMFormatter(chat=_chat_returning(RuntimeError("network down")))
    result = fmt.format("anything", ts=_EVENT_TS, source=_SOURCE)
    assert result is None


def test_transport_connection_error_degrades_to_none():
    """ConnectionError from the chat seam is caught too."""
    fmt = LLMFormatter(chat=_chat_returning(ConnectionError("timeout")))
    result = fmt.format("anything", ts=_EVENT_TS, source=_SOURCE)
    assert result is None


# ---------------------------------------------------------------------------
# Retry-on-invalid behaviour
# ---------------------------------------------------------------------------


def test_retry_succeeds_on_second_attempt():
    """First reply is garbage JSON; second attempt returns valid JSON → the feature is parsed correctly."""
    replies = iter(["not json at all", _canned(sign=-1, magnitude=0.6, category="regulatory")])

    def chat(model_id: str, prompt: str) -> str | None:
        return next(replies)

    fmt = LLMFormatter(chat=chat, max_retries=2)
    ff = fmt.format("Regulator bans crypto derivatives", ts=_EVENT_TS, source=_SOURCE)
    assert ff is not None
    assert ff.sign == -1
    assert ff.category == "regulatory"


def test_exhaust_retries_returns_none():
    """All attempts return invalid JSON — the formatter gives up and returns None."""
    fmt = LLMFormatter(chat=_chat_returning("this is not json {broken"), max_retries=2)
    result = fmt.format("anything", ts=_EVENT_TS, source=_SOURCE)
    assert result is None


def test_smuggled_extra_field_triggers_retry_then_succeeds():
    """First reply has a smuggled 'threshold' field (extra="forbid"); second reply is clean."""
    smuggled = json.dumps({"sign": 1, "magnitude": 0.5, "category": "macro", "rationale": "ok", "threshold": 0.9})
    clean = _canned(sign=1, magnitude=0.5, category="macro")
    replies = iter([smuggled, clean])

    def chat(model_id: str, prompt: str) -> str | None:
        return next(replies)

    fmt = LLMFormatter(chat=chat, max_retries=2)
    ff = fmt.format("BTC adoption milestone", ts=_EVENT_TS, source=_SOURCE)
    assert ff is not None
    assert ff.sign == 1


# ---------------------------------------------------------------------------
# Convenience top-level format_text
# ---------------------------------------------------------------------------


def test_format_text_function_returns_typed_feature():
    """The module-level format_text convenience function works the same as LLMFormatter.format()."""
    ff = format_text(
        "Massive ETF inflows signal institutional adoption",
        ts=_EVENT_TS,
        source="reuters",
        chat=_chat_returning(_canned(sign=1, magnitude=0.9, category="adoption", rationale="institutional buy")),
    )
    assert ff is not None
    assert ff.sign == 1
    assert ff.source == "reuters"
    assert ff.ts == _EVENT_TS


def test_format_text_no_chat_no_key_returns_none():
    """format_text degrades to None when no chat seam and no api_key — same key-gating as LLMFormatter."""
    ff = format_text(
        "any text",
        ts=_EVENT_TS,
        source=_SOURCE,
        api_key=None,
        chat=lambda m, p: None,
    )
    assert ff is None


# ---------------------------------------------------------------------------
# DEFAULT_FORMAT_MODEL uses a :free tier model
# ---------------------------------------------------------------------------


def test_default_model_is_free_tier():
    """The default model must be on the :free OpenRouter tier (zero spend on the autonomous loop)."""
    assert ":free" in DEFAULT_FORMAT_MODEL
