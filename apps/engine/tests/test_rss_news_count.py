"""Offline tests for the RSS headline COUNT source (rss_news.py).

Invariants:
- All offline — no network calls.  HTTP is either mocked or the fixture XML is used.
- PIT: available_at == pubDate of each item; the query window is (as_of - window, as_of].
- No look-ahead: items with pubDate > as_of are EXCLUDED from the count.
- No fabrication: a gap (zero matching items) → value=None, not 0.0.
- No LLM: pure count logic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cosmu.data.sources.rss_news import (
    TRANSFORM_VERSION,
    RssNewsCountSource,
    _count_items_in_window,
    _parse_pubdate,
    _parse_rss_items_with_titles,
    _topic_counts,
)
from cosmu.data.sources.registry import SourceFeature

# ── fixture reference timestamps ──────────────────────────────────────────────
# The bundled _FIXTURE_XML contains 3 items on 2024-06-01 and 1 old item on 2024-05-27.

_AS_OF_IN_WINDOW = datetime(2024, 6, 1, 20, 0, 0, tzinfo=UTC)   # all 3 items visible
_AS_OF_NO_ITEMS  = datetime(2024, 5, 26, 0, 0, 0, tzinfo=UTC)   # before everything
_AS_OF_FUTURE    = datetime(2024, 6, 2, 0, 0, 0, tzinfo=UTC)    # items still visible (<=24h window)


# ── unit: RSS pubDate parsing ─────────────────────────────────────────────────

def test_parse_pubdate_valid():
    dt = _parse_pubdate("Sat, 01 Jun 2024 10:00:00 +0000")
    assert dt is not None
    assert dt.year == 2024 and dt.month == 6 and dt.day == 1
    assert dt.tzinfo is not None

def test_parse_pubdate_invalid_returns_none():
    assert _parse_pubdate("not a date") is None
    assert _parse_pubdate("") is None


# ── unit: XML parsing ─────────────────────────────────────────────────────────

def test_parse_items_with_titles_fixture():
    """The fixture XML contains 4 items; all should parse with titles."""
    from cosmu.data.sources.rss_news import _FIXTURE_XML
    pairs = _parse_rss_items_with_titles(_FIXTURE_XML)
    assert len(pairs) == 4
    dates = [t for t, _ in pairs]
    titles = [title for _, title in pairs]
    # All timestamps are UTC-aware
    assert all(t.tzinfo is not None for t in dates)
    # Old article is present in raw parse but NOT in the window count
    assert any("Old news" in title for title in titles)

def test_parse_items_empty_xml():
    """Invalid or empty XML returns an empty list — not a crash."""
    assert _parse_rss_items_with_titles("") == []
    assert _parse_rss_items_with_titles("not xml") == []


# ── unit: window counting (PIT) ───────────────────────────────────────────────

def test_count_no_lookahead():
    """Items with pubDate > as_of are excluded (no look-ahead)."""
    future = _AS_OF_IN_WINDOW + timedelta(hours=3)
    # make one item just 1 second in the future
    pub_times = [_AS_OF_IN_WINDOW + timedelta(seconds=1)]
    assert _count_items_in_window(pub_times, _AS_OF_IN_WINDOW, 86_400) == 0

def test_count_pit_inclusive_boundary():
    """An item with pubDate == as_of IS included (the boundary is inclusive on the right)."""
    pub_times = [_AS_OF_IN_WINDOW]
    assert _count_items_in_window(pub_times, _AS_OF_IN_WINDOW, 86_400) == 1

def test_count_window_excludes_old_items():
    """Items older than the window are not counted."""
    old = _AS_OF_IN_WINDOW - timedelta(days=2)
    recent = _AS_OF_IN_WINDOW - timedelta(hours=1)
    assert _count_items_in_window([old, recent], _AS_OF_IN_WINDOW, 86_400) == 1

def test_count_empty_returns_zero():
    assert _count_items_in_window([], _AS_OF_IN_WINDOW, 86_400) == 0


# ── unit: topic counting ──────────────────────────────────────────────────────

def test_topic_counts_keywords():
    """Topic counts match keyword presence in titles, within the window."""
    pairs = [
        (_AS_OF_IN_WINDOW - timedelta(hours=2), "Bitcoin hits new high after SEC ruling"),
        (_AS_OF_IN_WINDOW - timedelta(hours=1), "Fed holds rates; inflation cools"),
        # outside window
        (_AS_OF_IN_WINDOW - timedelta(days=2), "Ethereum upgrade complete"),
    ]
    topics = {
        "crypto_market": ["bitcoin", "ethereum", "crypto"],
        "macro_risk": ["inflation", "fed", "rate"],
    }
    counts = _topic_counts(pairs, topics, _AS_OF_IN_WINDOW, 86_400)
    assert counts["crypto_market"] == 1   # only "Bitcoin" article within window
    assert counts["macro_risk"] == 1      # only "Fed holds rates" within window

def test_topic_counts_no_lookahead():
    """Items with pubDate > as_of are excluded from topic counts."""
    pairs = [
        (_AS_OF_IN_WINDOW + timedelta(hours=1), "Bitcoin surges tomorrow"),  # future
        (_AS_OF_IN_WINDOW - timedelta(hours=1), "Bitcoin dip today"),
    ]
    topics = {"crypto_market": ["bitcoin"]}
    counts = _topic_counts(pairs, topics, _AS_OF_IN_WINDOW, 86_400)
    assert counts["crypto_market"] == 1  # only the past item


# ── integration: RssNewsCountSource (offline fixture) ─────────────────────────

def test_rss_source_query_counts_items_in_window():
    """query() returns a positive float count for items within the window."""
    src = RssNewsCountSource(offline=True)
    f = src.query("MARKET", _AS_OF_IN_WINDOW)
    assert isinstance(f, SourceFeature)
    # Fixture has 3 items on 2024-06-01 within 24h of 20:00 UTC; old item is out of window
    assert f.value == 3.0

def test_rss_source_query_no_items_returns_none():
    """A gap (no items in window) → value=None, NOT 0.0 (no fabrication)."""
    src = RssNewsCountSource(offline=True)
    f = src.query("MARKET", _AS_OF_NO_ITEMS)
    assert f.value is None
    assert f.available_at is None

def test_rss_source_no_lookahead():
    """Items with pubDate > as_of are excluded from the count."""
    src = RssNewsCountSource(offline=True)
    # Query at 09:59 UTC — only items before that time count (fixture first item is at 10:00)
    as_of = datetime(2024, 6, 1, 9, 59, 0, tzinfo=UTC)
    f = src.query("MARKET", as_of)
    # Nothing published yet at 09:59 on 2024-06-01 (first item is 10:00:00)
    assert f.value is None

def test_rss_source_available_at_equals_as_of():
    """available_at == as_of when items are present (count is knowable at fetch time)."""
    src = RssNewsCountSource(offline=True)
    as_of = _AS_OF_IN_WINDOW
    f = src.query("MARKET", as_of)
    assert f.available_at == as_of

def test_rss_source_low_confidence():
    """The source declares low_confidence — must earn its place via OOS."""
    src = RssNewsCountSource(offline=True)
    assert src.low_confidence is True
    assert src.confidence < 0.5

def test_rss_source_transform_version_pinned():
    """transform_version is set so gate-passed survivors are byte-for-byte re-runnable."""
    src = RssNewsCountSource(offline=True)
    f = src.query("MARKET", _AS_OF_IN_WINDOW)
    assert f.transform_version == TRANSFORM_VERSION
    assert TRANSFORM_VERSION  # non-empty

def test_rss_source_metadata_fields():
    """SourceFeature carries the right name, scope, and confidence."""
    src = RssNewsCountSource(offline=True)
    f = src.query("BTCUSDT", _AS_OF_IN_WINDOW)
    assert f.name == "rss_news_count"
    assert f.scope == "BTCUSDT"
    assert f.confidence == src.confidence

def test_rss_source_kind_and_metric():
    """Source exposes kind='sentiment' and metric='rss_news_count' for registry wiring."""
    src = RssNewsCountSource(offline=True)
    assert src.kind == "sentiment"
    assert src.metric == "rss_news_count"


# ── integration: query_topics ─────────────────────────────────────────────────

def test_query_topics_returns_per_topic_features():
    """query_topics() returns one SourceFeature per configured topic."""
    src = RssNewsCountSource(offline=True)
    topics_out = src.query_topics("MARKET", _AS_OF_IN_WINDOW)
    # Default topics: crypto_market, regulation, macro_risk
    assert "crypto_market" in topics_out
    assert "regulation" in topics_out
    assert "macro_risk" in topics_out
    for topic, feat in topics_out.items():
        assert isinstance(feat, SourceFeature)
        # Names are prefixed with the source name
        assert feat.name == f"rss_news_count_{topic}"

def test_query_topics_fixture_counts():
    """Verify fixture topic counts against known fixture content:
    - 'Bitcoin rallies as SEC issues new crypto ruling' → crypto_market + regulation
    - 'Ethereum ETF approval boosts market sentiment' → crypto_market
    - 'Fed holds rates steady; crypto unaffected' → crypto_market + macro_risk
    """
    src = RssNewsCountSource(offline=True)
    topics_out = src.query_topics("MARKET", _AS_OF_IN_WINDOW)
    # crypto_market: all three in-window items match (bitcoin/sec/ethereum/eth/crypto)
    assert topics_out["crypto_market"].value is not None
    assert topics_out["crypto_market"].value >= 1.0
    # regulation: the SEC headline
    assert topics_out["regulation"].value is not None
    assert topics_out["regulation"].value >= 1.0

def test_query_topics_no_match_returns_none():
    """A topic with no matching headlines → value=None (no fabrication)."""
    src = RssNewsCountSource(
        offline=True,
        topics={"nonexistent_topic": ["xyzzy_no_such_keyword_ever_012345"]},
    )
    topics_out = src.query_topics("MARKET", _AS_OF_IN_WINDOW)
    assert topics_out["nonexistent_topic"].value is None

def test_query_topics_no_lookahead():
    """Topics exclude future items (pubDate > as_of)."""
    src = RssNewsCountSource(offline=True)
    # Query before the first fixture item (10:00 UTC)
    as_of = datetime(2024, 6, 1, 9, 59, 0, tzinfo=UTC)
    topics_out = src.query_topics("MARKET", as_of)
    for feat in topics_out.values():
        assert feat.value is None


# ── integration: injected fetcher (mocked HTTP, no network) ───────────────────

def test_injected_fetcher_no_network():
    """The source works with a fully injected fetcher — zero network calls."""
    call_log: list[str] = []

    minimal_xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Crypto regulatory clarity ahead</title>
      <pubDate>Sun, 02 Jun 2024 08:00:00 +0000</pubDate>
      <link>https://example.com/a</link>
    </item>
  </channel>
</rss>
"""

    def mock_fetcher(url: str) -> str:
        call_log.append(url)
        return minimal_xml

    src = RssNewsCountSource(
        feeds={"MARKET": ["https://fake.example.com/feed"]},
        _fetcher=mock_fetcher,
    )
    as_of = datetime(2024, 6, 2, 9, 0, 0, tzinfo=UTC)
    f = src.query("MARKET", as_of)

    assert len(call_log) == 1
    assert "fake.example.com" in call_log[0]
    assert f.value == 1.0   # one item in window

def test_injected_fetcher_returns_empty_xml():
    """An empty/broken feed → value=None (gap, not crash)."""
    src = RssNewsCountSource(
        feeds={"MARKET": ["https://broken.example.com/feed"]},
        _fetcher=lambda _url: "",
    )
    f = src.query("MARKET", _AS_OF_IN_WINDOW)
    assert f.value is None


# ── integration: DataSource protocol compliance ───────────────────────────────

def test_rss_source_satisfies_datasource_protocol():
    """RssNewsCountSource satisfies the DataSource protocol (registry-safe)."""
    from cosmu.data.sources.registry import DataSource

    src = RssNewsCountSource(offline=True)
    assert isinstance(src, DataSource)

def test_rss_source_registers_in_registry():
    """The source can be registered in a DataSourceRegistry without errors."""
    from cosmu.data.sources.registry import DataSourceRegistry

    reg = DataSourceRegistry()
    src = RssNewsCountSource(offline=True)
    reg.register(src)
    assert "rss_news_count" in reg.names()
    catalog = reg.discover()
    by_name = {c["name"]: c for c in catalog}
    assert by_name["rss_news_count"]["kind"] == "sentiment"
    assert by_name["rss_news_count"]["low_confidence"] is True
