"""Tests for the news event scorer and source trust scoreboard (offline, no network, no LLM key)."""

from datetime import UTC, datetime, timedelta

import pytest

from cosmu.data.altdata import AltDataPoint, AltDataStore, FixtureNewsProvider, NewsItem
from cosmu.ingest.pipeline import ingest_news_event_score
from cosmu.ingest.standardize import (
    EVENT_SCORE_TRANSFORM_VERSION,
    NewsEventScore,
    ScoredNewsEvent,
    _score_headline,
    score_news_events,
    scored_events_to_altdata,
)

_T0 = datetime(2024, 1, 1, tzinfo=UTC)

_BULLISH_HEADLINE = "Bitcoin surges to record on ETF approval inflows"
_BEARISH_HEADLINE = "Crypto crash: hack rekt traders in selloff dump"
_NEUTRAL_HEADLINE = "Markets hold steady as traders watch the open"


# ---------------------------------------------------------------------------
# _score_headline (deterministic offline lexicon)
# ---------------------------------------------------------------------------


def test_score_bullish_headline():
    result = _score_headline(_BULLISH_HEADLINE)
    assert isinstance(result, NewsEventScore)
    assert result.sign == 1
    assert result.magnitude > 0
    assert result.event_type == "bullish"
    assert result.confidence > 0
    assert result.transform_version == EVENT_SCORE_TRANSFORM_VERSION


def test_score_bearish_headline():
    result = _score_headline(_BEARISH_HEADLINE)
    assert result.sign == -1
    assert result.magnitude > 0
    assert result.event_type == "bearish"


def test_score_neutral_headline():
    result = _score_headline(_NEUTRAL_HEADLINE)
    assert result.sign == 0
    assert result.magnitude == 0.0
    assert result.event_type == "neutral"
    assert result.confidence == 0.0


# ---------------------------------------------------------------------------
# score_news_events
# ---------------------------------------------------------------------------


def _make_items(headlines: list[str], base: datetime = _T0) -> list[NewsItem]:
    return [
        NewsItem(ts=base + timedelta(hours=i), available_at=base + timedelta(hours=i), headline=h)
        for i, h in enumerate(headlines)
    ]


def test_score_news_events_returns_sorted_by_ts():
    items = _make_items([_NEUTRAL_HEADLINE, _BULLISH_HEADLINE, _BEARISH_HEADLINE])
    events = score_news_events(items)
    assert len(events) == 3
    for e in events:
        assert isinstance(e, ScoredNewsEvent)
    ts_list = [e.ts for e in events]
    assert ts_list == sorted(ts_list)


def test_score_news_events_content_hash_cache():
    """The same headline costs only ONE computation regardless of how many times it appears."""
    headline = _BULLISH_HEADLINE
    items = _make_items([headline, headline, headline])
    counter: dict = {}
    events = score_news_events(items, counter=counter)
    assert len(events) == 3
    assert counter.get("calls", 0) == 1  # cached after the first call


def test_scored_events_to_altdata():
    items = _make_items([_BULLISH_HEADLINE, _BEARISH_HEADLINE])
    events = score_news_events(items)
    points = scored_events_to_altdata(events)
    assert len(points) == 2
    for p, e in zip(points, events):
        assert isinstance(p, AltDataPoint)
        assert p.ts == e.ts
        assert p.available_at == e.available_at
        assert p.value == pytest.approx(e.score)


def test_scored_event_score_property():
    items = _make_items([_BULLISH_HEADLINE])
    events = score_news_events(items)
    e = events[0]
    assert e.score == pytest.approx(e.sign * e.magnitude)


# ---------------------------------------------------------------------------
# ingest_news_event_score (pipeline)
# ---------------------------------------------------------------------------


def test_ingest_news_event_score_writes_store(tmp_path):
    store = AltDataStore(tmp_path / "alt")
    news = FixtureNewsProvider({
        "BTCUSDT": _make_items([_BULLISH_HEADLINE, _BEARISH_HEADLINE, _NEUTRAL_HEADLINE]),
    })
    count = ingest_news_event_score(store, news, ["BTCUSDT"])
    assert count == 3

    # Point-in-time read: all 3 should be visible after their available_at
    points = store.read_asof("news", "BTCUSDT", "news_event_score", _T0 + timedelta(days=1))
    assert len(points) == 3
    # Bullish → positive value; bearish → negative; neutral → ~0
    values = {p.value for p in points}
    assert any(v > 0 for v in values)   # bullish headline scored positive
    assert any(v < 0 for v in values)   # bearish headline scored negative


