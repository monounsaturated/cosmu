# intent: the LLM qualitative→quantitative INDEX scorer — an LLM-AS-JUDGE that reads a typed set of source
# snippets for an `as_of` date and mints a STANDARDIZED, rubric-checked numeric score (e.g. reg_risk_crypto ∈
# [0,1], risk_on_off ∈ [-1,1]). The score is a POINT-IN-TIME FEATURE the gate can train on — NEVER a money move:
# the LLM only PROPOSES the number against an explicit rubric (Chain-of-Thought then strict JSON, Pydantic-
# validated with extra="forbid"), and the deterministic Gate alone disposes. inputs: an IndexRubric + evidence
# snippets + an injectable chat() seam; outputs: a validated IndexScore (or None on no-key/invalid). invariants:
# KEY-GATED + OFFLINE-testable (no key/seam → None, the source ingests nothing — honest degradation), the LLM
# output is range-checked against the rubric and any hallucinated evidence id is dropped, it runs cheap +
# temperature 0 + retry-on-invalid, and it is NEVER on the gate/scoring/money path. xAI default, OpenRouter
# fallback; cost is bounded by the cron cadence (one scoring call per index per pass) + the account spend cap.

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from cosmu.data.altdata import AltDataPoint, GdeltNewsProvider, NewsProvider
from cosmu.lab.llm import (
    OPENROUTER_URL,
    XAI_URL,
    ChatFn,
    _extract_json,
    openrouter_chat,
)

# Frozen, versioned transform — pinned into every index feature so a gate-passed survivor stays reproducible.
# Bump this string whenever a rubric or the prompt/schema changes.
INDEX_TRANSFORM_VERSION = "llm-index-v1"

# Cheap tiers — scoring a handful of snippets into one number needs no frontier model.
_XAI_MODEL = "grok-3-mini"
_OPENROUTER_MODEL = "openai/gpt-4o-mini"

_DEFAULT_EVIDENCE_LIMIT = 30  # snippets fed to the judge per call — bounded for cost + context


@dataclass(frozen=True)
class IndexRubric:
    """The explicit, frozen definition of ONE index: its name, its numeric range, the question the LLM judges,
    and the scale anchors (what lo / mid / hi MEAN). The rubric is the whole point — a vague score means nothing;
    a rubric-anchored one is reproducible and gate-checkable. `news_symbols` selects which headlines the default
    news-backed evidence provider pulls for this index."""

    name: str
    lo: float
    hi: float
    question: str  # the thing the LLM is asked to judge
    anchors: str  # explicit scale anchors — what lo / mid / hi mean
    news_symbols: tuple[str, ...]  # GDELT queries the default evidence provider reads for this index


# The starter index set (VISION §6 — "LLM-quality-scores as features"). Each is MARKET-WIDE (one read for the
# whole tape) and tier1 / low-confidence until it earns its place out-of-sample.
INDEX_RUBRICS: dict[str, IndexRubric] = {
    "reg_risk_crypto": IndexRubric(
        name="reg_risk_crypto",
        lo=0.0,
        hi=1.0,
        question="the level of REGULATORY-CRACKDOWN PRESSURE on crypto implied by the evidence",
        anchors=(
            "0.0 = no regulatory pressure (clear/supportive rules, approvals, friendly official statements); "
            "0.5 = mixed or uncertain (active debate, pending rules, mild enforcement chatter); "
            "1.0 = severe crackdown (bans, major enforcement actions, exchange shutdowns, criminal charges)."
        ),
        news_symbols=("BTCUSDT", "ETHUSDT"),
    ),
    "risk_on_off": IndexRubric(
        name="risk_on_off",
        lo=-1.0,
        hi=1.0,
        question="the macro / geopolitical RISK APPETITE of markets implied by the evidence",
        anchors=(
            "-1.0 = full risk-off (panic, war escalation, crisis, flight to safety); "
            "0.0 = neutral or mixed; "
            "+1.0 = full risk-on (easing, growth optimism, broad rally, calm geopolitics)."
        ),
        news_symbols=("BTCUSDT",),
    ),
}


# --------------------------------------------------------------------------- evidence (typed source snippets)


