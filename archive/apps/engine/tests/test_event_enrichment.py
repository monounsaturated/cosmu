# enrich_market_events (ingest/llm_formatter.py): the ONE TypedFeature schema fills a MarketEvent's typed
# fields — LLM path (injected chat seam, never the network) vs the deterministic lexicon fallback — with
# content-only reads, batch caching by content_hash, version pins, and already-extracted passthrough.

from __future__ import annotations

import json
from datetime import UTC, datetime

from cosmu.data.events_store import MarketEvent
from cosmu.ingest.llm_formatter import (
    EVENT_EXTRACTOR_LEXICON_VERSION,
    EVENT_EXTRACTOR_VERSION,
    OpenRouterFormatter,
    enrich_market_events,
)

_TS = datetime(2026, 6, 10, 14, 30, tzinfo=UTC)


def _event(title: str, **kw) -> MarketEvent:
    defaults = dict(provider="gdelt", source="", symbols=("BTCUSDT",), ts=_TS, available_at=_TS, title=title)
    defaults.update(kw)
    return MarketEvent(**defaults)


def _formatter(calls: list[str]) -> OpenRouterFormatter:
    def chat(_model: str, prompt: str) -> str:
        calls.append(prompt)
        return json.dumps({"sign": 1, "magnitude": 0.8, "category": "regulatory", "confidence": 0.9})

    return OpenRouterFormatter(chat=chat)


def test_llm_path_fills_typed_fields_content_only():
    calls: list[str] = []
    [e] = enrich_market_events([_event("SEC approves bitcoin ETF")], formatter=_formatter(calls))
    assert (e.event_type, e.direction, e.magnitude, e.confidence) == ("regulatory", 1, 0.8, 0.9)
    assert e.extractor_version == EVENT_EXTRACTOR_VERSION
    # Content-only: the prompt carries the title and nothing about dates/outcomes/symbols.
    assert "SEC approves bitcoin ETF" in calls[0]
    assert _TS.date().isoformat() not in calls[0]
    assert "BTCUSDT" not in calls[0]


def test_batch_cache_one_llm_call_per_unique_title():
    calls: list[str] = []
    events = [_event("same headline"), _event("same headline"), _event("different headline")]
    enriched = enrich_market_events(events, formatter=_formatter(calls))
    assert len(calls) == 2  # the duplicate title costs nothing
    assert all(e.extractor_version == EVENT_EXTRACTOR_VERSION for e in enriched)


def test_lexicon_fallback_never_fabricates_a_category():
    [e] = enrich_market_events([_event("bitcoin surges on approval rally")])  # no formatter / no key
    assert e.extractor_version == EVENT_EXTRACTOR_LEXICON_VERSION
    assert e.event_type is None  # the lexicon can't categorize — None, not a guessed category
    assert e.direction is not None and e.magnitude is not None  # but direction/strength are real lexicon output


def test_already_extracted_events_pass_through_untouched():
    done = _event("old news", event_type="macro", direction=-1, magnitude=0.4,
                  confidence=0.5, extractor_version="some-older-version")
    calls: list[str] = []
    [e] = enrich_market_events([done], formatter=_formatter(calls))
    assert calls == []  # no re-spend on an already-extracted event
    assert e.event_type == "macro" and e.extractor_version == "some-older-version"
