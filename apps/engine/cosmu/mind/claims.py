# intent: PHASE 1 of "PageRank for credibility" — CLAIM EXTRACTION. An LLM-as-extractor reads a voice's timeline
# (X → Reddit → Substack/news posts ingested in Phase 0) and turns each predictive utterance into a STRUCTURED,
# typed Claim {entity, direction, horizon, conviction, ts}. The LLM ONLY proposes the structure (instructor-style:
# prompt for the shape, validate with Pydantic extra="forbid", retry on invalid); the deterministic resolver
# (Phase 2) and authority ranker (Phase 3) dispose. inputs: VoicePost timeline units + an injectable chat() seam;
# outputs: a list of typed Claim records. invariants: KEY-GATED + OFFLINE-testable (no chat seam → [], the system
# extracts nothing — honest degradation, never a fabricated claim); the claim timestamp is STAMPED from the post's
# own availability (ts == available_at), NEVER a model-proposed date — so a claim can never read the future; every
# proposed field is range/vocab-checked and an un-parseable item is dropped (the batch survives). The LLM is NEVER
# on the gate/scoring/money path.

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from cosmu.lab.llm import (
    OPENROUTER_URL,
    XAI_URL,
    ChatFn,
    openrouter_chat,
)

# Frozen, versioned transform — pinned so a downstream gate-passed survivor that depends on extracted claims
# stays reproducible. Bump whenever the extraction prompt or the Claim schema changes.
CLAIM_EXTRACT_VERSION = "claim-extract-v1"

# Cheap tiers — turning a post into a handful of typed claims needs no frontier model.
_XAI_MODEL = "grok-3-mini"
_OPENROUTER_MODEL = "openai/gpt-4o-mini"

# Controlled vocabularies. Direction is the predicted move; horizon is the (canonical) time-to-resolution. Keeping
# both as a fixed set is what makes Phase 2's deterministic resolution possible — a free-form "soon" cannot be
# resolved against bars, but "1w" can.
Direction = Literal["up", "down", "flat"]

# Canonical horizon code → resolution window in days. The extractor maps the model's horizon onto one of these;
# anything outside the set is rejected (the item is dropped, never silently coerced).
HORIZON_DAYS: dict[str, int] = {
    "intraday": 1,
    "1d": 1,
    "3d": 3,
    "1w": 7,
    "2w": 14,
    "1m": 30,
    "3m": 90,
    "6m": 180,
    "1y": 365,
}


def horizon_to_days(horizon: str) -> int:
    """Canonical horizon code → its resolution window in days (raises KeyError on an unknown code)."""
    return HORIZON_DAYS[horizon]


# --------------------------------------------------------------------------- the Phase-0 timeline unit (input)


@dataclass(frozen=True)
class VoicePost:
    """ONE utterance from a voice's timeline — the unit Phase 0 ingests (xAI/Grok for X, Reddit API, RSS for
    newsletters) and the unit Phase 1 extracts claims from. `ts` is the post's point-in-time availability: a
    public post is knowable the moment it is published, so ts == available_at (no look-ahead). `refs` lists the
    post_ids / urls this post cites or quotes — the raw material for Phase 3's citation graph (who-cites-whom)."""

    handle: str           # the author ("@elonmusk", "u/spez", a newsletter slug) — normalized upstream
    platform: str         # "x" | "reddit" | "substack" | "news"
    post_id: str          # stable id within the platform (for primacy + the citation graph)
    text: str             # the raw post text the extractor reads
    ts: datetime          # publication time == availability (point-in-time; a public post is known when posted)
    url: str = ""         # canonical url (provenance)
    refs: tuple[str, ...] = ()  # post_ids / urls this post cites or quotes (Phase 3 citation edges)


# --------------------------------------------------------------------------- the LLM proposal (typed boundary)


