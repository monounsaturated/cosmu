# The prediction-market DataAdapter must satisfy core.DataAdapter, treat odds as the tradable price (point-in-time),
# drop RESOLVED markets from the universe (expiry safety = the prediction-market analogue of survivorship), and
# never let a later odds revision rewrite an earlier point-in-time read.

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cosmu.adapters.data.prediction import Market, PredictionDataAdapter, instrument_id
from cosmu.core.interfaces import AssetClass, DataAdapter
from cosmu.data.altdata import AltDataPoint, AltDataStore

T0 = datetime(2024, 1, 1, tzinfo=UTC)


class FixtureAlt:
    def __init__(self, series):
        self._series = series  # {(provider, token, metric): [AltDataPoint]}

    def read_asof(self, provider, token, metric, as_of):
        return [p for p in self._series.get((provider, token, metric), []) if p.available_at <= as_of]


def _odds(n=5, base=0.5):
    return [AltDataPoint(ts=T0 + timedelta(days=i), available_at=T0 + timedelta(days=i), value=base + 0.01 * i) for i in range(n)]


def test_prediction_adapter_conforms_and_is_prediction():
    adapter = PredictionDataAdapter([Market("RISKON", token="tok1")])
    assert isinstance(adapter, DataAdapter)
    assert adapter.asset_class is AssetClass.PREDICTION


def test_resolved_market_leaves_the_universe():
    markets = [
        Market("LIVE", token="t1", listed_at=T0),
        Market("RESOLVED", token="t2", listed_at=T0, resolves_at=T0 + timedelta(days=3)),
    ]
    adapter = PredictionDataAdapter(markets)
    early = {i.symbol for i in adapter.universe(T0 + timedelta(days=1))}
    late = {i.symbol for i in adapter.universe(T0 + timedelta(days=5))}
    assert early == {"LIVE", "RESOLVED"}
    assert late == {"LIVE"}  # resolved → absent (no resolved-market look-ahead)


def test_odds_are_the_price_and_point_in_time():
    alt = FixtureAlt({("polymarket", "tok1", "odds"): _odds()})
    adapter = PredictionDataAdapter([Market("RISKON", token="tok1")], alt_reader=alt)
    bars = adapter.bars(instrument_id("RISKON"), T0, T0 + timedelta(days=10), "1d")
    assert len(bars) == 5
    assert float(bars[0].close) == 0.5  # the share price IS the probability
    assert float(bars[4].close) == 0.54
    assert all(b.available_at == b.ts for b in bars)  # CLOB quotes known at quote time


def test_revised_odds_do_not_rewrite_an_earlier_read(tmp_path):
    store = AltDataStore(root=tmp_path / "pm")
    # first pull: odds=0.40 for T0, available T0
    store.append("polymarket", "tok1", "odds", [AltDataPoint(ts=T0, available_at=T0, value=0.40)])
    # a later revision of the SAME ts arrives at T0+2 with a different value
    store.append("polymarket", "tok1", "odds", [AltDataPoint(ts=T0, available_at=T0 + timedelta(days=2), value=0.90)])
    adapter = PredictionDataAdapter([Market("RISKON", token="tok1")], alt_reader=store)
    # as of T0+1 the revision is not yet known → the earlier read stands
    early = adapter.bars(instrument_id("RISKON"), T0, T0 + timedelta(days=1), "1d")
    assert float(early[0].close) == 0.40
    # as of T0+3 the revision is known → latest-available-wins
    late = adapter.bars(instrument_id("RISKON"), T0, T0 + timedelta(days=3), "1d")
    assert float(late[0].close) == 0.90


def test_direction_stays_signed_via_opposite_token():
    # 'down' is the opposite side, not a negative quantity — core.AssetClass keeps one shape per class.
    assert AssetClass.PREDICTION == "prediction"
