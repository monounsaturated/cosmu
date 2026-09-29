# intent: the seam that makes an INDEX a first-class, key-off-able strategy FEATURE — so "strategies built on
# top of indexes" is a config merge, not a rewrite. inputs: a Store; outputs: metric→provider routes (+ the
# market-wide set) for every registered index, and a StoreBackedAltProvider pre-loaded with them; invariants:
# additive only (never shadows a canonical _STORE_PROVIDER_OF route), read-only.

from __future__ import annotations

from typing import Any

from cosmu.indexes.registry import list_indexes
from cosmu.indexes.spec import INDEX_PROVIDER


def index_routes(store: Any) -> dict[str, str]:
    """{idx_<id>: 'index'} for every registered index — merge into StoreBackedAltProvider.provider_of so the
    gate/backtest can read an index series by metric name exactly like any other alt feature."""
    return {spec.metric: INDEX_PROVIDER for spec in list_indexes(store)}


def index_market_wide(store: Any) -> frozenset[str]:
    """The subset of index metrics stored MARKET-wide (one series for the whole tape)."""
    return frozenset(spec.metric for spec in list_indexes(store) if spec.market_wide)


def store_provider_with_indexes(store: Any):
    """A StoreBackedAltProvider whose routing includes every registered index — the one call a strategy/gate
    construction site swaps in to make indexes readable as features. Additive over the canonical routes."""
    from cosmu.data.altdata import _STORE_MARKET_WIDE, _STORE_PROVIDER_OF, StoreBackedAltProvider

    provider_of = dict(_STORE_PROVIDER_OF)
    provider_of.update(index_routes(store))  # additive; canonical metrics already present win on key collision below
    # Canonical routes must never be shadowed by an index that (mis)used a reserved name — re-assert them.
    provider_of.update(_STORE_PROVIDER_OF)
    market_wide = _STORE_MARKET_WIDE | index_market_wide(store)
    return StoreBackedAltProvider(store, provider_of=provider_of, market_wide=market_wide)