class _ClaimProposal(BaseModel):
    """The TYPED, validated shape the extractor asks the LLM for — ONE predictive claim. `extra="forbid"` is the
    boundary where a smuggled field (a price target, a position size) is REJECTED, not silently kept. The model
    proposes only WHAT was claimed (entity/direction/horizon/conviction) + a verbatim `quote`; the claim's
    timestamp and provenance are attached deterministically from the post (never trusted to the model)."""

    model_config = ConfigDict(extra="forbid")

    entity: str = Field(description="the asset the claim is about, e.g. BTC, ETH, AAPL")
    direction: Direction = Field(description="predicted move: up | down | flat")
    horizon: str = Field(description="canonical horizon code: " + " | ".join(HORIZON_DAYS))
    conviction: float = Field(ge=0.0, le=1.0, description="how strongly the claim is asserted, 0..1")
    quote: str = Field(default="", description="the verbatim sentence the claim was extracted from")
    rationale: str = Field(default="", description="one-line why, in the author's framing")

    @field_validator("entity")
    @classmethod
    def _norm_entity(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if not v:
            raise ValueError("empty entity")
        return v

    @field_validator("horizon")
    @classmethod
    def _known_horizon(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v not in HORIZON_DAYS:
            raise ValueError(f"unknown horizon: {v!r}")
        return v


# --------------------------------------------------------------------------- the typed domain object (output)


@dataclass(frozen=True)
class Claim:
    """A typed, resolved-against-nothing-yet predictive claim — the Phase 1 output Phase 2 scores and Phase 3
    ranks. `ts` is the claim timestamp == the post's availability (stamped from the post, no look-ahead). The
    provenance fields (handle/platform/post_id/url) carry the claim back to the voice and the citation graph."""

    handle: str
    platform: str
    post_id: str
    entity: str
    direction: Direction
    horizon: str
    horizon_days: int
    conviction: float
    ts: datetime          # claim timestamp == available_at (point-in-time)
    quote: str = ""
    rationale: str = ""
    url: str = ""

    def to_dict(self) -> dict:
        d = {
            "handle": self.handle,
            "platform": self.platform,
            "post_id": self.post_id,
            "entity": self.entity,
            "direction": self.direction,
            "horizon": self.horizon,
            "horizon_days": self.horizon_days,
            "conviction": self.conviction,
            "ts": self.ts.isoformat(),
            "quote": self.quote,
            "rationale": self.rationale,
            "url": self.url,
        }
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Claim:
        return cls(
            handle=d["handle"],
            platform=d["platform"],
            post_id=d["post_id"],
            entity=d["entity"],
            direction=d["direction"],
            horizon=d["horizon"],
            horizon_days=int(d["horizon_days"]),
            conviction=float(d["conviction"]),
            ts=datetime.fromisoformat(d["ts"]),
            quote=d.get("quote", ""),
            rationale=d.get("rationale", ""),
            url=d.get("url", ""),
        )


def _claim_from_proposal(p: _ClaimProposal, post: VoicePost) -> Claim:
    """Attach the post's provenance + point-in-time timestamp to a validated proposal. The claim's ts is the
    POST's availability — never a model-proposed date — so a claim can never be stamped earlier than it was made."""
    return Claim(
        handle=post.handle,
        platform=post.platform,
        post_id=post.post_id,
        entity=p.entity,
        direction=p.direction,
        horizon=p.horizon,
        horizon_days=horizon_to_days(p.horizon),
        conviction=float(p.conviction),
        ts=post.ts,
        quote=p.quote or "",
        rationale=p.rationale or "",
        url=post.url,
    )


# --------------------------------------------------------------------------- extraction (instructor-style)


def _extract_json_list(text: str) -> list:
    """Pull the first JSON array out of the model text (models sometimes wrap it in prose/markdown fences)."""
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON array in model response")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, list):
        raise ValueError("JSON value is not an array")
    return data


def _extract_prompt(post: VoicePost) -> str:
    """Ask the model to read ONE post and emit a JSON array of predictive claims (possibly empty). Chain-of-Thought
    is deliberately NOT requested here — we want only the array, and an empty array is the correct answer for a
    non-predictive post."""
    return (
        "You are a financial-claims extractor. Read ONE social-media / newsletter post and extract every "
        "PREDICTIVE, DIRECTIONAL claim it makes about a tradable asset's FUTURE price or value. Ignore "
        "non-predictive chatter, past-tense observations, jokes, and questions.\n\n"
        "Output ONLY a JSON array (no prose, no markdown). Each element is one claim, matching EXACTLY:\n"
        '{"entity": "<asset ticker/symbol, e.g. BTC>", "direction": "<up|down|flat>", '
        '"horizon": "<one of: ' + " | ".join(HORIZON_DAYS) + '>", '
        '"conviction": <float 0..1, how strongly asserted>, '
        '"quote": "<the verbatim sentence>", "rationale": "<one-line why>"}\n'
        "Rules: entity is the asset symbol in UPPERCASE; horizon MUST be one of the listed codes (map vague "
        "phrasing to the nearest code — 'next week'→1w, 'this year'→1y); add NO other fields. If the post makes "
        "no predictive claim, output exactly []\n\n"
        f"Post by {post.handle} on {post.platform}:\n\"\"\"\n{post.text}\n\"\"\""
    )


def extract_claims(
    post: VoicePost,
    *,
    chat: ChatFn,
    model_id: str,
    max_retries: int = 2,
) -> list[Claim]:
    """Extract every predictive claim from ONE post. Ask the LLM for a JSON array, validate each element with
    Pydantic (extra="forbid"), DROP any un-parseable element (the batch survives), and stamp provenance + the
    point-in-time timestamp deterministically from the post. Returns [] when the seam yields nothing (no key),
    every retry fails, or the post simply makes no claim — never a fabricated claim."""
    last_err = ""
    for _ in range(max(1, max_retries) + 1):
        prompt = _extract_prompt(post)
        if last_err:
            prompt += f"\n\nYour previous reply was invalid ({last_err}). Reply with a corrected JSON array only."
        try:
            raw = chat(model_id, prompt)
        except Exception:  # noqa: BLE001 — a transport failure degrades to no-claims, never crashes the pass
            return []
        if raw is None:
            return []  # no key / no model available → honest degradation (extract nothing)
        try:
            items = _extract_json_list(raw)
        except (ValueError, json.JSONDecodeError) as exc:
            last_err = str(exc)[:160]
            continue
        claims: list[Claim] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                proposal = _ClaimProposal.model_validate(item)
            except (ValueError, ValidationError):
                continue  # drop the un-parseable element; the rest of the batch survives
            claims.append(_claim_from_proposal(proposal, post))
        return claims
    return []


@dataclass
class ClaimExtractor:
    """The timeline-level extractor: runs `extract_claims` over a voice's posts. KEY-GATED — with no chat seam
    (no key) it extracts nothing (honest degradation, never a fabricated claim). The LLM ONLY proposes structure;
    the deterministic resolver + authority ranker dispose. Offline-testable: inject `chat=(model_id, prompt)->str|None`."""

    chat: ChatFn | None = None
    model_id: str = _OPENROUTER_MODEL
    max_retries: int = 2

    def extract(self, posts: list[VoicePost]) -> list[Claim]:
        if self.chat is None:  # no key / no seam → honest degradation
            return []
        out: list[Claim] = []
        for post in posts:
            out.extend(extract_claims(post, chat=self.chat, model_id=self.model_id, max_retries=self.max_retries))
        # Deterministic, stable order — by timestamp then post id (Phase 2/3 consume an ordered timeline).
        out.sort(key=lambda c: (c.ts, c.post_id, c.entity, c.direction))
        return out


def build_claim_extractor_from_settings(settings) -> ClaimExtractor:  # noqa: ANN001 — cosmu.config.settings.Settings
    """Build the extractor WITH the operator's LLM key wired in — xAI preferred (already on Railway), OpenRouter
    fallback, both OpenAI-compatible. With NO key the chat seam is None so the extractor ingests nothing (honest
    degradation). The LLM is NEVER on the gate/scoring/money path."""
    chat: ChatFn | None = None
    model_id = _OPENROUTER_MODEL
    if getattr(settings, "xai_api_key", None):
        chat = openrouter_chat(settings.xai_api_key, url=XAI_URL)
        model_id = _XAI_MODEL
    elif getattr(settings, "openrouter_api_key", None):
        chat = openrouter_chat(settings.openrouter_api_key, url=OPENROUTER_URL)
        model_id = _OPENROUTER_MODEL
    return ClaimExtractor(chat=chat, model_id=model_id)
