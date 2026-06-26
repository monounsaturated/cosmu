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

    # Re-running the schedule writes NOTHING new — not just an unchanged point-in-time view, but zero
    # duplicate rows in the underlying store. The 15-min cron re-pulls a full provider window every pass;
    # without (ts, available_at) dedup the store gained a full duplicate copy per pass (unbounded growth,
    # and the [-limit:] read slice covered ever-less DISTINCT history).
    ingest_free_sources(store, funding_provider=funding, feargreed_provider=feargreed, news_provider=news, symbols=["BTCUSDT"])
    assert len(store.read_asof("binance", "BTCUSDT", "funding_rate", now)) == 5
    assert len(store.read_all("binance", "BTCUSDT", "funding_rate")) == 5, "re-run must append 0 duplicate rows"
    assert len(store.read_all("news", "BTCUSDT", "news_sentiment")) == 5
    assert len(store.read_all("alternative.me", "MARKET", "fear_greed")) == 5


def test_reingest_keeps_vendor_revisions(tmp_path):
    """Dedup must NOT swallow a genuine revision: the same `ts` re-served with a LATER `available_at` is new
    point-in-time information (an ALFRED-style vintage) and must land as an extra row."""
    store = AltDataStore(tmp_path / "alt")
    original = [AltDataPoint(ts=_T0, available_at=_T0 + timedelta(hours=1), value=1.0)]
    revised = original + [AltDataPoint(ts=_T0, available_at=_T0 + timedelta(days=2), value=1.5)]

    from cosmu.ingest.pipeline import ingest_numeric

    ingest_numeric(store, FixtureAltDataProvider({("MARKET", "macro_regime"): original}), ["MARKET"], "macro_regime", provider_name="fred")
    ingest_numeric(store, FixtureAltDataProvider({("MARKET", "macro_regime"): revised}), ["MARKET"], "macro_regime", provider_name="fred")
    rows = store.read_all("fred", "MARKET", "macro_regime")
    assert len(rows) == 2, "the revision (same ts, later available_at) must be kept"
    # The point-in-time view honors the revision timeline: before the revision lands, the first value rules.
    assert store.read_asof("fred", "MARKET", "macro_regime", _T0 + timedelta(days=1))[0].value == 1.0
    assert store.read_asof("fred", "MARKET", "macro_regime", _T0 + timedelta(days=3))[0].value == 1.5


def test_fetch_series_counts_distinct_history_despite_duplicates(tmp_path):
    """A store that already accreted duplicate copies of a window (the pre-dedup scheduled ingest) must not
    shrink the history the gate sees: fetch_series collapses exact (ts, available_at) duplicates BEFORE the
    trailing [-limit:] slice, so `limit` counts DISTINCT points."""
    from cosmu.data.providers.store import StoreBackedAltProvider

    store = AltDataStore(tmp_path / "alt")
    window = [AltDataPoint(ts=_T0 + timedelta(days=i), available_at=_T0 + timedelta(days=i), value=float(i)) for i in range(10)]
    for _ in range(3):  # three cron passes of the same window, pre-dedup style
        store.append("binance", "BTCUSDT", "funding_rate", window)

    provider = StoreBackedAltProvider(store)
    got = provider.fetch_series("BTCUSDT", "funding_rate", limit=10)
    assert len(got) == 10
    assert [p.value for p in got] == [float(i) for i in range(10)], "limit must cover the DISTINCT window, not 10 duplicate rows"


def test_run_once_accepts_knowledge_store(tmp_path):
    # The master tick hands run_once a knowledge Store (not an AltDataStore). It must wrap it as the DB-backed
    # alt-data store and actually persist — the regression was every source raising
    # "'Store' object has no attribute 'append'", swallowed as a 0 count so the deployed tick silently ingested
    # nothing. Offline: fixture providers (funding has data, the rest return [] for unknown metrics).
    from cosmu.config.settings import Settings
    from cosmu.ingest.run import Providers, run_once
    from cosmu.knowledge.store import Store

    funding, feargreed, news = _providers()
    store = Store(Settings(database_url=f"sqlite:///{tmp_path}/k.sqlite3", openrouter_api_key=None))
    providers = Providers(
        funding=funding, feargreed=feargreed, news=news, fred=funding, polymarket=funding,
        putcall=funding, defillama=funding, open_interest=funding, basis=funding,
        netflow=funding, osint=funding, polymarket_clob=funding, reddit=funding, lunarcrush=funding,
    )
    counts = run_once(store, symbols=["BTCUSDT"], providers=providers)
    assert counts["funding_rate"] == 5  # appended through the wrapped knowledge store (was 0 before the fix)
    # the points actually landed in the store's alt_data table (sqlite-compatible read; prod uses Postgres)
    n = store.rows("SELECT COUNT(*) AS n FROM alt_data WHERE provider = ? AND metric = ?", ("binance", "funding_rate"))[0]["n"]
    assert n == 5


def test_fear_greed_ingested_market_wide(tmp_path):
    store = AltDataStore(tmp_path / "alt")
    funding, feargreed, news = _providers()
    ingest_free_sources(store, funding_provider=funding, feargreed_provider=feargreed, news_provider=news, symbols=["BTCUSDT"])
    # stored under the MARKET key, not per-symbol
    assert store.read_asof("alternative.me", "MARKET", "fear_greed", _T0 + timedelta(days=10))
    assert store.read_asof("alternative.me", "BTCUSDT", "fear_greed", _T0 + timedelta(days=10)) == []
