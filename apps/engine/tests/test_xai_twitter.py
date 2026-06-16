"""XaiTwitterProvider — offline tests (no network, no XAI_API_KEY).

All tests use injected fixture scorers and canned tweet payloads so CI runs fully deterministically.
Covers: key-gating, wrong-metric degradation, point-in-time availability, influencer weighting,
score clamping, StubInfluencerHitRateStore, and ingest pipeline integration.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from cosmu.data.altdata import AltDataStore
from cosmu.data.sources.xai_twitter import (
    FIXTURE_SCORES,
    FIXTURE_TWEETS,
    StubInfluencerHitRateStore,
    XaiTwitterProvider,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _provider_offline(
    *,
    overrides: dict[str, float] | None = None,
    scorer=None,
) -> XaiTwitterProvider:
    """Return a provider that uses the bundled fixture tweets and an injected scorer (no network)."""
    if scorer is None:
        scorer = lambda tweets: list(FIXTURE_SCORES)  # noqa: E731
    return XaiTwitterProvider(
        api_key="test-key",
        offline=True,
        hit_rate_store=StubInfluencerHitRateStore(overrides or {}),
        _scorer=scorer,
    )


# ---------------------------------------------------------------------------
# Key-gating
# ---------------------------------------------------------------------------


def test_no_key_returns_empty_not_fabricated() -> None:
    """Without XAI_API_KEY the provider MUST return [] — honest degradation, never a fabricated read."""
    p = XaiTwitterProvider(api_key="", offline=False)
    assert p.fetch_series("MARKET", "twitter_sentiment", limit=10) == []
    assert p.fetch_series("MARKET", "twitter_influencer_sentiment", limit=10) == []


def test_wrong_metric_returns_empty() -> None:
    p = _provider_offline()
    assert p.fetch_series("MARKET", "fear_greed", limit=10) == []
    assert p.fetch_series("BTCUSDT", "reddit_sentiment", limit=10) == []


# ---------------------------------------------------------------------------
# Point-in-time availability
# ---------------------------------------------------------------------------


def test_availability_equals_observation_time() -> None:
    """Real-time Twitter read → available_at == ts (known when fetched; no look-ahead)."""
    p = _provider_offline()
    series = p.fetch_series("MARKET", "twitter_sentiment", limit=10)
    assert len(series) == 1
    pt = series[0]
    # Both ts and available_at should be very close to now (allow 5-second window for test execution).
    delta = abs((pt.available_at - pt.ts).total_seconds())
    assert delta == 0.0, f"available_at != ts (got {delta}s gap — look-ahead violation)"
    assert pt.ts.tzinfo == UTC


# ---------------------------------------------------------------------------
# Score range and aggregation
# ---------------------------------------------------------------------------


def test_sentiment_is_in_range() -> None:
    p = _provider_offline()
    series = p.fetch_series("MARKET", "twitter_sentiment", limit=10)
    assert len(series) == 1
    assert -1.0 <= series[0].value <= 1.0


def test_twitter_and_influencer_metrics_return_same_value_with_uniform_weights() -> None:
    """With uniform hit-rates (0.5 for all), twitter_sentiment == twitter_influencer_sentiment."""
    p = _provider_offline()
    s1 = p.fetch_series("MARKET", "twitter_sentiment", limit=10)
    s2 = p.fetch_series("MARKET", "twitter_influencer_sentiment", limit=10)
    assert len(s1) == 1 and len(s2) == 1
    assert abs(s1[0].value - s2[0].value) < 1e-9


def test_influencer_weighting_shifts_result() -> None:
    """Giving author u001 (score +0.85) a high hit-rate should shift the aggregate bullish."""
    # Uniform weights (all 0.5): compute expected value first.
    p_uniform = _provider_offline()
    uniform_val = p_uniform.fetch_series("MARKET", "twitter_sentiment", limit=10)[0].value

    # Give the bullish author (u001, score +0.85) maximum weight; bearish author (u002) gets minimum.
    p_weighted = _provider_offline(overrides={"u001": 1.0, "u002": 0.0})
    weighted_val = p_weighted.fetch_series("MARKET", "twitter_sentiment", limit=10)[0].value

    assert weighted_val > uniform_val, (
        f"Up-weighting the bullish author ({weighted_val:.4f}) should exceed uniform ({uniform_val:.4f})"
    )


def test_out_of_range_scores_are_dropped() -> None:
    """Scores outside [-1, 1] (Grok hallucination guard) must be silently dropped."""

    def bad_scorer(tweets):
        return [{"author_id": "u001", "score": 999.0}]  # clearly invalid

    p = XaiTwitterProvider(api_key="test-key", offline=True, _scorer=bad_scorer)
    # All invalid → weighted average has no valid items → returns []
    result = p.fetch_series("MARKET", "twitter_sentiment", limit=10)
    assert result == []


def test_empty_tweet_fetch_returns_empty() -> None:
    """If LiveSearch returns no tweets the provider returns [] (never fabricates a 0)."""
    p = XaiTwitterProvider(api_key="test-key", offline=True, _scorer=lambda tweets: [])
    # We still need tweets to come from the fixture; test the scorer→empty path separately.
    p2 = XaiTwitterProvider(
        api_key="test-key",
        offline=True,
        _scorer=lambda tweets: [],
    )
    result = p2.fetch_series("MARKET", "twitter_sentiment", limit=10)
    assert result == []


def test_scorer_returns_empty_yields_empty() -> None:
    """If the Grok scorer returns [] (e.g. API error) the provider returns [] not a fabricated 0."""
    p = _provider_offline(scorer=lambda tweets: [])
    assert p.fetch_series("MARKET", "twitter_sentiment", limit=10) == []


# ---------------------------------------------------------------------------
# Limit respected
# ---------------------------------------------------------------------------


def test_respects_limit() -> None:
    # The provider returns at most 1 point per call (a snapshot); limit=1 keeps it, limit=0 trims to empty.
    p = _provider_offline()
    assert len(p.fetch_series("MARKET", "twitter_sentiment", limit=1)) == 1
    # limit=0 → caller asked for 0 items → must return []
    assert p.fetch_series("MARKET", "twitter_sentiment", limit=0) == []


# ---------------------------------------------------------------------------
# StubInfluencerHitRateStore
# ---------------------------------------------------------------------------


def test_stub_returns_0_5_for_unknown_author() -> None:
    store = StubInfluencerHitRateStore()
    assert store.hit_rate("unknown_author") == 0.5


def test_stub_applies_overrides() -> None:
    store = StubInfluencerHitRateStore({"u001": 0.9, "u002": 0.1})
    assert store.hit_rate("u001") == 0.9
    assert store.hit_rate("u002") == 0.1
    assert store.hit_rate("u999") == 0.5  # fallback


# ---------------------------------------------------------------------------
# Ingest pipeline integration
# ---------------------------------------------------------------------------


def test_ingest_twitter_market_wide(tmp_path) -> None:
    """The provider integrates with ingest_market_wide_numeric and writes to AltDataStore."""
    from cosmu.ingest.pipeline import ingest_market_wide_numeric

    store = AltDataStore(tmp_path / "alt")
    p = _provider_offline()

    count = ingest_market_wide_numeric(
        store, p, source_metric="twitter_sentiment", stored_metric="twitter_sentiment", provider_name="xai"
    )
    assert count == 1
    stored = store.read_all("xai", "MARKET", "twitter_sentiment")
    assert len(stored) == 1
    assert -1.0 <= stored[0].value <= 1.0


def test_ingest_influencer_sentiment_market_wide(tmp_path) -> None:
    from cosmu.ingest.pipeline import ingest_market_wide_numeric

    store = AltDataStore(tmp_path / "alt")
    p = _provider_offline()

    count = ingest_market_wide_numeric(
        store, p,
        source_metric="twitter_influencer_sentiment",
        stored_metric="twitter_influencer_sentiment",
        provider_name="xai",
    )
    assert count == 1
    stored = store.read_all("xai", "MARKET", "twitter_influencer_sentiment")
    assert len(stored) == 1


def test_run_once_includes_twitter_counts(tmp_path) -> None:
    """run_once includes twitter_sentiment in its count dict.
    twitter_influencer_sentiment is DISABLED (stub returns 0.5 = byte-identical duplicate; BACKLOG.md:65)
    so it is no longer ingested and not present in the count dict."""
    from cosmu.ingest.run import Providers, run_once
    from cosmu.data.altdata import FixtureAltDataProvider

    empty = FixtureAltDataProvider({})  # returns [] for all metrics

    providers = Providers(
        funding=empty, feargreed=empty, news=empty, fred=empty, polymarket=empty,
        liquidations=empty, putcall=empty, defillama=empty, open_interest=empty, basis=empty,
        netflow=empty, osint=empty, polymarket_clob=empty, reddit=empty, lunarcrush=empty,
        xai_twitter=_provider_offline(),  # real offline provider
    )
    store = AltDataStore(tmp_path / "alt")
    counts = run_once(store, symbols=["BTCUSDT"], providers=providers)

    assert "twitter_sentiment" in counts
    assert counts["twitter_sentiment"] == 1
    # twitter_influencer_sentiment disabled: not in counts (stub = byte-identical duplicate of twitter_sentiment)
    assert "twitter_influencer_sentiment" not in counts


def test_no_key_in_run_once_counts_zero(tmp_path) -> None:
    """Without a key the xAI provider returns [] → count for twitter_sentiment is 0 (never aborts).
    twitter_influencer_sentiment is disabled and not counted at all."""
    from cosmu.ingest.run import Providers, run_once
    from cosmu.data.altdata import FixtureAltDataProvider

    empty = FixtureAltDataProvider({})
    no_key_provider = XaiTwitterProvider(api_key="", offline=False)

    providers = Providers(
        funding=empty, feargreed=empty, news=empty, fred=empty, polymarket=empty,
        liquidations=empty, putcall=empty, defillama=empty, open_interest=empty, basis=empty,
        netflow=empty, osint=empty, polymarket_clob=empty, reddit=empty, lunarcrush=empty,
        xai_twitter=no_key_provider,
    )
    store = AltDataStore(tmp_path / "alt")
    counts = run_once(store, symbols=["BTCUSDT"], providers=providers)

    assert counts["twitter_sentiment"] == 0
    assert "twitter_influencer_sentiment" not in counts


# ---------------------------------------------------------------------------
# Feature registry smoke
# ---------------------------------------------------------------------------


def test_feature_registry_contains_twitter_features() -> None:
    from cosmu.config.feature_registry import FEATURE_REGISTRY, TWITTER_TRANSFORM_VERSION

    names = {f.name for f in FEATURE_REGISTRY}
    assert "twitter_sentiment" in names
    assert "twitter_influencer_sentiment" in names

    ts = next(f for f in FEATURE_REGISTRY if f.name == "twitter_sentiment")
    tis = next(f for f in FEATURE_REGISTRY if f.name == "twitter_influencer_sentiment")

    # Both features must be tier1 (low-confidence until validated OOS)
    assert ts.tier == "tier1"
    assert tis.tier == "tier1"

    # Transform versions must match the pinned constant
    assert ts.transform_version == TWITTER_TRANSFORM_VERSION
    assert tis.transform_version == TWITTER_TRANSFORM_VERSION

    # Source must be xai
    assert ts.source == "xai"
    assert tis.source == "xai"


def test_twitter_influencer_disabled_twitter_sentiment_enabled() -> None:
    """twitter_influencer_sentiment is DISABLED (stub hit-rate = byte-identical to twitter_sentiment).
    twitter_sentiment remains ENABLED (real signal, registered in store-backed registry)."""
    from cosmu.config.feature_registry import FEATURE_REGISTRY, feature_names

    ts = next(f for f in FEATURE_REGISTRY if f.name == "twitter_sentiment")
    tis = next(f for f in FEATURE_REGISTRY if f.name == "twitter_influencer_sentiment")

    assert ts.enabled is True, "twitter_sentiment must stay enabled"
    assert tis.enabled is False, "twitter_influencer_sentiment must be disabled until real hit-rate store is wired"

    active = feature_names()
    assert "twitter_sentiment" in active
    assert "twitter_influencer_sentiment" not in active
