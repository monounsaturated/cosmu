# intent: the ACTIONABLE-CALL CLASSIFIER — the pre-scoring filter that keeps only DIRECTIONAL asset calls and
# drops NEUTRAL macro-commentary and SARCASM. The V1 @elontrades demo showed the leak: 5/8 posts were neutral
# market chatter and a "buy BTC when MSTR goes to zero" line was sarcasm mis-tagged bullish — both would have
# polluted the score with calls the account never really made. This layer is LIGHTWEIGHT and HEURISTIC by default
# (regex/markers on the verbatim text + the already-parsed direction) with an OPTIONAL LLM EXTRACTION PROMPT for
# the local runner (the prompt is just a string here — no network, no key on this path). invariants: LEAN +
# CONSERVATIVE — the operator's rule is that authority is inaccurate by design and the only way to RUIN it is to
# be OVERLY STRICT, so we DROP only on a POSITIVE sarcasm/neutral signal and KEEP by default (an empty-text call,
# or one with a clear directional word, stays); a flat (range/sideways) call is a legitimate explicit call and is
# NOT dropped here (the scorer handles it for calibration); pure + deterministic (the score downstream is math, so
# a mis-keep can only ever add a weak row, never fabricate a number). Accept misses — this trims the worst noise,
# it does not adjudicate every post.

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from cosmu.authority.ingest import DIRECTION_SYNONYMS
from cosmu.authority.models import AccountCall

# ── Sarcasm (DROP) ────────────────────────────────────────────────────────────────────────────────────────────
# Markers that flip a post to sarcasm/joke regardless of any directional word it contains ("buy BTC when MSTR goes
# to zero" carries "buy" but is sarcasm). Lower-cased substring match. Kept lean — the obvious tells social posts
# actually use; misses are accepted.
SARCASM_MARKERS: tuple[str, ...] = (
    "/s", " jk", "lol", "lmao", "rofl", "🤡", "😂", "🙃", "yeah right", "yeah, right", "sure thing",
    "said no one", "totally not", "not financial advice but", "this is satire", "/sarcasm", "as if",
)
# Absurd-conditional sarcasm: a call gated on something that never happens ("when MSTR goes to zero", "when hell
# freezes over", "when pigs fly", "when the fed prints to infinity"). The conditional makes it a non-call.
SARCASM_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bwhen\b.*\bgoes? to (zero|0)\b"),
    re.compile(r"\bwhen\b.*\b(hell freezes|pigs fly|the sun (explodes|burns out))\b"),
    re.compile(r"\bif\b.*\bgoes? to (zero|0)\b.*\b(buy|sell|short|long)\b"),
    re.compile(r"\bnarrator\b.*\b(it|they|he|she) (did|didn't|wasn't|wouldn't)\b"),  # "narrator voice" meme
)

# ── Neutral macro-commentary (DROP) ───────────────────────────────────────────────────────────────────────────
# Commentary with no directional claim: a question, a hedge, a "watching"/"interesting" observation. Dropped ONLY
# when there is ALSO no clear directional word in the text (so an explicit "I'm long BTC, thoughts?" survives).
NEUTRAL_MARKERS: tuple[str, ...] = (
    "thoughts?", "what do you think", "we'll see", "we will see", "no idea", "who knows", "could go either way",
    "interesting chart", "watching closely", "keeping an eye", "time will tell", "not sure", "hard to say",
    "let's see", "remains to be seen", "macro is", "fed is", "cpi", "fomc", "just my opinion",
)
# Hedge words — many of them with no directional word = commentary, not a call.
HEDGE_WORDS: tuple[str, ...] = (
    "might", "maybe", "perhaps", "possibly", "could", "should probably", "i guess", "seems like", "kinda",
    "sort of", "leaning", "unsure",
)

# Direction words that count as a CLEAR directional claim in free text (a superset of the ingest synonym keys,
# matched as whole words). Their presence keeps a post even amid some hedging.
_DIRECTION_WORDS: frozenset[str] = frozenset(
    k for k in DIRECTION_SYNONYMS if k.isalpha() and len(k) > 1
)
_WORD_RE = re.compile(r"[a-z]+")


@dataclass(frozen=True)
class CallClassification:
    """The verdict on ONE call. `is_actionable` gates whether it reaches the scorer; `confidence` is how sure the
    classifier is of THAT verdict (not of the market direction); `reason` is a short tag for display/debug:
    'directional' (kept, clear up/down word) · 'flat_call' (kept, explicit range call) · 'no_text' (kept, no text
    to judge — trust the parsed direction) · 'sarcasm' (dropped) · 'neutral' (dropped, commentary not a call)."""

    is_actionable: bool
    confidence: float
    reason: str


def _has_directional_word(low: str) -> bool:
    return any(w in _DIRECTION_WORDS for w in _WORD_RE.findall(low))


