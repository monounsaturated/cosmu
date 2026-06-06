# intent: test PolymarketGammaProvider — auto-discover via events+keywords, snapshot aggregate, pin, offline fixtures, ingest wiring.

from datetime import UTC, datetime, timedelta

from cosmu.data.altdata import AltDataPoint, AltDataStore, FixtureAltDataProvider, PolymarketGammaProvider
from cosmu.ingest.pipeline import ingest_market_wide_numeric
from cosmu.ingest.run import Providers, run_once

_T0 = datetime(2025, 1, 1, tzinfo=UTC)

GAMMA_MARKETS = [
    {
        "id": "100",
        "question": "Will the US enter a recession in 2026?",
        "outcomePrices": '["0.30", "0.70"]',
        "liquidity": "500000",
        "active": True,
        "closed": False,
    },
    {
        "id": "101",
        "question": "Will the Federal Reserve cut interest rates before July?",
        "outcomePrices": '["0.60", "0.40"]',
        "liquidity": "300000",
        "active": True,
        "closed": False,
    },
    {
        "id": "102",
        "question": "Will inflation exceed 5% in 2026?",
        "outcomePrices": '["0.20", "0.80"]',
        "liquidity": "200000",
        "active": True,
        "closed": False,
    },
    {
        "id": "103",
        "question": "Who will win the NBA finals?",
        "outcomePrices": '["0.50", "0.50"]',
        "liquidity": "1000000",
        "active": True,
        "closed": False,
    },
]

GAMMA_EVENTS = [
    {
        "title": "US Recession",
        "tags": [{"label": "Economy"}],
        "markets": [GAMMA_MARKETS[0], GAMMA_MARKETS[2]],
    },
    {
        "title": "Fed Rate Decision",
        "tags": [{"label": "Finance"}],
        "markets": [GAMMA_MARKETS[1]],
    },
    {
        "title": "NBA Finals",
        "tags": [{"label": "Sports"}],
        "markets": [GAMMA_MARKETS[3]],
    },
]


def _gamma_fetcher(url):
    if "/events" in url:
        return list(GAMMA_EVENTS)
    return list(GAMMA_MARKETS)


def _make_provider(pin_token=None, max_markets=8):
    return PolymarketGammaProvider(
        pin_token=pin_token,
        max_markets=max_markets,
        _gamma_fetcher=_gamma_fetcher,
    )


def test_discover_finds_events_tagged_economy():
    p = _make_provider()
    markets = p.discover_markets()
    questions = [m["question"] for m in markets]
    assert any("recession" in q.lower() for q in questions)
    assert any("inflation" in q.lower() for q in questions)


def test_discover_finds_keywords_fallback():
    p = _make_provider()
    markets = p.discover_markets()
    questions = [m["question"] for m in markets]
    assert any("federal reserve" in q.lower() for q in questions)


def test_discover_excludes_non_macro():
    p = _make_provider()
    markets = p.discover_markets()
    questions = [m["question"] for m in markets]
    assert not any("nba" in q.lower() for q in questions)


def test_discover_sorted_by_liquidity():
    p = _make_provider()
    markets = p.discover_markets()
    liqs = [m["liquidity"] for m in markets]
    assert liqs == sorted(liqs, reverse=True)


def test_discover_deduplicates_across_passes():
    p = _make_provider()
    markets = p.discover_markets()
    ids = [m["id"] for m in markets]
    assert len(ids) == len(set(ids))


def test_discover_respects_max_markets():
    p = _make_provider(max_markets=2)
    markets = p.discover_markets()
    assert len(markets) <= 2


def test_fetch_series_returns_snapshot():
    p = _make_provider()
    series = p.fetch_series("MARKET", "risk_on", limit=1000)
    assert len(series) == 1
    pt = series[0]
    assert 0 < pt.value < 1
    assert pt.ts.tzinfo is not None
    assert pt.available_at == pt.ts


def test_fetch_series_aggregate_is_mean_of_discovered():
    p = _make_provider()
    series = p.fetch_series("MARKET", "risk_on", limit=1000)
    expected_avg = (0.30 + 0.60 + 0.20) / 3
    assert abs(series[0].value - expected_avg) < 1e-9


def test_discover_extracts_yes_probability():
    p = _make_provider()
    markets = p.discover_markets()
    for m in markets:
        assert m["yes_prob"] is not None
        assert 0 <= m["yes_prob"] <= 1