@dataclass(frozen=True)
class EvidenceSnippet:
    """ONE typed piece of evidence handed to the judge. `id` is a stable content hash the LLM cites in
    `evidence_ids` (so a score is traceable to its sources); `available_at` is the point-in-time stamp."""

    id: str
    text: str
    available_at: datetime


class EvidenceProvider(Protocol):
    def fetch_evidence(self, index_name: str, *, limit: int) -> list[EvidenceSnippet]:
        """Return the source snippets to score for one index (most-recent last)."""


def _evidence_id(text: str) -> str:
    """Stable 10-char content hash — the citable id for a snippet (dedupes wire-service repeats too)."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]  # noqa: S324 — id only, not security


class NewsEvidenceProvider:
    """Adapts a NewsProvider (GDELT by default) into the EvidenceProvider seam: pulls the headlines for an
    index's configured `news_symbols`, dedupes by content hash, and stamps each with its point-in-time
    availability. Offline-testable — inject any NewsProvider (FixtureNewsProvider in tests)."""

    def __init__(self, news: NewsProvider, rubrics: dict[str, IndexRubric] | None = None) -> None:
        self._news = news
        self._rubrics = rubrics or INDEX_RUBRICS

    def fetch_evidence(self, index_name: str, *, limit: int) -> list[EvidenceSnippet]:
        rubric = self._rubrics.get(index_name)
        if rubric is None:
            return []
        per = max(1, limit // max(1, len(rubric.news_symbols)))
        seen: set[str] = set()
        out: list[EvidenceSnippet] = []
        for symbol in rubric.news_symbols:
            for item in self._news.fetch_news(symbol, limit=per):
                eid = _evidence_id(item.headline)
                if eid in seen:
                    continue
                seen.add(eid)
                out.append(EvidenceSnippet(id=eid, text=item.headline, available_at=item.available_at))
        return out[-limit:]


class FixtureEvidenceProvider:
    """Deterministic offline evidence so the scorer + tests run with no key/network."""

    def __init__(self, snippets: dict[str, list[EvidenceSnippet]]) -> None:
        self.snippets = snippets

    def fetch_evidence(self, index_name: str, *, limit: int) -> list[EvidenceSnippet]:
        return self.snippets.get(index_name, [])[-limit:]


# --------------------------------------------------------------------------- the validated score (typed boundary)


class IndexScore(BaseModel):
    """The TYPED, validated thing the judge returns. `extra="forbid"` is the boundary where a smuggled field
    (e.g. a raw threshold) is REJECTED, not silently stripped. `score` is range-checked against the rubric in
    `score_index` (the range is per-index, so it cannot be a static field validator)."""

    model_config = ConfigDict(extra="forbid")

    score: float = Field(description="the rubric-anchored numeric score")
    confidence: float = Field(ge=0.0, le=1.0, description="the judge's self-assessed certainty")
    rationale: str = Field(default="", description="one-sentence why")
    evidence_ids: list[str] = Field(default_factory=list, description="cited snippet ids (subset of those shown)")


def _index_prompt(rubric: IndexRubric, snippets: list[EvidenceSnippet]) -> str:
    """Chain-of-Thought THEN strict JSON. The model reasons in one short paragraph, then emits ONE JSON object;
    `_extract_json` lifts the object (first `{` … last `}`) out of the reply."""
    evidence = "\n".join(f"[{s.id}] {s.text}" for s in snippets) or "(no evidence available)"
    return (
        "You are a quant research analyst scoring a standardized market index. Judge "
        + rubric.question
        + f".\nScore on a scale from {rubric.lo} to {rubric.hi} where: "
        + rubric.anchors
        + "\n\nFirst think step by step about what the evidence implies (ONE short paragraph, no JSON yet). "
        "Then on the FINAL line output ONLY a single JSON object, no prose, matching EXACTLY:\n"
        f'{{"score": <float {rubric.lo}..{rubric.hi}>, "confidence": <float 0..1>, '
        '"rationale": "<one sentence>", "evidence_ids": ["<id>", ...]}\n'
        "evidence_ids MUST be a subset of the bracketed ids below. Add NO other fields.\n\n"
        f"Evidence:\n{evidence}"
    )


def score_index(
    rubric: IndexRubric,
    snippets: list[EvidenceSnippet],
    *,
    chat: ChatFn,
    model_id: str,
    max_retries: int = 2,
) -> IndexScore | None:
    """Ask the judge for a rubric-anchored IndexScore, validate with Pydantic, range-check against the rubric,
    drop any hallucinated evidence id, retry on invalid. Returns None if the seam yields nothing (no key) or
    every attempt fails — the caller then ingests nothing (honest degradation), never a fabricated score."""
    valid_ids = {s.id for s in snippets}
    last_err = ""
    for _ in range(max(1, max_retries) + 1):
        prompt = _index_prompt(rubric, snippets)
        if last_err:
            prompt += f"\n\nYour previous reply was invalid ({last_err}). Reply with corrected JSON only."
        try:
            raw = chat(model_id, prompt)
        except Exception:  # noqa: BLE001 — a transport failure degrades to no-score, never crashes the pass
            return None
        if raw is None:
            return None  # no key / no model available → honest degradation
        try:
            score = IndexScore.model_validate(_extract_json(raw))
        except (ValueError, ValidationError) as exc:
            last_err = str(exc)[:160]
            continue
        if not (rubric.lo <= score.score <= rubric.hi):
            last_err = f"score {score.score} out of range [{rubric.lo}, {rubric.hi}]"
            continue
        # Defence in depth: a model that cites an id we never showed it is dropped (never trusted).
        score.evidence_ids = [e for e in score.evidence_ids if e in valid_ids]
        return score
    return None


# --------------------------------------------------------------------------- the AltDataProvider (ingest seam)


@dataclass
class LlmIndexProvider:
    """The AltDataProvider that mints LLM index scores as POINT-IN-TIME features. `fetch_series(metric)` gathers
    the metric's evidence, scores it against the rubric, and returns ONE AltDataPoint stamped now (a real-time
    judgement is knowable only when made — availability == observation, no look-ahead). Over many cron passes the
    append-only store accumulates a real time series WITH HISTORY for the gate to train on.

    KEY-GATED: with no chat seam (no key) `fetch_series` returns [] so the source ingests nothing — the system
    degrades honestly and never fabricates a score. The LLM ONLY proposes the number; the deterministic Gate
    alone disposes. Offline-testable: inject `chat=(model_id, prompt) -> str | None` + a FixtureEvidenceProvider."""

    evidence: EvidenceProvider
    chat: ChatFn | None = None
    model_id: str = _OPENROUTER_MODEL
    rubrics: dict[str, IndexRubric] = field(default_factory=lambda: dict(INDEX_RUBRICS))
    evidence_limit: int = _DEFAULT_EVIDENCE_LIMIT
    max_retries: int = 2

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        rubric = self.rubrics.get(metric)
        if rubric is None:
            return []
        if self.chat is None:  # no key / no seam → honest degradation (never a fabricated read)
            return []
        snippets = self.evidence.fetch_evidence(metric, limit=self.evidence_limit)
        if not snippets:
            return []
        score = score_index(rubric, snippets, chat=self.chat, model_id=self.model_id, max_retries=self.max_retries)
        if score is None:
            return []
        now = datetime.now(tz=UTC)
        pts = [AltDataPoint(ts=now, available_at=now, value=float(score.score))]
        return pts[-limit:] if limit > 0 else []


def build_index_provider_from_settings(
    settings,  # noqa: ANN001 — cosmu.config.settings.Settings (avoid an import cycle)
    *,
    evidence: EvidenceProvider | None = None,
) -> LlmIndexProvider:
    """Build the index provider WITH the operator's LLM key wired in — xAI preferred (already on Railway),
    OpenRouter fallback, both OpenAI-compatible. With NO key the chat seam is None so the provider ingests
    nothing (honest degradation). Default evidence = GDELT headlines; inject a fixture in tests."""
    chat: ChatFn | None = None
    model_id = _OPENROUTER_MODEL
    if getattr(settings, "xai_api_key", None):
        chat = openrouter_chat(settings.xai_api_key, url=XAI_URL)
        model_id = _XAI_MODEL
    elif getattr(settings, "openrouter_api_key", None):
        chat = openrouter_chat(settings.openrouter_api_key, url=OPENROUTER_URL)
        model_id = _OPENROUTER_MODEL
    ev = evidence if evidence is not None else NewsEvidenceProvider(GdeltNewsProvider())
    return LlmIndexProvider(evidence=ev, chat=chat, model_id=model_id)