def classify_text(text: str, direction: str) -> CallClassification:
    """Heuristic verdict from the verbatim post text + the already-parsed direction. Order matters: SARCASM first
    (it overrides directional words), then NEUTRAL commentary, else the call is actionable. Empty text → KEEP
    (we have a parsed direction and no text evidence to drop on — lean, never over-strict)."""
    low = (text or "").strip().lower()
    if not low:
        # No text to judge. A flat call with no text is a weak signal; a directional one we trust the parse.
        return CallClassification(True, 0.4, "flat_call" if direction == "flat" else "no_text")

    # Sarcasm — drop even if a directional word is present.
    if any(m in low for m in SARCASM_MARKERS) or any(p.search(low) for p in SARCASM_PATTERNS):
        return CallClassification(False, 0.85, "sarcasm")

    has_dir = _has_directional_word(low)
    neutral_hits = sum(1 for m in NEUTRAL_MARKERS if m in low)
    hedge_hits = sum(1 for w in HEDGE_WORDS if w in low)
    is_question = low.endswith("?")

    # Neutral commentary — drop ONLY when there is no clear directional word AND a neutral/hedge/question signal.
    if not has_dir and (neutral_hits or is_question or hedge_hits >= 2):
        return CallClassification(False, 0.65, "neutral")

    if direction == "flat" and not has_dir:
        # An explicit flat/range parse with neutral-ish but non-disqualifying text — keep, but it is the weakest
        # actionable class (the scorer credits it for calibration only).
        return CallClassification(True, 0.5, "flat_call")

    # A clear directional call. Strong when an explicit up/down word is present; a touch weaker when the direction
    # came only from the parse (e.g. a structured field) but the text shows no disqualifier.
    return CallClassification(True, 0.8 if has_dir else 0.6, "directional")


def classify_call(call: AccountCall) -> CallClassification:
    """Classify ONE typed call (uses its verbatim `text` + parsed `direction`). See classify_text."""
    return classify_text(call.text, call.direction)


def partition_actionable(
    calls: Sequence[AccountCall], *, min_confidence: float = 0.0
) -> tuple[list[AccountCall], list[tuple[AccountCall, CallClassification]]]:
    """Split a corpus into (kept, dropped). A call is DROPPED when the classifier judges it non-actionable
    (sarcasm/neutral) with confidence >= `min_confidence` (default 0.0 → any positive drop signal counts). Dropped
    rows are returned WITH their verdict for provenance/auditing. Conservative: a kept call is always actionable;
    we never drop on uncertainty."""
    kept: list[AccountCall] = []
    dropped: list[tuple[AccountCall, CallClassification]] = []
    for c in calls:
        verdict = classify_call(c)
        if (not verdict.is_actionable) and verdict.confidence >= min_confidence:
            dropped.append((c, verdict))
        else:
            kept.append(c)
    return kept, dropped


def filter_actionable(calls: Sequence[AccountCall], *, min_confidence: float = 0.0) -> list[AccountCall]:
    """Just the kept (actionable) calls — the pre-scoring filter the scoreboard runs. See partition_actionable."""
    return partition_actionable(calls, min_confidence=min_confidence)[0]


# ── Optional LLM extraction prompt (for the LOCAL runner only) ───────────────────────────────────────────────
# The heuristics above are the default + the test surface. When the local runner DOES have the xAI/Grok (or
# Claude) key, a stronger first pass is to have the model EXTRACT structured calls from raw posts and SELF-DROP
# neutral/sarcasm — handing back exactly the ingest-shaped JSON `parse_calls` already eats. This is just the
# PROMPT (a string); the HTTP call + key live in the local runner, never here (cloud-safe). The SCORE stays math,
# so even a hallucinated extraction can only add/drop a row — never move the number.

EXTRACTION_SYSTEM_PROMPT = (
    "You extract DIRECTIONAL ASSET CALLS from social posts for a quant research store. For each post that makes a "
    "CLEAR call that a specific tradable asset will go UP or DOWN, emit one JSON object. DROP anything that is "
    "neutral macro-commentary, a question, a hedge, a joke, or SARCASM (e.g. 'buy BTC when MSTR goes to zero' is "
    "sarcasm — DROP it). Never invent a call the author did not clearly make; when unsure, DROP. Output ONLY a "
    "JSON array (possibly empty), no prose."
)

# The exact per-call shape to request — a subset of what cosmu.authority.ingest.parse_calls accepts (extra keys
# are ignored; missing required keys drop the row downstream). `direction` must be one of up|down (or flat for an
# explicit range call); `confidence` is 0..1; `ts` is the post's ISO-8601 UTC time; `call_id` the post id.
EXTRACTION_SCHEMA_HINT = (
    '{"account": "@handle", "platform": "x", "asset": "BTC", "direction": "up|down|flat", '
    '"confidence": 0.0-1.0, "ts": "2026-06-29T12:00:00Z", "call_id": "<post id>", "text": "<verbatim>", '
    '"url": "<permalink>"}'
)


def build_extraction_prompt(posts: Sequence[str], *, account: str | None = None, platform: str = "x") -> str:
    """Assemble the LLM extraction prompt for a batch of raw post texts — the optional stronger first pass for the
    LOCAL runner. Returns a single string (system instruction + schema + the enumerated posts); the runner sends
    it to its model and feeds the JSON array straight into `parse_calls`. Pure string assembly (deterministic, no
    network), so it is unit-testable and cloud-safe. `account`/`platform` are hints the model stamps onto every
    extracted call when the post stream is from one known handle."""
    header = EXTRACTION_SYSTEM_PROMPT
    if account:
        header += f"\nAll posts below are from {account} on {platform}; stamp account={account}, platform={platform}."
    schema = f"Each emitted object: {EXTRACTION_SCHEMA_HINT}"
    body = "\n".join(f"[{i}] {p.strip()}" for i, p in enumerate(posts) if p and p.strip())
    return f"{header}\n\n{schema}\n\nPOSTS:\n{body}\n\nJSON array:"


__all__ = [
    "CallClassification",
    "EXTRACTION_SCHEMA_HINT",
    "EXTRACTION_SYSTEM_PROMPT",
    "HEDGE_WORDS",
    "NEUTRAL_MARKERS",
    "SARCASM_MARKERS",
    "SARCASM_PATTERNS",
    "build_extraction_prompt",
    "classify_call",
    "classify_text",
    "filter_actionable",
    "partition_actionable",
]
