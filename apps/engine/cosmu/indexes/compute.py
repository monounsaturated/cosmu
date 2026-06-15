# intent: turn an IndexSpec into ONE point-in-time value per symbol per pass, reusing the CANONICAL scorers —
# never reimplementing them: text indexes (event_topic / prompt_rubric) delegate to cosmu.lab.indexes
# (LlmIndexProvider + the rubric-anchored, validated, CoT-then-JSON LLM-as-judge); social indexes
# (single_account / social_bucket) delegate to cosmu.mind.authority (the deterministic authority-weighted
# claim signal). inputs: an IndexSpec + injectable seams (chat / evidence / claims+bars); outputs: {symbol:
# AltDataPoint} stamped now, appended PIT to alt_data under provider='index'; invariants: SCORING IS THE
# EXISTING PRIMITIVE (no second scoring path → no drift), the LLM standardizes/judges text ONLY at compute time
# behind the frozen rubric (never a gate/money path), an empty source (no key / no evidence / no claims) yields
# {} (honest — never a fabricated value), availability == observation (no look-ahead). History accrues over
# cron passes exactly like LlmIndexProvider / AuthorityProvider already do.

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from cosmu.data.altdata import AltDataPoint, NewsItem, PgAltDataStore
from cosmu.indexes.spec import INDEX_PROVIDER, IndexSpec
from cosmu.knowledge.store import Store
from cosmu.lab.indexes import (
    EvidenceProvider,
    IndexRubric,
    LlmIndexProvider,
    NewsEvidenceProvider,
)

# Standard sentiment anchors for an event_topic index (a prompt_rubric supplies its own via the definition).
_SENTIMENT_ANCHORS = (
    "-1.0 = strongly negative / risk-off / bearish for the topic; "
    "0.0 = neutral or mixed; "
    "+1.0 = strongly positive / risk-on / bullish for the topic."
)


# --------------------------------------------------------------------------- spec → rubric (the canonical scorer's input)


def rubric_from_spec(spec: IndexSpec) -> IndexRubric:
    """Build the cosmu.lab.indexes IndexRubric this index is scored by. event_topic → a sentiment-about-the-topic
    rubric in [-1,1]; prompt_rubric → the operator's own question/anchors/range. `news_symbols` are the GDELT
    queries the default evidence provider reads (the topic itself for event_topic)."""
    d = spec.definition
    if spec.kind == "event_topic":
        topic = str(d["topic"])
        return IndexRubric(
            name=spec.metric, lo=-1.0, hi=1.0,
            question=f"the market sentiment implied by recent news about: {topic}",
            anchors=_SENTIMENT_ANCHORS,
            news_symbols=tuple(d.get("news_symbols") or (topic,)),
        )
    # prompt_rubric — the operator defines the question; range/anchors default to sentiment if unspecified.
    return IndexRubric(
        name=spec.metric, lo=float(d.get("lo", -1.0)), hi=float(d.get("hi", 1.0)),
        question=str(d["prompt"]), anchors=str(d.get("anchors", _SENTIMENT_ANCHORS)),
        news_symbols=tuple(d.get("news_symbols") or ()),
    )


class _TopicGdeltNews:
    """A NewsProvider over a FREE-TEXT GDELT query (each `symbol` is used verbatim as the query) — so an
    event_topic index ('middle east conflict') sources real headlines, not a ticker mapping. Network failure
    → [] (honest). Only used as the default; tests inject a FixtureEvidenceProvider instead."""

    def __init__(self, *, timespan: str = "7d") -> None:
        self._timespan = timespan

    def fetch_news(self, symbol: str, *, limit: int) -> list[NewsItem]:
        import json
        import urllib.parse
        import urllib.request

        from cosmu.data.altdata import _news_from_gdelt, _ssl_context

        if not symbol.strip():
            return []
        try:
            params = urllib.parse.urlencode(
                {"query": symbol, "mode": "ArtList", "format": "json", "maxrecords": min(limit, 250),
                 "timespan": self._timespan, "sort": "DateAsc"}
            )
            url = f"https://api.gdeltproject.org/api/v2/doc/doc?{params}"
            with urllib.request.urlopen(url, timeout=20, context=_ssl_context()) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
            return _news_from_gdelt(payload)
        except Exception:  # noqa: BLE001 — offline / rate-limited: no evidence this pass
            return []


