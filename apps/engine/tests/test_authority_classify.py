# The ACTIONABLE-CALL CLASSIFIER (cosmu/authority/classify.py) — the pre-scoring filter that keeps only
# DIRECTIONAL asset calls and drops NEUTRAL macro-commentary + SARCASM. Pins the V1 @elontrades leaks:
#   * a sarcasm line ("buy BTC when MSTR goes to zero lol") is DROPPED even though it carries "buy";
#   * neutral chatter / a question with no directional word is DROPPED;
#   * a clear directional call is KEPT (high confidence);
#   * CONSERVATIVE by design — an empty-text call (no evidence) and an explicit flat/range call are KEPT (the
#     operator's rule: the only way to ruin authority is to be OVERLY STRICT);
#   * partition/filter split a corpus correctly; the optional LLM extraction prompt assembles deterministically.

from __future__ import annotations

from datetime import UTC, datetime

from cosmu.authority.classify import (
    build_extraction_prompt,
    classify_text,
    filter_actionable,
    partition_actionable,
)
from cosmu.authority.models import AccountCall

T0 = datetime(2024, 1, 1, tzinfo=UTC)


def _call(asset: str, direction: str, text: str, *, call_id: str = "") -> AccountCall:
    return AccountCall(account="@a", platform="x", asset=asset, direction=direction,  # type: ignore[arg-type]
                       ts=T0, conviction=0.6, call_id=call_id, text=text, source="xai")


# --------------------------------------------------------------------------- DROP: sarcasm


def test_sarcasm_with_a_directional_word_is_dropped():
    """The headline V1 miss: 'buy BTC when MSTR goes to zero' was tagged bullish but is sarcasm — drop it even
    though it contains 'buy'."""
    v = classify_text("buy BTC when MSTR goes to zero lol", "up")
    assert v.is_actionable is False
    assert v.reason == "sarcasm"
    assert v.confidence >= 0.8


def test_absurd_conditional_is_sarcasm():
    v = classify_text("sure, I'll go long when pigs fly", "up")
    assert v.is_actionable is False and v.reason == "sarcasm"


def test_explicit_sarcasm_marker_drops():
    assert classify_text("ETH to 10k by friday /s", "up").is_actionable is False


# --------------------------------------------------------------------------- DROP: neutral commentary


def test_neutral_question_without_direction_is_dropped():
    """Neutral macro-commentary — a question, no directional claim. (5/8 of the V1 posts were this.)"""
    v = classify_text("Interesting chart on BTC here, thoughts?", "up")
    assert v.is_actionable is False and v.reason == "neutral"


def test_hedged_commentary_without_direction_is_dropped():
    v = classify_text("the fed is unpredictable, could go either way, not sure", "flat")
    assert v.is_actionable is False and v.reason == "neutral"


# --------------------------------------------------------------------------- KEEP: directional


def test_clear_directional_call_is_kept_high_confidence():
    v = classify_text("I'm long BTC here, breaking out", "up")
    assert v.is_actionable is True and v.reason == "directional"
    assert v.confidence >= 0.8


def test_directional_word_survives_some_hedging():
    """A clear directional word keeps the call even with one hedge token — we drop neutral chatter, not opinions."""
    v = classify_text("might be early but I'm short SOL", "down")
    assert v.is_actionable is True


# --------------------------------------------------------------------------- KEEP: conservative (never over-strict)


def test_empty_text_is_kept_we_trust_the_parse():
    """No text to judge → KEEP (we have a parsed direction; dropping would be over-strict)."""
    v = classify_text("", "up")
    assert v.is_actionable is True and v.reason == "no_text"
    assert v.confidence < 0.6  # but it is the weakest actionable class


def test_explicit_flat_call_is_kept():
    """A flat/range call is a legitimate explicit call (scored for calibration) — not neutral commentary."""
    v = classify_text("BTC chops sideways into the range", "flat")
    assert v.is_actionable is True


# --------------------------------------------------------------------------- partition / filter


def test_partition_splits_kept_and_dropped():
    calls = [
        _call("BTC", "up", "long BTC, clear breakout", call_id="keep"),
        _call("BTC", "up", "buy BTC when MSTR goes to zero lol", call_id="sarc"),
        _call("ETH", "up", "thoughts on ETH?", call_id="neutral"),
    ]
    kept, dropped = partition_actionable(calls)
    assert [c.call_id for c in kept] == ["keep"]
    assert {c.call_id for c, _ in dropped} == {"sarc", "neutral"}
    assert filter_actionable(calls) == kept


# --------------------------------------------------------------------------- optional LLM extraction prompt


def test_build_extraction_prompt_is_deterministic_and_enumerates_nonblank_posts():
    posts = ["BTC to the moon", "   ", "thoughts on ETH?"]
    prompt = build_extraction_prompt(posts, account="@elontrades", platform="x")
    assert build_extraction_prompt(posts, account="@elontrades") == build_extraction_prompt(posts, account="@elontrades")  # deterministic
    assert "@elontrades" in prompt and "SARCASM" in prompt
    assert "[0] BTC to the moon" in prompt
    assert "[2] thoughts on ETH?" in prompt  # blank [1] skipped, index preserved
    assert "[1]" not in prompt
