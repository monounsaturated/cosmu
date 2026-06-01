"""Free-data ingestion → append-only point-in-time store (offline, idempotent)."""

from datetime import UTC, datetime, timedelta

from cosmu.data.altdata import AltDataPoint, AltDataStore, FixtureAltDataProvider, FixtureNewsProvider, NewsItem
from cosmu.ingest.pipeline import ingest_free_sources

_T0 = datetime(2023, 1, 1, tzinfo=UTC)


def _providers():
    funding = FixtureAltDataProvider(
        {
            ("BTCUSDT", "funding_rate"): [AltDataPoint(ts=_T0 + timedelta(days=i), available_at=_T0 + timedelta(days=i), value=0.0001 * i) for i in range(5)],
        }
    )
    feargreed = FixtureAltDataProvider(
        {
            ("MARKET", "fear_greed"): [AltDataPoint(ts=_T0 + timedelta(days=i), available_at=_T0 + timedelta(days=i, hours=1), value=40.0 + i) for i in range(5)],
        }
    )
    news = FixtureNewsProvider(
        {
            "BTCUSDT": [NewsItem(ts=_T0 + timedelta(days=i), available_at=_T0 + timedelta(days=i), headline="Bitcoin surges to record on ETF inflows" if i % 2 else "markets quiet") for i in range(5)],
        }
    )
    return funding, feargreed, news


def test_ingest_writes_point_in_time_and_is_idempotent(tmp_path):
    store = AltDataStore(tmp_path / "alt")
    funding, feargreed, news = _providers()

    summary = ingest_free_sources(store, funding_provider=funding, feargreed_provider=feargreed, news_provider=news, symbols=["BTCUSDT"])
    assert summary.counts["funding_rate"] == 5
    assert summary.counts["fear_greed"] == 5
    assert summary.counts["news_sentiment"] == 5

    now = _T0 + timedelta(days=10)
    funding_now = store.read_asof("binance", "BTCUSDT", "funding_rate", now)
    news_now = store.read_asof("news", "BTCUSDT", "news_sentiment", now)
    assert len(funding_now) == 5
    assert len(news_now) == 5
    assert any(p.value > 0 for p in news_now)  # bullish headlines standardized to positive sentiment

    # Re-running the schedule appends again but the point-in-time view is unchanged (latest-wins per ts).
    ingest_free_sources(store, funding_provider=funding, feargreed_provider=feargreed, news_provider=news, symbols=["BTCUSDT"])
    assert len(store.read_asof("binance", "BTCUSDT", "funding_rate", now)) == 5


def test_fear_greed_ingested_market_wide(tmp_path):
    store = AltDataStore(tmp_path / "alt")
    funding, feargreed, news = _providers()
    ingest_free_sources(store, funding_provider=funding, feargreed_provider=feargreed, news_provider=news, symbols=["BTCUSDT"])
    # stored under the MARKET key, not per-symbol
    assert store.read_asof("alternative.me", "MARKET", "fear_greed", _T0 + timedelta(days=10))
    assert store.read_asof("alternative.me", "BTCUSDT", "fear_greed", _T0 + timedelta(days=10)) == []
