# intent: a point-in-time-safe seam for social/alt data (LunarCrush etc.) feeding the gate and, later, the LLM feature factory; inputs: provider pulls; outputs: ordered AltDataPoint series readable "as of" a time; invariants: every point carries an availability time, snapshots are append-only (vendors revise history — we never overwrite), transforms are causal (rolling only), and secrets stay server-side.

# This file is a thin re-export shim. All implementation lives under cosmu.data.providers.*
# Every name that was top-level in the original monolith is re-exported here so that the 40+
# test files and ~25 engine modules that import from cosmu.data.altdata continue to work unchanged.

from __future__ import annotations

from cosmu.data.providers._types import (  # noqa: F401
    AltDataPoint,
    AltDataProvider,
    NewsItem,
    NewsProvider,
    _ssl_context,
)
from cosmu.data.providers.fees import (  # noqa: F401
    VenueFeesProvider,
    read_pit_fee,
)
from cosmu.data.providers.fixtures import (  # noqa: F401
    FixtureAltDataProvider,
    FixtureNewsProvider,
)
from cosmu.data.providers.funding import (  # noqa: F401
    BinanceFundingHistoryProvider,
    CachedFundingRateProvider,
    FundingRateProvider,
    KrakenFuturesFundingRateProvider,
    OkxFundingRateProvider,
)
from cosmu.data.providers.lunarcrush import LunarCrushProvider  # noqa: F401
from cosmu.data.providers.macro import (  # noqa: F401
    CboePutCallProvider,
    FredMacroProvider,
    _parse_cboe_date,
    _points_from_cboe_putcall,
)
from cosmu.data.providers.news import (  # noqa: F401
    GdeltNewsProvider,
    GdeltToneProvider,
    OsintAirActivityProvider,
    _gdelt_query,
    _news_from_gdelt,
    _parse_gdelt_date,
    _points_from_gdelt_tone,
)
from cosmu.data.providers.onchain import (  # noqa: F401
    BinanceBasisProvider,
    BinanceOpenInterestProvider,
    CoinglassLiquidationProvider,
    DefiLlamaTvlProvider,
    DeribitDvolProvider,
    ExchangeNetflowProvider,
    _points_from_coinglass,
    _points_from_deribit_dvol,
)
from cosmu.data.providers.prediction import (  # noqa: F401
    PolymarketClobProvider,
    PolymarketGammaProvider,
    PolymarketOddsProvider,
)
from cosmu.data.providers.reddit import RedditSentimentProvider  # noqa: F401
from cosmu.data.providers.sentiment import (  # noqa: F401
    FearGreedProvider,
    XaiTwitterProvider,
)
from cosmu.data.providers.store import (  # noqa: F401
    _STORE_MARKET_WIDE,
    _STORE_METRIC_ALIAS,  # noqa: F401
    _STORE_PROVIDER_OF,
    AltDataStore,
    PgAltDataStore,
    StoreBackedAltProvider,
    UnknownAltMetricError,
)
from cosmu.data.providers.util import rolling_zscore  # noqa: F401

__all__ = [
    # types / protocols
    "AltDataPoint",
    "AltDataProvider",
    "NewsItem",
    "NewsProvider",
    "_ssl_context",
    # store
    "AltDataStore",
    "PgAltDataStore",
    "StoreBackedAltProvider",
    "UnknownAltMetricError",
    "_STORE_MARKET_WIDE",
    "_STORE_METRIC_ALIAS",
    "_STORE_PROVIDER_OF",
    # providers
    "LunarCrushProvider",
    "RedditSentimentProvider",
    "FundingRateProvider",
    "CachedFundingRateProvider",
    "BinanceFundingHistoryProvider",
    "OkxFundingRateProvider",
    "KrakenFuturesFundingRateProvider",
    "FearGreedProvider",
    "XaiTwitterProvider",
    "FredMacroProvider",
    "CboePutCallProvider",
    "PolymarketOddsProvider",
    "PolymarketGammaProvider",
    "PolymarketClobProvider",
    "DefiLlamaTvlProvider",
    "ExchangeNetflowProvider",
    "BinanceOpenInterestProvider",
    "BinanceBasisProvider",
    "CoinglassLiquidationProvider",
    "DeribitDvolProvider",
    "GdeltNewsProvider",
    "GdeltToneProvider",
    "OsintAirActivityProvider",
    "FixtureAltDataProvider",
    "FixtureNewsProvider",
    "read_pit_fee",
    "VenueFeesProvider",
    "rolling_zscore",
    # private helpers
    "_gdelt_query",
    "_news_from_gdelt",
    "_parse_cboe_date",
    "_parse_gdelt_date",
    "_points_from_cboe_putcall",
    "_points_from_coinglass",
    "_points_from_deribit_dvol",
    "_points_from_gdelt_tone",
]
