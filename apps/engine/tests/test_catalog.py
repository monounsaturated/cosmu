# Offline guard that the managed-source catalog stays in lock-step with the canonical store routing map and
# the feature registry. If a source is wired into ingest but not the catalog (or vice-versa), this fails —
# so `manage-data verify` can never silently under-report coverage.

from __future__ import annotations

from cosmu.data.altdata import _STORE_PROVIDER_OF
from cosmu.ingest import catalog


def test_catalog_metrics_match_store_routing():
    # Every semantic metric the store can route MUST be owned by exactly one catalog source, and the catalog
    # must not invent a metric the store can't route.
    assert catalog.catalog_metric_set() == set(_STORE_PROVIDER_OF)


def test_each_metric_owned_by_one_source():
    owners: dict[str, int] = {}
    for spec in catalog.managed_sources().values():
        for metric in spec.metrics:
            owners[metric] = owners.get(metric, 0) + 1
    assert all(count == 1 for count in owners.values()), {m: c for m, c in owners.items() if c != 1}


def test_disabled_mislabeled_metrics_are_not_actively_ingested():
    """The two disabled honesty-fix metrics (vix_term_slope = phantom VIXCLS duplicate; exchange_netflow =
    mislabeled perp long/short ratio) must NOT be fetched by any active source — only the no-op `dormant`
    source carries them (so banked rows stay routed/readable, but no new mislabeled rows are written)."""
    from cosmu.ingest.catalog import _DORMANT_METRICS, _fetch_dormant

    sources = catalog.managed_sources()
    for metric in ("vix_term_slope", "exchange_netflow"):
        owners = [name for name, spec in sources.items() if metric in spec.metrics]
        assert owners == ["dormant"], f"{metric} should be owned only by the dormant source, got {owners}"
    # The standalone `netflow` source is gone entirely; the macro source no longer lists vix_term_slope.
    assert "netflow" not in sources
    assert "vix_term_slope" not in sources["macro"].metrics
    # The dormant source's fetch is a genuine no-op (writes nothing, returns 0).
    assert set(_DORMANT_METRICS) == {"vix_term_slope", "exchange_netflow"}
    assert _fetch_dormant(None, ["BTCUSDT"], None) == 0


def test_expected_alt_specs_cover_market_wide_and_per_symbol():
    specs = catalog.expected_alt_specs(["BTCUSDT", "ETHUSDT"])
    by_metric = {}
    for _provider, symbol, metric in specs:
        by_metric.setdefault(metric, set()).add(symbol)
    # A market-wide metric lives under MARKET only; a per-symbol metric under each symbol.
    assert by_metric["fear_greed"] == {"MARKET"}
    assert by_metric["funding_rate"] == {"BTCUSDT", "ETHUSDT"}
    # Venue-fee metrics use the composite <venue>:<symbol> key.
    assert by_metric["venue_fees_maker"] == {"binance:BTCUSDT", "binance:ETHUSDT"}
