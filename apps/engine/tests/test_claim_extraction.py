# Offline tests for Phase 1 claim extraction (cosmu.mind.claims). A MOCK chat seam returns canned JSON so the
# extractor runs with no key / no network. Asserts: typed claims parse, the claim timestamp is STAMPED from the
# post (no look-ahead, never a model-proposed date), provenance is attached, un-parseable items are dropped (the
# batch survives), malformed JSON retries then degrades to [], and no chat seam → [] (honest degradation).

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from cosmu.mind.claims import (
    HORIZON_DAYS,
    Claim,
    ClaimExtractor,
    VoicePost,
    extract_claims,
    horizon_to_days,
)

_TS = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)


def _post(text: str, **kw) -> VoicePost:
    base = dict(handle="@vox", platform="x", post_id="p1", text=text, ts=_TS, url="http://x/p1")
    base.update(kw)
    return VoicePost(**base)


def _chat_returning(payload) -> "object":
    """A mock ChatFn that ignores the prompt and returns the given payload as JSON text."""
    text = payload if isinstance(payload, str) else json.dumps(payload)

    def chat(model_id: str, prompt: str) -> str:
        return text

    return chat


def test_extracts_typed_claim_and_stamps_post_timestamp():
    chat = _chat_returning(
        [{"entity": "btc", "direction": "up", "horizon": "1w", "conviction": 0.8,
          "quote": "BTC to the moon next week", "rationale": "ETF inflows"}]
    )
    claims = extract_claims(_post("BTC to the moon next week"), chat=chat, model_id="m")
    assert len(claims) == 1
    c = claims[0]
    assert c.entity == "BTC"             # uppercased
    assert c.direction == "up"
    assert c.horizon == "1w"
    assert c.horizon_days == 7
    assert c.conviction == 0.8
    # the claim timestamp is the POST's availability, never a model-proposed date — no look-ahead
    assert c.ts == _TS
    assert c.handle == "@vox" and c.post_id == "p1" and c.url == "http://x/p1"


def test_no_chat_seam_extracts_nothing_honest_degradation():
    assert ClaimExtractor(chat=None).extract([_post("BTC up")]) == []


def test_empty_array_for_non_predictive_post():
    chat = _chat_returning([])
    assert extract_claims(_post("gm frens"), chat=chat, model_id="m") == []


def test_drops_unparseable_item_but_keeps_valid_ones():
    chat = _chat_returning(
        [
            {"entity": "ETH", "direction": "down", "horizon": "1m", "conviction": 0.6},
            {"entity": "BTC", "direction": "sideways", "horizon": "1w", "conviction": 0.5},  # bad direction
            {"entity": "SOL", "direction": "up", "horizon": "forever", "conviction": 0.5},   # bad horizon
            {"entity": "DOGE", "direction": "up", "horizon": "1d", "conviction": 9.0},        # out-of-range
            {"entity": "ADA", "direction": "up", "horizon": "1d", "conviction": 0.5, "target": 1.0},  # extra field
        ]
    )
    claims = extract_claims(_post("mixed bag"), chat=chat, model_id="m")
    assert [c.entity for c in claims] == ["ETH"]  # only the one fully-valid item survives


def test_malformed_json_retries_then_degrades_to_empty():
    calls = {"n": 0}

    def chat(model_id: str, prompt: str) -> str:
        calls["n"] += 1
        return "not json at all"

    assert extract_claims(_post("x"), chat=chat, model_id="m", max_retries=2) == []
    assert calls["n"] == 3  # initial + 2 retries


def test_transport_error_degrades_to_empty():
    def chat(model_id: str, prompt: str) -> str:
        raise RuntimeError("boom")

    assert extract_claims(_post("x"), chat=chat, model_id="m") == []


def test_none_from_seam_is_honest_degradation():
    def chat(model_id: str, prompt: str):
        return None

    assert extract_claims(_post("x"), chat=chat, model_id="m") == []


def test_horizon_vocab_maps_to_days():
    assert horizon_to_days("1w") == 7
    assert horizon_to_days("3m") == 90
    assert set(HORIZON_DAYS) >= {"1d", "1w", "1m", "3m", "1y"}
    with pytest.raises(KeyError):
        horizon_to_days("nope")


def test_extractor_sorts_timeline_and_round_trips_dict():
    p1 = _post("BTC up", post_id="a", ts=datetime(2024, 1, 2, tzinfo=UTC))
    p2 = _post("ETH down", post_id="b", ts=datetime(2024, 1, 1, tzinfo=UTC))
    chat = _chat_returning(
        [{"entity": "X", "direction": "up", "horizon": "1d", "conviction": 0.5}]
    )
    claims = ClaimExtractor(chat=chat, model_id="m").extract([p1, p2])
    assert [c.ts for c in claims] == sorted(c.ts for c in claims)  # ascending by ts
    assert Claim.from_dict(claims[0].to_dict()) == claims[0]       # dict round-trip is lossless
