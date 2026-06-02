# intent: pluggable, point-in-time data-source seam — a typed DataSource protocol + a registry so any
# agent can discover and query a source by name. This is the upgrade seam for data sources; concrete
# sources (funding, fear_greed, news, fred, polymarket, coinglass, cboe, osint_adsb) register here.

from __future__ import annotations

from cosmu.data.sources.registry import (
    DataSource,
    DataSourceRegistry,
    SourceFeature,
    default_source_registry,
)

__all__ = ["DataSource", "DataSourceRegistry", "SourceFeature", "default_source_registry"]