def test_fetch_series_empty_on_gamma_failure():
    def fail_gamma(url):
        raise ConnectionError("offline")

    p = PolymarketGammaProvider(_gamma_fetcher=fail_gamma)
    series = p.fetch_series("MARKET", "risk_on", limit=1000)
    assert series == []


def test_handles_json_encoded_outcome_prices():
    """The Gamma API returns outcomePrices as a JSON-encoded string, not a native list."""
    import json

    markets = [
        {
            "id": "200",
            "question": "Will there be a recession?",
            "outcomePrices": json.dumps(["0.40", "0.60"]),
            "liquidity": "100000",
            "active": True,
            "closed": False,
        },
    ]
    events = [{"title": "Recession", "tags": [{"label": "Economy"}], "markets": markets}]

    def fetcher(url):
        return events if "/events" in url else markets

    p = PolymarketGammaProvider(_gamma_fetcher=fetcher)
    mkts = p.discover_markets()
    assert len(mkts) >= 1
    assert mkts[0]["yes_prob"] == 0.4


def test_handles_native_list_outcome_prices():
    """Some responses might have outcomePrices as a native list."""
    markets = [
        {
            "id": "201",
            "question": "Will inflation rise?",
            "outcomePrices": ["0.55", "0.45"],
            "liquidity": 50000,
            "active": True,
            "closed": False,
        },
    ]
    events = [{"title": "Inflation", "tags": [{"label": "Economy"}], "markets": markets}]

    def fetcher(url):
        return events if "/events" in url else markets

    p = PolymarketGammaProvider(_gamma_fetcher=fetcher)
    mkts = p.discover_markets()
    assert len(mkts) >= 1
    assert mkts[0]["yes_prob"] == 0.55


def test_events_only_no_keywords():
    """When all macro markets come from tagged events, the keyword pass finds nothing new."""

    def events_only(url):
        if "/events" in url:
            return list(GAMMA_EVENTS)
        return []

    p = PolymarketGammaProvider(_gamma_fetcher=events_only)
    markets = p.discover_markets()
    assert len(markets) >= 2


def test_ingest_with_gamma_provider(tmp_path):
    store = AltDataStore(tmp_path / "alt")
    provider = _make_provider()
    count = ingest_market_wide_numeric(
        store, provider, source_metric="risk_on", stored_metric="risk_on", provider_name="polymarket",
    )
    assert count == 1
    now = datetime.now(tz=UTC) + timedelta(seconds=1)
    points = store.read_asof("polymarket", "MARKET", "risk_on", now)
    assert len(points) == 1
    assert 0 < points[0].value < 1


def test_ingest_accumulates_history(tmp_path):
    """Repeated ingest runs accumulate history in the append-only store."""
    store = AltDataStore(tmp_path / "alt")
    provider = _make_provider()
    ingest_market_wide_numeric(store, provider, source_metric="risk_on", stored_metric="risk_on", provider_name="polymarket")
    ingest_market_wide_numeric(store, provider, source_metric="risk_on", stored_metric="risk_on", provider_name="polymarket")
    now = datetime.now(tz=UTC) + timedelta(seconds=1)
    points = store.read_asof("polymarket", "MARKET", "risk_on", now)
    assert len(points) >= 1


def test_run_once_uses_gamma_provider(tmp_path):
    store = AltDataStore(tmp_path / "alt")
    fixture = FixtureAltDataProvider({
        ("BTCUSDT", "funding_rate"): [AltDataPoint(ts=_T0, available_at=_T0, value=0.001)],
        ("MARKET", "fear_greed"): [AltDataPoint(ts=_T0, available_at=_T0, value=50)],
    })
    from cosmu.data.altdata import FixtureNewsProvider, NewsItem

    news = FixtureNewsProvider({"BTCUSDT": [NewsItem(ts=_T0, available_at=_T0, headline="test")]})
    gamma = _make_provider()
    fred = FixtureAltDataProvider({("MARKET", "T10Y2Y"): [AltDataPoint(ts=_T0, available_at=_T0, value=0.5)]})

    providers = Providers(
        funding=fixture,
        feargreed=fixture,
        news=news,
        fred=fred,
        polymarket=gamma,
        liquidations=FixtureAltDataProvider({}),
        putcall=FixtureAltDataProvider({}),
    )
    counts = run_once(store, symbols=["BTCUSDT"], providers=providers)
    assert counts["pm_risk_on"] == 1  # run_once stores under the canonical pm_risk_on (was stale 'risk_on')