def test_ingest_news_event_score_wrong_symbol_returns_zero(tmp_path):
    store = AltDataStore(tmp_path / "alt")
    news = FixtureNewsProvider({"BTCUSDT": _make_items([_BULLISH_HEADLINE])})
    # ETHUSDT has no fixture news → should ingest 0 points (no fabrication)
    count = ingest_news_event_score(store, news, ["ETHUSDT"])
    assert count == 0


def test_ingest_news_event_score_point_in_time(tmp_path):
    """A point scored AFTER `as_of` must NOT appear in read_asof (no look-ahead)."""
    store = AltDataStore(tmp_path / "alt")
    future_item = NewsItem(
        ts=_T0 + timedelta(days=5),
        available_at=_T0 + timedelta(days=5),
        headline=_BULLISH_HEADLINE,
    )
    news = FixtureNewsProvider({"BTCUSDT": [future_item]})
    ingest_news_event_score(store, news, ["BTCUSDT"])

    # as_of is before the event's available_at → should return empty (no look-ahead)
    points = store.read_asof("news", "BTCUSDT", "news_event_score", _T0 + timedelta(days=1))
    assert points == []


# ---------------------------------------------------------------------------
# LLM injection seam (offline mock: same contract, higher accuracy)
# ---------------------------------------------------------------------------


def test_ingest_accepts_llm_scorer():
    """The `llm` kwarg slots in an alternate scorer — the contract doesn't change."""
    def mock_llm(headline: str) -> NewsEventScore:
        # Trivially: all headlines are bullish in this mock
        return NewsEventScore(sign=1, magnitude=0.9, event_type="bullish", confidence=0.95, headline=headline)

    items = _make_items([_NEUTRAL_HEADLINE])
    counter: dict = {}
    events = score_news_events(items, llm=mock_llm, counter=counter)
    assert events[0].sign == 1
    assert events[0].magnitude == pytest.approx(0.9)
    assert counter["calls"] == 1


# ---------------------------------------------------------------------------
# Source trust scoreboard (offline, empty store)
# ---------------------------------------------------------------------------


def test_source_trust_build_empty_store(tmp_path):
    """Offline: no alt_data table → all sources show trust_score=0, status='no data'."""
    from cosmu.config.settings import Settings
    from cosmu.knowledge.store import Store
    from cosmu.mind.source_trust import build_source_trust

    # Use a temp sqlite store (no alt_data table on cold start)
    s = Settings(database_url=f"sqlite:///{tmp_path}/test.sqlite3")
    st = Store(s)
    rows = build_source_trust(st)

    # Should return rows (one per source in the registry), all with no data
    assert len(rows) > 0
    for row in rows:
        assert row.status == "no data"
        assert row.trust_score == 0.0
        assert row.gate_pass_count == 0
        assert row.last_at is None


def test_source_trust_row_fields(tmp_path):
    """SourceTrustRow fields are correctly typed and non-empty."""
    from cosmu.config.settings import Settings
    from cosmu.knowledge.store import Store
    from cosmu.mind.source_trust import build_source_trust

    s = Settings(database_url=f"sqlite:///{tmp_path}/test.sqlite3")
    st = Store(s)
    rows = build_source_trust(st)

    for row in rows:
        assert isinstance(row.source, str) and row.source
        assert isinstance(row.features, list) and len(row.features) > 0
        assert isinstance(row.summary, str) and row.summary
        assert row.tier in ("tier0", "tier1")
        assert 0.0 <= row.trust_score <= 1.0


# ---------------------------------------------------------------------------
# News intel panel (offline)
# ---------------------------------------------------------------------------


def test_news_intel_empty_store(tmp_path):
    """Offline: no alt_data → returns []."""
    from cosmu.config.settings import Settings
    from cosmu.knowledge.store import Store
    from cosmu.mind.news_intel import recent_news_events

    s = Settings(database_url=f"sqlite:///{tmp_path}/test.sqlite3")
    st = Store(s)
    events = recent_news_events(st, symbol="BTCUSDT", limit=10)

    assert events == []
