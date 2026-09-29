# Offline tests for the FREE cross-asset daily price sources (Stooq primary, Yahoo alternate) and their
# point-in-time ingest. Everything is injected (canned CSV / JSON) so no live network is touched. Asserts the
# next-day availability floor, honest [] on unknown metric, and that the new metrics are fully lock-stepped
# into the feature registry + store routing + catalog.

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from cosmu.config.feature_registry import feature_names
from cosmu.data.altdata import _STORE_MARKET_WIDE, _STORE_PROVIDER_OF, AltDataStore
from cosmu.data.sources.multiasset import (
    MULTIASSET_METRICS,
    StooqDailyProvider,
    YahooDailyProvider,
)
from cosmu.ingest import catalog

_FAR = datetime(2099, 1, 1, tzinfo=UTC)

_STOOQ_CSV = (
    "Date,Open,High,Low,Close,Volume\n"
    "2024-01-02,2000,2010,1995,2005,100\n"
    "2024-01-03,2005,2015,2000,2012,120\n"
    "2024-01-04,2012,2020,2008,2018,90\n"
)


def _stooq() -> StooqDailyProvider:
    return StooqDailyProvider(_fetcher=lambda url: _STOOQ_CSV)


def test_stooq_parses_close_with_next_day_availability():
    pts = _stooq().fetch_series("MARKET", "gold_xau", limit=10)
    assert [p.value for p in pts] == [2005.0, 2012.0, 2018.0]
    # a daily close is finalized after the session → available the NEXT day (point-in-time floor)
    for p in pts:
        assert (p.available_at - p.ts).days == 1


def test_stooq_unknown_metric_is_empty():
    assert _stooq().fetch_series("MARKET", "not_a_metric", limit=10) == []


def test_stooq_limit_trims_to_trailing():
    pts = _stooq().fetch_series("MARKET", "spx_index", limit=2)
    assert [p.value for p in pts] == [2012.0, 2018.0]


def test_yahoo_alternate_same_contract():
    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": [1704153600, 1704240000, 1704326400],
                    "indicators": {"quote": [{"close": [2005.0, None, 2018.0]}]},  # null is a Yahoo gap → skipped
                }
            ]
        }
    }
    prov = YahooDailyProvider(_fetcher=lambda url: payload)
    pts = prov.fetch_series("MARKET", "gold_xau", limit=10)
    assert [p.value for p in pts] == [2005.0, 2018.0]  # the null close is dropped, not fabricated
    assert all((p.available_at - p.ts).days == 1 for p in pts)
    assert prov.fetch_series("MARKET", "not_a_metric", limit=10) == []


def test_ingest_lands_market_wide_under_stooq_provider(tmp_path):
    store = AltDataStore(tmp_path / "alt")
    spec = catalog.managed_sources()["multiasset"]
    providers = SimpleNamespace(multiasset=_stooq())
    n = spec.fetch(store, ["BTCUSDT"], providers)
    assert n == 3 * len(MULTIASSET_METRICS)  # 3 rows × every metric
    # stored market-wide under the stooq provider at the MARKET key (not per crypto symbol)
    assert len(store.read_asof("stooq", "MARKET", "gold_xau", _FAR)) == 3
    assert store.read_asof("stooq", "BTCUSDT", "gold_xau", _FAR) == []


def test_new_metrics_are_lock_stepped():
    for metric in MULTIASSET_METRICS:
        assert metric in feature_names()              # referenceable by the lab
        assert _STORE_PROVIDER_OF[metric] == "stooq"  # store routes it
        assert metric in _STORE_MARKET_WIDE           # market-wide (MARKET key)
    # the catalog owns exactly the store's metric set (the existing lock-step guard, re-asserted here)
    assert catalog.catalog_metric_set() == set(_STORE_PROVIDER_OF)