def _default_evidence(spec: IndexSpec, rubric: IndexRubric) -> EvidenceProvider:
    """Default evidence source for a text index: GDELT headlines for the rubric's news queries."""
    return NewsEvidenceProvider(_TopicGdeltNews(), rubrics={spec.metric: rubric})


# --------------------------------------------------------------------------- per-pass compute (one point / symbol)


def compute_text_point(
    spec: IndexSpec,
    *,
    chat: Callable[[str, str], str | None] | None,
    evidence: EvidenceProvider | None = None,
    model_id: str = "openai/gpt-4o-mini",
) -> dict[str, AltDataPoint]:
    """One PIT score for a text index, via the canonical LlmIndexProvider. The SAME headline set + rubric →
    the SAME judged number (content the model sees is fixed; temperature 0 upstream). No key → {} (honest)."""
    if chat is None:
        return {}
    rubric = rubric_from_spec(spec)
    ev = evidence or _default_evidence(spec, rubric)
    provider = LlmIndexProvider(evidence=ev, chat=chat, model_id=model_id, rubrics={spec.metric: rubric})
    pts = provider.fetch_series("MARKET", spec.metric, limit=1)
    if not pts:
        return {}
    point = pts[0]  # a text index is one topic series — attached to each declared symbol (MARKET if market-wide)
    return {sym: point for sym in spec.symbols()}


def compute_social_point(
    spec: IndexSpec,
    *,
    claims: list,
    bars_by_entity: dict[str, list],
    posts: list | None = None,
    events: list | None = None,
    now: datetime | None = None,
) -> dict[str, AltDataPoint]:
    """One PIT value per symbol for a social index, via the deterministic authority scorer. Per-entity index →
    one point per entity; market-wide → the mean across entities. No claims → {} (honest, never fabricated)."""
    from cosmu.mind.authority import AuthorityProvider

    if not claims:
        return {}
    provider = AuthorityProvider(claims=claims, bars_by_entity=bars_by_entity, posts=posts, events=events, now=now)
    entities = list(spec.entities) if spec.entities else sorted({c.entity for c in claims})
    per_entity: dict[str, AltDataPoint] = {}
    for entity in entities:
        pts = provider.fetch_series(entity, "authority_weighted_claim_signal", limit=1)
        if pts:
            per_entity[entity] = pts[0]
    if not per_entity:
        return {}
    if not spec.market_wide:
        return per_entity
    ts = max(p.available_at for p in per_entity.values())
    value = round(sum(p.value for p in per_entity.values()) / len(per_entity), 6)
    return {"MARKET": AltDataPoint(ts=ts, available_at=ts, value=value)}


# --------------------------------------------------------------------------- storage (PIT, append-only)


def store_index_points(store: Store, spec: IndexSpec, points_by_symbol: dict[str, AltDataPoint]) -> int:
    """Append each symbol's point to alt_data (provider='index', metric=idx_<id>). Returns points written."""
    alt = PgAltDataStore(store)
    written = 0
    for symbol, point in points_by_symbol.items():
        alt.append(INDEX_PROVIDER, symbol, spec.metric, [point])
        written += 1
    return written


def read_index_series(store: Store, spec: IndexSpec, symbol: str = "MARKET") -> list[AltDataPoint]:
    """Full point-in-time history of one index symbol's accrued series (read_all)."""
    return PgAltDataStore(store).read_all(INDEX_PROVIDER, symbol, spec.metric)


def now_utc() -> datetime:
    return datetime.now(tz=UTC)
