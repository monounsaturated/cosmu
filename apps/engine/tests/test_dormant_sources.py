# Proves the dormant key-free sources actually PRODUCE rows in ingest: Reddit sentiment, Binance
# open-interest/basis/netflow, CBOE put/call. All offline via injected `_fetcher` (canned real-shaped
# payloads) — NO live network. Also asserts run_once lands them AND that the run-level FRED memoization
# fetches each shared series exactly once (no redundant external calls). (Coinglass liquidations were
# removed 2026-06-26 — key-gated + direction-blind; graveyarded in config/feature_registry.py.)

from __future__ import annotations

from datetime import UTC, datetime

from cosmu.data.altdata import (
    AltDataPoint,
    AltDataStore,
    BinanceBasisProvider,
    BinanceOpenInterestProvider,
    CboePutCallProvider,
    ExchangeNetflowProvider,
    FixtureAltDataProvider,
    FixtureNewsProvider,
    RedditSentimentProvider,
)
from cosmu.ingest.run import Providers, run_once

_T0 = datetime(2023, 1, 1, tzinfo=UTC)


# --------------------------------------------------------------------------- per-provider parse → rows


def test_reddit_sentiment_scores_bull_minus_bear_in_range():
    hot = {
        "data": {
            "children": [
                {"data": {"title": "BTC to the moon, massive bullish breakout rally"}},
                {"data": {"title": "Altcoins pump as buyers accumulate"}},
                {"data": {"title": "Bearish crash incoming, everyone is selling"}},
                {"data": {"title": "neutral discussion about protocols"}},
            ]
        }
    }
    prov = RedditSentimentProvider(subreddits=("cryptocurrency",), _fetcher=lambda url: hot)
    pts = prov.fetch_series("MARKET", "reddit_sentiment", limit=1)
    assert len(pts) == 1
    assert -1.0 <= pts[0].value <= 1.0
    assert pts[0].value > 0  # 2 bull, 1 bear → net positive
    assert pts[0].available_at == pts[0].ts  # live read: availability == observation


def test_binance_open_interest_produces_rows():
    rows = [
        {"timestamp": 1672531200000, "sumOpenInterestValue": "12345.6"},
        {"timestamp": 1672534800000, "sumOpenInterestValue": "12400.0"},
    ]
    prov = BinanceOpenInterestProvider(_fetcher=lambda url: rows)
    pts = prov.fetch_series("BTCUSDT", "open_interest", limit=10)
    assert [p.value for p in pts] == [12345.6, 12400.0]
    assert all(p.available_at == p.ts for p in pts)


def test_binance_basis_produces_row():
    row = {"markPrice": "101.0", "indexPrice": "100.0", "time": 1672531200000}
    prov = BinanceBasisProvider(_fetcher=lambda url: row)
    pts = prov.fetch_series("BTCUSDT", "perp_spot_basis", limit=1)
    assert len(pts) == 1
    assert abs(pts[0].value - 0.01) < 1e-9  # (mark - index) / index = 1%


def test_exchange_netflow_produces_rows():
    rows = [
        {"timestamp": 1672531200000, "longShortRatio": "1.25"},
        {"timestamp": 1672534800000, "longShortRatio": "0.80"},
    ]
    prov = ExchangeNetflowProvider(_fetcher=lambda url: rows)
    pts = prov.fetch_series("BTCUSDT", "exchange_netflow", limit=10)
    assert [round(p.value, 2) for p in pts] == [0.25, -0.20]  # ratio - 1: positive=net longs, negative=net shorts


def test_cboe_putcall_produces_rows():
    csv_text = "Date,P/C\n2023-01-03,0.95\n2023-01-04,1.10\n"
    prov = CboePutCallProvider(_fetcher=lambda url: csv_text)
    pts = prov.fetch_series("MARKET", "putcall_ratio", limit=10)
    assert [p.value for p in pts] == [0.95, 1.10]
    assert pts[0].available_at > pts[0].ts  # finalized after the close → next-day availability floor


# --------------------------------------------------------------------------- run_once lands the rows


