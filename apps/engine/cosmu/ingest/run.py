# intent: the one-pass, cron-able free-data ingest CLI — arrange the free sources once, hit go, fill the append-only point-in-time alt-data store; inputs: the real free providers (funding/F&G/GDELT news/FRED macro/Polymarket odds/Coinglass liquidations/CBOE put-call), injectable so tests run offline on fixtures; outputs: per-source append counts into the store the cross-asset gate reads; invariants: append-only + point-in-time (re-runs never rewrite the view), ZERO API keys required, ONE pass per invocation (NOT a daemon), per-source failure is caught and logged as a 0 count so one dead source never aborts the pass, and the LLM runs ONLY at news standardization (cached, offline lexicon by default).

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from cosmu.config.settings import get_settings
from cosmu.data.altdata import (
    AltDataProvider,
    AltDataStore,
    CboePutCallProvider,
    CoinglassLiquidationProvider,
    FearGreedProvider,
    FredMacroProvider,
    FundingRateProvider,
    GdeltNewsProvider,
    NewsProvider,
    PolymarketOddsProvider,
)
from cosmu.ingest.pipeline import (
    ingest_liquidations,
    ingest_market_wide_numeric,
    ingest_news_sentiment,
    ingest_numeric,
    ingest_putcall,
)
from cosmu.ingest.standardize import StandardizedNews

logger = logging.getLogger("cosmu.ingest.run")

# Default crypto universe (mirrors the seeded Binance instruments in spine.venue.default_catalog).
DEFAULT_SYMBOLS = ("BTCUSDT", "ETHUSDT")
# Native source ids for the two market-wide cross-asset transfer series — mapped to their SEMANTIC
# names (macro_regime / risk_on) at ingest, exactly as ingest_cross_asset_sources does.
DEFAULT_FRED_SERIES = "T10Y2Y"  # 10y-2y curve slope: one macro read conditions risk across classes
DEFAULT_POLYMARKET_TOKEN = "risk-on"  # a market token id; real runs override via --polymarket-token


@dataclass
class Providers:
    """The injectable set of free providers. Default = the REAL free APIs (zero keys). Tests pass fixtures
    so a pass runs fully offline. News standardization uses the offline lexicon unless an `llm` is given."""

    funding: AltDataProvider = field(default_factory=FundingRateProvider)
    feargreed: AltDataProvider = field(default_factory=FearGreedProvider)
    news: NewsProvider = field(default_factory=GdeltNewsProvider)
    fred: AltDataProvider = field(default_factory=FredMacroProvider)
    polymarket: AltDataProvider = field(default_factory=PolymarketOddsProvider)
    liquidations: AltDataProvider = field(default_factory=CoinglassLiquidationProvider)
    putcall: AltDataProvider = field(default_factory=CboePutCallProvider)
    llm: Callable[[str], StandardizedNews] | None = None
    fred_series: str = DEFAULT_FRED_SERIES
    polymarket_token: str = DEFAULT_POLYMARKET_TOKEN

    @classmethod
    def from_settings(cls, settings) -> "Providers":  # noqa: ANN001
        """Build the real free providers WITH the operator's keys/tokens wired in — so setting FRED_API_KEY
        (free) and POLYMARKET_TOKEN (a real market id) is all it takes for macro_regime / risk_on to connect.
        Sources needing nothing (Binance/Fear&Greed/GDELT) work regardless; missing key/token → that one
        source stays empty (caught by _safe), never crashing the pass."""
        return cls(
            fred=FredMacroProvider(api_key=settings.fred_api_key),
            polymarket_token=settings.polymarket_token or DEFAULT_POLYMARKET_TOKEN,
        )


def _default_store():  # noqa: ANN202 - AltDataStore | PgAltDataStore
    """Pick the backend the SAME way the API does: postgres URL → PgAltDataStore over the Store, else the
    JSONL AltDataStore. ZERO keys required — both are append-only point-in-time stores with one interface."""
    settings = get_settings()
    if settings.database_url.startswith("postgres://") or settings.database_url.startswith("postgresql://"):
        from cosmu.data.altdata import PgAltDataStore
        from cosmu.knowledge.store import Store

        return PgAltDataStore(Store(settings))
    return AltDataStore()


def _safe(source: str, fn: Callable[[], int]) -> int:
    """Run one source's ingest; a network failure / None is caught and logged as a 0 count so one dead
    source never aborts the pass. This is what makes the cron-able pass robust without a babysitter."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - one dead source must never abort the whole pass
        logger.warning("ingest source %s failed (counted as 0): %s", source, exc)
        return 0


def run_once(store=None, *, symbols: list[str] | None = None, providers: Providers | None = None) -> dict[str, int]:  # noqa: ANN001
    """ONE append-only, point-in-time pass over the free sources into the alt-data store, composing the
    existing ingest_* primitives. Returns per-source append counts. Per-source failure → a 0 count, never
    an abort. The LLM runs ONLY at news standardization (cached); everything else is numeric (no LLM)."""
    store = store if store is not None else _default_store()
    symbols = list(symbols) if symbols is not None else list(DEFAULT_SYMBOLS)
    p = providers if providers is not None else Providers.from_settings(get_settings())

    counts: dict[str, int] = {}
    counts["funding_rate"] = _safe(
        "funding_rate", lambda: ingest_numeric(store, p.funding, symbols, "funding_rate", provider_name="binance")
    )
    # Fear & Greed and the cross-asset transfer series are market-wide → ingest once under the MARKET key.
    counts["fear_greed"] = _safe(
        "fear_greed", lambda: ingest_numeric(store, p.feargreed, ["MARKET"], "fear_greed", provider_name="alternative.me")
    )
    counts["news_sentiment"] = _safe(
        "news_sentiment", lambda: ingest_news_sentiment(store, p.news, symbols, llm=p.llm)
    )
    counts["macro_regime"] = _safe(
        "macro_regime",
        lambda: ingest_market_wide_numeric(
            store, p.fred, source_metric=p.fred_series, stored_metric="macro_regime", provider_name="fred"
        ),
    )
    counts["risk_on"] = _safe(
        "risk_on",
        lambda: ingest_market_wide_numeric(
            store, p.polymarket, source_metric=p.polymarket_token, stored_metric="risk_on", provider_name="polymarket"
        ),
    )
    counts["liquidations"] = _safe("liquidations", lambda: ingest_liquidations(store, p.liquidations, symbols))
    counts["putcall_ratio"] = _safe("putcall_ratio", lambda: ingest_putcall(store, p.putcall))
    return counts


def _run_passes(passes: int) -> dict[str, int]:
    """Run N bounded passes (default 1). Append-only means a re-run is just more rows; the point-in-time
    view is unchanged. Returns the LAST pass's counts (what `python3 -m cosmu.ingest.run` prints)."""
    last: dict[str, int] = {}
    for i in range(max(1, passes)):
        last = run_once()
        if passes > 1:
            print(f"pass {i + 1}/{passes}: {last}")
    return last


def _main(argv: list[str] | None = None) -> int:
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="One-pass free-data ingest into the alt-data store (no keys).")
    parser.add_argument("--passes", type=int, default=1, help="number of bounded passes to run (default 1)")
    args = parser.parse_args(argv)

    counts = _run_passes(args.passes)
    print("FREE-DATA INGEST — one pass complete")
    for source, n in counts.items():
        print(f"  {source:<15} {n:>6} points")
    total = sum(counts.values())
    print(f"  {'TOTAL':<15} {total:>6} points")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
