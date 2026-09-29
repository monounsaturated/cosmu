# The equity DataAdapter must satisfy core.DataAdapter, be point-in-time honest (a daily bar known only after
# its session; FRED macro known only by its release time), and DECLARE its free-bars survivorship limit.

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.adapters.data.equity import EquityDataAdapter, instrument_id
from cosmu.core.interfaces import AssetClass, DataAdapter
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
        return [p for p in self._series.get((provider, symbol, metric), []) if p.available_at <= as_of]


def _bars(n=5):
    return [
        MarketBar(ts=T0 + timedelta(days=i), open=Decimal("400"), high=Decimal("405"),
                  low=Decimal("395"), close=Decimal("400"), volume=Decimal("1000"))
        for i in range(n)
    ]


def test_equity_adapter_conforms_and_is_equity():
    adapter = EquityDataAdapter(["SPY"], market_provider=FixtureMarket(_bars()))
    assert isinstance(adapter, DataAdapter)
    assert adapter.asset_class is AssetClass.EQUITY


def test_free_bars_survivorship_limit_is_declared():
    # The free-data limit is explicit, not hidden: this gate tests signal presence, not capacity.
    assert EquityDataAdapter.survivorship_complete is False
    from cosmu.data.market import StooqDailyBarsProvider

    assert StooqDailyBarsProvider.survivorship_complete is False


def test_daily_bar_known_only_after_session():
    adapter = EquityDataAdapter(["SPY"], market_provider=FixtureMarket(_bars()))
    bars = adapter.bars(instrument_id("SPY"), T0, T0 + timedelta(days=10), "1d")
    assert len(bars) == 5
    assert bars[0].available_at == bars[0].ts + timedelta(days=1)  # known after the session closes
    assert all(b.instrument_id == instrument_id("SPY") for b in bars)


def test_macro_features_are_point_in_time_and_market_wide():
    pts = [
        AltDataPoint(ts=T0, available_at=T0 + timedelta(days=1), value=0.5),
        AltDataPoint(ts=T0 + timedelta(days=1), available_at=T0 + timedelta(days=2), value=0.7),
    ]
    alt = FixtureAlt({("fred", "MARKET", "T10Y2Y"): pts})  # macro is stored market-wide
    adapter = EquityDataAdapter(
        ["SPY"], alt_reader=alt, macro_metrics=(("fred", "T10Y2Y"),),
        transform_versions={"T10Y2Y": "macro-regime-v1"},
    )
    feats = adapter.features(instrument_id("SPY"), T0 + timedelta(days=1))
    assert len(feats) == 1  # only the row available by as_of
    assert feats[0].name == "T10Y2Y"
    assert feats[0].transform_version == "macro-regime-v1"
    assert feats[0].available_at <= T0 + timedelta(days=1)


def test_universe_is_survivorship_aware_with_listings():
    listings = [
        Listing(symbol="SPY", listed_at=T0),
        Listing(symbol="GONE", listed_at=T0, delisted_at=T0 + timedelta(days=3)),
    ]
    adapter = EquityDataAdapter(["SPY", "GONE"], listings=listings)
    early = {i.symbol for i in adapter.universe(T0 + timedelta(days=1))}
    late = {i.symbol for i in adapter.universe(T0 + timedelta(days=5))}
    assert early == {"SPY", "GONE"}
    assert late == {"SPY"}
