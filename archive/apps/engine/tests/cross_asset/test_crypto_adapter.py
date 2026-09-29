# The crypto DataAdapter must satisfy core.DataAdapter and be point-in-time honest: bars known only at close,
# alt-data only by availability time, universe survivorship-aware. Uses injected fixtures — no network.

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.adapters.data.crypto import CryptoDataAdapter, instrument_id
from cosmu.core.interfaces import DataAdapter
from cosmu.data.altdata import AltDataPoint
from cosmu.data.market import Bar as MarketBar
from cosmu.data.universe_calendar import Listing

T0 = datetime(2024, 1, 1, tzinfo=UTC)


class FixtureMarket:
    def __init__(self, bars):
        self._bars = bars

    def fetch_bars(self, symbol, timeframe, *, limit):
        return self._bars[-limit:]


class FixtureAlt:
    def __init__(self, series):
        self._series = series  # {(provider, symbol, metric): [AltDataPoint]}

    def read_asof(self, provider, symbol, metric, as_of):
        pts = self._series.get((provider, symbol, metric), [])
        return [p for p in pts if p.available_at <= as_of]


def _market_bars(n=5):
    return [
        MarketBar(ts=T0 + timedelta(days=i), open=Decimal("100"), high=Decimal("101"),
                  low=Decimal("99"), close=Decimal("100"), volume=Decimal("10"))
        for i in range(n)
    ]


def test_crypto_adapter_conforms():
    assert isinstance(CryptoDataAdapter(["BTCUSDT"]), DataAdapter)


def test_bars_are_point_in_time_known_at_close():
    adapter = CryptoDataAdapter(["BTCUSDT"], market_provider=FixtureMarket(_market_bars()))
    bars = adapter.bars(instrument_id("BTCUSDT"), T0, T0 + timedelta(days=10), "1d")
    assert len(bars) == 5
    # a daily bar opened at T0 is only known at its close, T0 + 1 day
    assert bars[0].available_at == bars[0].ts + timedelta(days=1)
    assert all(b.instrument_id == instrument_id("BTCUSDT") and b.interval == "1d" for b in bars)


def test_universe_is_survivorship_aware():
    listings = [
        Listing(symbol="BTCUSDT", listed_at=T0),
        Listing(symbol="DEADUSDT", listed_at=T0, delisted_at=T0 + timedelta(days=3)),
    ]
    adapter = CryptoDataAdapter(["BTCUSDT", "DEADUSDT"], listings=listings)
    early = {i.symbol for i in adapter.universe(T0 + timedelta(days=1))}
    late = {i.symbol for i in adapter.universe(T0 + timedelta(days=5))}
    assert early == {"BTCUSDT", "DEADUSDT"}
    assert late == {"BTCUSDT"}  # DEADUSDT delisted → absent after, present before (no survivorship bias)


def test_features_are_point_in_time():
    pts = [
        AltDataPoint(ts=T0, available_at=T0 + timedelta(days=1), value=0.01),
        AltDataPoint(ts=T0 + timedelta(days=1), available_at=T0 + timedelta(days=2), value=0.02),
    ]
    alt = FixtureAlt({("binance", "BTCUSDT", "funding_rate"): pts})
    adapter = CryptoDataAdapter(
        ["BTCUSDT"], alt_reader=alt, alt_metrics=(("binance", "funding_rate"),),
        transform_versions={"funding_rate": "funding-zscore-v1"},
    )
    as_of = T0 + timedelta(days=1)
    feats = adapter.features(instrument_id("BTCUSDT"), as_of)
    assert len(feats) == 1                                   # only the row available by as_of
    assert feats[0].name == "funding_rate"
    assert feats[0].transform_version == "funding-zscore-v1"
    assert feats[0].available_at <= as_of
