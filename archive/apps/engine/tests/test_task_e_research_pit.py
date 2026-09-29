"""TASK E — research uses data + web + xAI tweets; PIT hazards closed.

Tests:
1. gather_context surfaces tweets from a seeded store (PIT-honest, $0)
2. registry.query("twitter_sentiment") returns a value instead of KeyError
3. xai_live tool is offline-testable with an injected transport
4. gtrends_search_interest is quarantined (disabled in feature_names() / feature registry)
5. twitter_influencer_sentiment is disabled (stub = byte-identical duplicate)
6. web_search query is derived from brief/symbol (not hardcoded)
7. _prior_art_from_context folds tweets into (features, citations)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from cosmu.config.settings import Settings
from cosmu.data.altdata import AltDataPoint, AltDataStore, FixtureAltDataProvider
from cosmu.knowledge.store import Store
from cosmu.lab.research import _prior_art_from_context, _read_store_tweets, _web_query_from_symbol, gather_context
from cosmu.lab.tools.research_tools import research_tool_bus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/test.sqlite3", openrouter_api_key=None))


def _seed_twitter_sentiment(tmp_path) -> Store:
    """Seed a store with 3 twitter_sentiment points so gather_context has something to read."""
    from cosmu.data.providers.store import PgAltDataStore

    store = _store(tmp_path)
    pg = PgAltDataStore(store)
    now = datetime.now(tz=UTC)
    pts = [
        AltDataPoint(ts=now - timedelta(hours=i), available_at=now - timedelta(hours=i), value=0.3 - i * 0.1)
        for i in range(3)
    ]
    pg.append("xai", "MARKET", "twitter_sentiment", pts)
    return store


# ---------------------------------------------------------------------------
# 1. gather_context surfaces tweets from a seeded store
# ---------------------------------------------------------------------------


def test_gather_context_includes_tweets_from_seeded_store(tmp_path) -> None:
    """gather_context reads already-ingested twitter_sentiment from the store (PIT-honest, $0).
    With a seeded store the tweets entry must have ok=True, source='store', and points."""
    store = _seed_twitter_sentiment(tmp_path)
    bus = research_tool_bus()
    ctx = gather_context(bus, store=store)

    tweets = ctx.get("tweets")
    assert isinstance(tweets, dict), f"gather_context should return tweets dict, got {type(tweets)}"
    assert tweets["ok"] is True
    assert tweets["source"] == "store"
    assert len(tweets["points"]) > 0
    # Values must be in the expected range
    for pt in tweets["points"]:
        assert -1.0 <= pt["value"] <= 1.0


def test_gather_context_tweets_ok_false_without_store() -> None:
    """Without a store, gather_context returns tweets={'ok': False, 'source': 'none', 'points': []}."""
    bus = research_tool_bus()
    ctx = gather_context(bus, store=None)
    tweets = ctx["tweets"]
    assert tweets["ok"] is False
    assert tweets["points"] == []


def test_read_store_tweets_seeded(tmp_path) -> None:
    """_read_store_tweets reads the last N twitter_sentiment points from the store."""
    store = _seed_twitter_sentiment(tmp_path)
    result = _read_store_tweets(store)
    assert result["ok"] is True
    assert result["source"] == "store"
    assert len(result["points"]) >= 1


def test_read_store_tweets_empty_store(tmp_path) -> None:
    """Empty store → ok=True, source='store', points=[]."""
    store = _store(tmp_path)
    result = _read_store_tweets(store)
    assert result["ok"] is True
    assert result["source"] == "store"
    assert result["points"] == []


def test_read_store_tweets_no_store() -> None:
    """None store → ok=False (offline CI path)."""
    result = _read_store_tweets(None)
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# 2. registry.query("twitter_sentiment") no longer KeyErrors
# ---------------------------------------------------------------------------


def test_registry_query_twitter_sentiment_with_fixture_provider() -> None:
    """registry.query('twitter_sentiment') must not KeyError; with an injected fixture provider
    it returns a SourceFeature (value may be None if before the fixture window — that's PIT-honest)."""
    from cosmu.data.sources.registry import SourceFeature, default_source_registry

    now = datetime.now(tz=UTC)
    pts = [AltDataPoint(ts=now - timedelta(hours=1), available_at=now - timedelta(hours=1), value=0.42)]
    alt = FixtureAltDataProvider({("MARKET", "twitter_sentiment"): pts})
    reg = default_source_registry(alt_provider=alt, include_osint=False)

    # Must not KeyError — twitter_sentiment is now registered
    names = reg.names()
    assert "twitter_sentiment" in names, f"twitter_sentiment missing from registry; got {names}"

    feat = reg.query("twitter_sentiment", "MARKET", now)
    assert isinstance(feat, SourceFeature)
    assert feat.confidence == pytest.approx(0.4, abs=0.05)
    assert feat.low_confidence is True  # confidence < 0.5
    assert feat.value == pytest.approx(0.42, abs=1e-6)


def test_registry_query_twitter_sentiment_before_data_returns_none_not_error() -> None:
    """Before any data point is available, value=None (PIT-honest, never look-ahead)."""
    from cosmu.data.sources.registry import default_source_registry

    now = datetime.now(tz=UTC)
    pts = [AltDataPoint(ts=now, available_at=now, value=0.5)]
    alt = FixtureAltDataProvider({("MARKET", "twitter_sentiment"): pts})
    reg = default_source_registry(alt_provider=alt, include_osint=False)

    # Query at a time before the data point: should return None, not raise
    past = now - timedelta(days=30)
    feat = reg.query("twitter_sentiment", "MARKET", past)
    assert feat.value is None  # nothing knowable before the point


# ---------------------------------------------------------------------------
# 3. xai_live tool: offline-testable with an injected transport
# ---------------------------------------------------------------------------


def test_xai_live_tool_registered_on_bus() -> None:
    """The xai_live tool must appear on the research bus."""
    bus = research_tool_bus()
    names = {t["name"] for t in bus.list_tools()}
    assert "xai_live" in names, f"xai_live not on bus; got {names}"


def test_xai_live_offline_no_key_returns_fixture() -> None:
    """Without an xAI key the xai_live tool degrades to the offline fixture (no network)."""
    bus = research_tool_bus()  # no xai_key → fixture path
    result = bus.call("xai_live", {"query": "BTC momentum"})
    assert result["ok"] is True
    assert result["source"] == "offline"
    assert isinstance(result["results"], list)
    assert len(result["results"]) > 0
    # Each result has title+snippet
    for r in result["results"]:
        assert "title" in r
        assert "snippet" in r


def test_xai_live_injected_transport_offline() -> None:
    """xai_live with an injected key that returns a canned response (no real network call)."""
    from unittest.mock import patch
    from cosmu.lab.tools import research_tools as rt

    canned_resp = {
        "choices": [{
            "message": {
                "content": '[{"title": "Mock XAI result", "snippet": "Mocked.", "url": "https://x.ai"}]'
            }
        }]
    }

    with patch.object(rt, "_http_post_json", return_value=canned_resp):
        bus = research_tool_bus(xai_key="fake-key")
        result = bus.call("xai_live", {"query": "ETH swing edge"})

    assert result["ok"] is True
    assert result["source"] == "xai_live"
    assert result["results"][0]["title"] == "Mock XAI result"


def test_xai_live_is_readonly_on_bus() -> None:
    """xai_live must be registered as readonly so execution can never reach the bus.
    The bus rejects non-readonly tools at registration time; since xai_live was successfully registered
    (it appears in list_tools()), it must be readonly by the ToolBus invariant."""
    bus = research_tool_bus()
    names = {t["name"] for t in bus.list_tools()}
    # xai_live is registered → it passed the ToolBus readonly check (the bus raises on non-readonly)
    assert "xai_live" in names
    # The ToolBus guard (registry.py:23) rejects readonly=False; registering with readonly=True is what
    # makes it reach list_tools(). Attempting to register a non-readonly tool must still raise.
    from cosmu.lab.tools.registry import ToolDefinition
    with pytest.raises(ValueError):
        bus.register(ToolDefinition(name="xai_execute", intent="x", readonly=False, handler=lambda p: {}))


# ---------------------------------------------------------------------------
# 4. gtrends_search_interest quarantined (disabled in feature_names)
# ---------------------------------------------------------------------------


def test_gtrends_quarantined_not_in_feature_names() -> None:
    """gtrends_search_interest is quarantined (revision_safety hazard: rescales history = look-ahead).
    It must NOT appear in feature_names() so the Gate cannot use it in backtests."""
    from cosmu.config.feature_registry import FEATURE_REGISTRY, feature_names

    # Still present in the registry (for audit trail / potential re-enable)
    all_names = {f.name for f in FEATURE_REGISTRY}
    assert "gtrends_search_interest" in all_names, "definition must still exist (do not delete, just disable)"

    # But DISABLED so the Gate cannot reference it
    active = feature_names()
    assert "gtrends_search_interest" not in active, (
        "gtrends_search_interest is QUARANTINED (revision_safety hazard) and must not be in feature_names()"
    )

    gtrends = next(f for f in FEATURE_REGISTRY if f.name == "gtrends_search_interest")
    assert gtrends.enabled is False, "gtrends_search_interest must have enabled=False in the registry"


# ---------------------------------------------------------------------------
# 5. twitter_influencer_sentiment disabled (stub = byte-identical duplicate)
# ---------------------------------------------------------------------------


def test_twitter_influencer_disabled_not_in_feature_names() -> None:
    """twitter_influencer_sentiment is disabled until the real InfluencerHitRateStore is wired.
    Must NOT appear in feature_names() (no gate N inflation from a byte-identical duplicate)."""
    from cosmu.config.feature_registry import FEATURE_REGISTRY, feature_names

    all_names = {f.name for f in FEATURE_REGISTRY}
    assert "twitter_influencer_sentiment" in all_names, "definition must still exist for future re-enable"

    active = feature_names()
    assert "twitter_influencer_sentiment" not in active, (
        "twitter_influencer_sentiment must be disabled until real hit-rate store is wired (BACKLOG.md:65)"
    )

    tis = next(f for f in FEATURE_REGISTRY if f.name == "twitter_influencer_sentiment")
    assert tis.enabled is False


# ---------------------------------------------------------------------------
# 6. web_search query derived from symbol/brief
# ---------------------------------------------------------------------------


def test_web_query_from_symbol_uses_coin_not_hardcoded() -> None:
    """The web search query must be derived from symbol, not the old hardcoded 'crypto swing strategy edge'."""
    q_btc = _web_query_from_symbol("BTCUSDT")
    assert "BTC" in q_btc, f"expected BTC in query, got {q_btc!r}"
    assert "crypto swing strategy edge" not in q_btc, "hardcoded query must not appear"

    q_eth = _web_query_from_symbol("ETHUSDT")
    assert "ETH" in q_eth

    # With a brief, the brief content appears in the query
    q_brief = _web_query_from_symbol("BTCUSDT", brief="Fade oversold RSI on crypto swing horizon")
    assert "BTC" in q_brief
    assert "Fade" in q_brief or "oversold" in q_brief.lower() or "RSI" in q_brief


def test_gather_context_web_search_not_hardcoded(tmp_path) -> None:
    """gather_context must call web_search with a derived query, not the old hardcoded string."""
    bus = research_tool_bus()
    ctx = gather_context(bus, symbol="ETHUSDT", store=None)
    ws = ctx.get("web_search", {})
    if isinstance(ws, dict) and ws.get("query"):
        assert ws["query"] != "crypto swing strategy edge", (
            "web_search query must be derived from symbol, not the old hardcoded string"
        )
        assert "ETH" in ws["query"] or "eth" in ws["query"].lower()


# ---------------------------------------------------------------------------
# 7. _prior_art_from_context folds tweets into (features, citations)
# ---------------------------------------------------------------------------


def test_prior_art_folds_tweets_bullish(tmp_path) -> None:
    """When tweets with positive sentiment are present, twitter_sentiment appears in prior_art features
    and a 'store-tweets: ...' citation is added."""
    ctx = {
        "rag_read": {"matches": []},
        "web_search": {"results": []},
        "xai_live": {"results": []},
        "tweets": {"ok": True, "source": "store", "points": [{"value": 0.45, "ts": "2024-01-01T00:00:00+00:00"}]},
    }
    feats, cites = _prior_art_from_context(ctx)
    assert "twitter_sentiment" in feats
    assert any("store-tweets" in c for c in cites), f"store-tweets citation missing from {cites}"
    assert any("bullish" in c for c in cites), f"expected 'bullish' direction in citations: {cites}"


def test_prior_art_folds_tweets_bearish() -> None:
    ctx = {
        "rag_read": {"matches": []},
        "web_search": {"results": []},
        "xai_live": {"results": []},
        "tweets": {"ok": True, "source": "store", "points": [{"value": -0.55, "ts": "2024-01-01T00:00:00+00:00"}]},
    }
    feats, cites = _prior_art_from_context(ctx)
    assert "twitter_sentiment" in feats
    assert any("bearish" in c for c in cites), f"expected 'bearish' direction: {cites}"


def test_prior_art_no_tweets_does_not_add_feature() -> None:
    """When tweets are empty, twitter_sentiment must NOT be added to prior_art features."""
    ctx = {
        "rag_read": {"matches": []},
        "web_search": {"results": []},
        "xai_live": {"results": []},
        "tweets": {"ok": True, "source": "store", "points": []},
    }
    feats, cites = _prior_art_from_context(ctx)
    assert "twitter_sentiment" not in feats
    assert not any("store-tweets" in c for c in cites)


def test_prior_art_folds_xai_live_results() -> None:
    """xai_live results must be folded into citations."""
    ctx = {
        "rag_read": {"matches": []},
        "web_search": {"results": []},
        "xai_live": {"results": [{"title": "XAI live: BTC signal", "snippet": "...", "url": ""}]},
        "tweets": {"ok": False, "source": "none", "points": []},
    }
    feats, cites = _prior_art_from_context(ctx)
    assert any("xai-live" in c for c in cites), f"expected xai-live citation in {cites}"