def _empty():
    return FixtureAltDataProvider({})


def test_run_once_lands_dormant_sources(tmp_path):
    store = AltDataStore(tmp_path / "alt")
    reddit = RedditSentimentProvider(
        subreddits=("cryptocurrency",),
        _fetcher=lambda url: {"data": {"children": [{"data": {"title": "bullish moon rally"}}]}},
    )
    oi = BinanceOpenInterestProvider(_fetcher=lambda url: [{"timestamp": 1672531200000, "sumOpenInterestValue": "1.0"}])
    basis = BinanceBasisProvider(_fetcher=lambda url: {"markPrice": "101", "indexPrice": "100", "time": 1672531200000})
    netflow = ExchangeNetflowProvider(_fetcher=lambda url: [{"timestamp": 1672531200000, "longShortRatio": "1.1"}])

    providers = Providers(
        funding=_empty(), feargreed=_empty(), news=FixtureNewsProvider({}), fred=_empty(),
        polymarket=_empty(), putcall=_empty(), defillama=_empty(),
        open_interest=oi, basis=basis, netflow=netflow, osint=_empty(), polymarket_clob=_empty(),
        reddit=reddit, lunarcrush=_empty(), xai_twitter=_empty(), venue_fees=_empty(),
    )
    counts = run_once(store, symbols=["BTCUSDT"], providers=providers)

    assert counts["reddit_sentiment"] == 1
    assert counts["open_interest"] == 1
    assert counts["perp_spot_basis"] == 1
    # liquidation_cascade was graveyarded 2026-06-26 (key-gated + direction-blind) — run_once no longer
    # ingests it, so it is absent from counts and no row lands.
    assert "liquidation_cascade" not in counts
    # exchange_netflow is a DISABLED/dormant honesty fix (the provider fetched the Binance perp long/short
    # ratio, not on-chain netflow) — run_once NO LONGER ingests it, so it is absent from counts and no new
    # row lands. The provider itself still parses correctly (test_exchange_netflow_produces_rows above).
    assert "exchange_netflow" not in counts
    # the rows are actually in the point-in-time store under their canonical provider keys
    far = datetime(2099, 1, 1, tzinfo=UTC)
    assert store.read_asof("reddit", "MARKET", "reddit_sentiment", far)
    assert store.read_asof("binance", "BTCUSDT", "open_interest", far)
    assert store.read_asof("binance", "BTCUSDT", "perp_spot_basis", far)
    assert not store.read_asof("binance", "BTCUSDT", "exchange_netflow", far)  # dormant: never re-ingested
    assert not store.read_asof("coinglass", "BTCUSDT", "liquidation_cascade", far)  # graveyarded: never ingested


def test_run_once_memoizes_shared_fred_series(tmp_path):
    # The single FRED provider feeds macro_regime + yield_curve_2s10s (both T10Y2Y) off one shared series.
    # (VIXCLS now feeds only vix_level — the duplicate vix_term_slope was disabled.) Memoization must still
    # fetch each shared series exactly ONCE per run.
    class CountingFred:
        def __init__(self):
            self.calls: list[str] = []

        def fetch_series(self, symbol, metric, *, limit):
            self.calls.append(metric)
            return [AltDataPoint(ts=_T0, available_at=_T0, value=1.0)]

    fred = CountingFred()
    store = AltDataStore(tmp_path / "alt")
    providers = Providers(
        funding=_empty(), feargreed=_empty(), news=FixtureNewsProvider({}), fred=fred,
        polymarket=_empty(), putcall=_empty(), defillama=_empty(),
        open_interest=_empty(), basis=_empty(), netflow=_empty(), osint=_empty(), polymarket_clob=_empty(),
        reddit=_empty(), lunarcrush=_empty(), xai_twitter=_empty(), venue_fees=_empty(),
    )
    run_once(store, symbols=["BTCUSDT"], providers=providers)
    assert fred.calls.count("VIXCLS") == 1   # would be 2 without memoization
    assert fred.calls.count("T10Y2Y") == 1   # would be 2 without memoization
