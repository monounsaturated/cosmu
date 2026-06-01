# Ingest test for the NEW real free sources (Coinglass liquidations, CBOE put/call, GDELT-shaped news).
# Offline via injected fixture providers: assert they land in the append-only point-in-time store and that
# re-running a scheduled pass is idempotent-in-view (the point-in-time read is unchanged).

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cosmu.data.altdata import AltDataPoint, AltDataStore, FixtureAltDataProvider, FixtureNewsProvider, NewsItem
from cosmu.ingest.pipeline import ingest_extra_free_sources

_T0 = datetime(2023, 1, 1, tzinfo=UTC)
_FAR = datetime(2099, 1, 1, tzinfo=UTC)


def _providers():
    liquidations = FixtureAltDataProvider(
        {("BTCUSDT", "liquidations"): [AltDataPoint(ts=_T0 + timedelta(days=i), available_at=_T0 + timedelta(days=i + 1), value=1_000_000.0 * (i + 1)) for i in range(5)]}
    )
    putcall = FixtureAltDataProvider(
        {("MARKET", "putcall_ratio"): [AltDataPoint(ts=_T0 + timedelta(days=i), available_at=_T0 + timedelta(days=i + 1), value=0.9 + 0.01 * i) for i in range(5)]}
    )
    news = FixtureNewsProvider(
        {"BTCUSDT": [NewsItem(ts=_T0 + timedelta(days=i), available_at=_T0 + timedelta(days=i), headline="Bitcoin surges to record on ETF inflows" if i % 2 else "Exchange hack triggers selloff") for i in range(5)]}
    )
    return liquidations, putcall, news


def test_extra_free_sources_land_in_store_point_in_time(tmp_path):
    store = AltDataStore(tmp_path / "alt")
    liquidations, putcall, news = _providers()

    summary = ingest_extra_free_sources(store, liquidation_provider=liquidations, putcall_provider=putcall, news_provider=news, symbols=["BTCUSDT"])
    assert summary.counts["liquidations"] == 5
    assert summary.counts["putcall_ratio"] == 5
    assert summary.counts["news_sentiment"] == 5

    # liquidations stored per-symbol under the coinglass provider
    liq_now = store.read_asof("coinglass", "BTCUSDT", "liquidations", _FAR)
    assert len(liq_now) == 5
    assert all(p.available_at > p.ts for p in liq_now)  # next-bucket availability floor preserved

    # put/call stored market-wide under the cboe provider at the MARKET key (not per symbol)
    assert store.read_asof("cboe", "MARKET", "putcall_ratio", _FAR)
    assert store.read_asof("cboe", "BTCUSDT", "putcall_ratio", _FAR) == []

    # news standardized to a numeric sentiment series (LLM seam runs once at ingest, here offline)
    news_now = store.read_asof("news", "BTCUSDT", "news_sentiment", _FAR)
    assert len(news_now) == 5
    assert any(p.value > 0 for p in news_now)  # bullish headlines → positive sentiment
    assert any(p.value < 0 for p in news_now)  # bearish headlines → negative sentiment


def test_extra_free_sources_reingest_is_idempotent_in_view(tmp_path):
    store = AltDataStore(tmp_path / "alt")
    liquidations, putcall, news = _providers()
    ingest_extra_free_sources(store, liquidation_provider=liquidations, putcall_provider=putcall, news_provider=news, symbols=["BTCUSDT"])
    before = store.read_asof("cboe", "MARKET", "putcall_ratio", _FAR)
    # re-run a scheduled pass — append-only, but the point-in-time VIEW (latest-revision-per-ts) is unchanged
    ingest_extra_free_sources(store, liquidation_provider=liquidations, putcall_provider=putcall, news_provider=news, symbols=["BTCUSDT"])
    after = store.read_asof("cboe", "MARKET", "putcall_ratio", _FAR)
    assert [(p.ts, p.value) for p in before] == [(p.ts, p.value) for p in after]
    assert len(store.read_asof("coinglass", "BTCUSDT", "liquidations", _FAR)) == 5
