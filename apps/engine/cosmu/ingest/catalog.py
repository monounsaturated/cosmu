# intent: the single declarative catalog of MANAGED data sources — the discovery + dispatch surface behind
# `manage-data fetch/backfill/verify`; inputs: the `Providers` set + the canonical metric→provider map in
# altdata; outputs: (1) the list of expected (provider, symbol, metric) series a coverage report should find,
# (2) a per-source FETCH closure so one source can be pulled by name, (3) the BACKFILL wiring for the
# paginated sources (funding history, multi-venue bars). Invariants: this NEVER re-implements an ingest
# primitive — every fetch composes the existing `ingest_*` helpers; the alt-metric set is kept in lock-step
# with `altdata._STORE_PROVIDER_OF` (a consistency test fails if a source is added to ingest but not here).

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from cosmu.data.altdata import _STORE_MARKET_WIDE, _STORE_PROVIDER_OF
from cosmu.ingest.pipeline import (
    MemoizingProvider,
    ingest_liquidations,
    ingest_market_wide_numeric,
    ingest_news_event_score,
    ingest_news_sentiment,
    ingest_numeric,
)

# Default market-bar coverage targets. Binance + Kraken via ccxt (the two venues the unified fetch layer
# manages); daily bars are the backtest's spine timeframe.
DEFAULT_BAR_VENUES = ("binance", "kraken")
DEFAULT_BAR_TIMEFRAME = "1d"
# The managed timeframes — multiple resolutions so a strategy can be screened at its native bar size (the daily
# spine + an intraday 4h/1h read). `verify` reports every (venue, symbol, timeframe) and `backfill bars` walks
# them all when no single `--timeframe` is given. Ordered coarse→fine (1d is the spine).
DEFAULT_BAR_TIMEFRAMES = ("1d", "4h", "1h")

# FRED native series id → the SEMANTIC metric it is stored under (mirrors run_once exactly). macro_regime's
# native id is operator-configurable (Providers.fred_series); the rest are fixed.
_FRED_FIXED: dict[str, str] = {
    "vix_level": "VIXCLS",
    "fed_funds_rate": "DFF",
    "dxy": "DTWEXBGS",
    "yield_curve_2s10s": "T10Y2Y",
    "credit_spread": "BAMLH0A0HYM2",
    "vix_term_slope": "VIXCLS",
}


@dataclass(frozen=True)
class SourceSpec:
    """One managed source. `metrics` are the SEMANTIC names it writes (the keys the coverage report and the
    store routing use). `fetch` pulls the source ONCE for the given symbols and returns the appended count;
    `backfill` (when present) walks paginated history for `days` back. `kind` is "alt" or "bars"."""

    name: str
    kind: str  # "alt" | "bars"
    metrics: tuple[str, ...]
    fetch: Callable[[Any, list[str], Any], int]  # (store, symbols, providers) -> appended count
    backfill: Callable[..., dict[str, Any]] | None = None
    market_wide: bool = False
    per_symbol: bool = True
    note: str = ""


# --------------------------------------------------------------------------- fetch closures (compose only)


def _fetch_numeric(metric: str, provider_field: str, provider_name: str) -> Callable[[Any, list[str], Any], int]:
    def fetch(store: Any, symbols: list[str], providers: Any) -> int:
        provider = getattr(providers, provider_field)
        return ingest_numeric(store, provider, symbols, metric, provider_name=provider_name)

    return fetch


def _fetch_market_wide(source_metric: str, stored_metric: str, provider_field: str, provider_name: str) -> Callable[[Any, list[str], Any], int]:
    def fetch(store: Any, symbols: list[str], providers: Any) -> int:
        provider = getattr(providers, provider_field)
        return ingest_market_wide_numeric(
            store, provider, source_metric=source_metric, stored_metric=stored_metric, provider_name=provider_name,
        )

    return fetch


def _fetch_fred(store: Any, symbols: list[str], providers: Any) -> int:
    """All FRED-derived macro metrics in one pass, memoized so a shared native series (VIXCLS feeds both
    vix_level + vix_term_slope; T10Y2Y feeds macro_regime + yield_curve_2s10s) is fetched ONCE — exactly the
    run_once invariant, reused here."""
    fred = MemoizingProvider(providers.fred)
    total = 0
    total += ingest_market_wide_numeric(store, fred, source_metric=providers.fred_series, stored_metric="macro_regime", provider_name="fred")
    for stored, native in _FRED_FIXED.items():
        total += ingest_market_wide_numeric(store, fred, source_metric=native, stored_metric=stored, provider_name="fred")
    return total


def _fetch_news(store: Any, symbols: list[str], providers: Any) -> int:
    n = ingest_news_sentiment(store, providers.news, symbols, llm=getattr(providers, "llm", None))
    # The event scorer uses the cheap-OpenRouter formatter (key-gated → None = deterministic lexicon).
    n += ingest_news_event_score(store, providers.news, symbols, llm=getattr(providers, "event_llm", None))
    return n


def _fetch_multiasset(store: Any, symbols: list[str], providers: Any) -> int:
    """All cross-asset daily price levels (metals / commodities / equity indexes / FX) in one pass, each
    market-wide under its SEMANTIC name (free, no key). Composes ingest_market_wide_numeric — no re-impl."""
    from cosmu.data.sources.multiasset import MULTIASSET_METRICS

    total = 0
    for metric in MULTIASSET_METRICS:
        total += ingest_market_wide_numeric(
            store, providers.multiasset, source_metric=metric, stored_metric=metric, provider_name="stooq",
        )
    return total


def _fetch_polymarket_clob(store: Any, symbols: list[str], providers: Any) -> int:
    total = 0
    for metric in ("pm_implied_prob", "pm_prob_velocity", "pm_book_depth"):
        total += ingest_market_wide_numeric(
            store, providers.polymarket_clob, source_metric=metric, stored_metric=metric, provider_name="polymarket",
        )
    return total


def _fetch_lunarcrush(store: Any, symbols: list[str], providers: Any) -> int:
    total = 0
    for metric in ("social_volume", "social_sentiment", "galaxy_score"):
        total += ingest_numeric(store, providers.lunarcrush, symbols, metric, provider_name="lunarcrush")
    return total


def _fetch_xai(store: Any, symbols: list[str], providers: Any) -> int:
    total = 0
    for metric in ("twitter_sentiment", "twitter_influencer_sentiment"):
        total += ingest_market_wide_numeric(
            store, providers.xai_twitter, source_metric=metric, stored_metric=metric, provider_name="xai",
        )
    return total


def _fetch_gdelt_tone(store: Any, symbols: list[str], providers: Any) -> int:
    return ingest_market_wide_numeric(
        store, providers.gdelt_tone, source_metric="gdelt_tone", stored_metric="gdelt_tone", provider_name="gdelt",
    )


def _fetch_dvol(store: Any, symbols: list[str], providers: Any) -> int:
    return ingest_numeric(store, providers.dvol, symbols, "dvol", provider_name="deribit")


def _fetch_llm_index(store: Any, symbols: list[str], providers: Any) -> int:
    """LLM qualitative→quantitative index scores — each market-wide under its semantic name. Key-gated (no LLM
    key → provider returns [] → 0, never an abort). The LLM only proposes the rubric-anchored number at ingest."""
    from cosmu.lab.indexes import INDEX_RUBRICS

    total = 0
    for metric in INDEX_RUBRICS:
        total += ingest_market_wide_numeric(
            store, providers.llm_index, source_metric=metric, stored_metric=metric, provider_name="llm_index",
        )
    return total


def _fetch_risk_on(store: Any, symbols: list[str], providers: Any) -> int:
    return ingest_market_wide_numeric(
        store, providers.polymarket, source_metric=providers.polymarket_token, stored_metric="pm_risk_on", provider_name="polymarket",
    )


def _fetch_venue_fees(store: Any, symbols: list[str], providers: Any) -> int:
    from cosmu.ingest.run import _ingest_venue_fees

    return _ingest_venue_fees(store, providers.venue_fees, symbols)


# --------------------------------------------------------------------------- the catalog


def managed_sources() -> dict[str, SourceSpec]:
    """The catalog, built fresh each call (no global mutable state). Keyed by the friendly source name the
    CLI accepts (`manage-data fetch funding`). Bars are handled by the manager's backfill path, not here."""
    specs: list[SourceSpec] = [
        SourceSpec("funding", "alt", ("funding_rate",), _fetch_numeric("funding_rate", "funding", "binance"), note="Binance USDⓈ-M funding (paginated history)."),
        SourceSpec("fear_greed", "alt", ("fear_greed",), _fetch_market_wide("fear_greed", "fear_greed", "feargreed", "alternative.me"), market_wide=True, per_symbol=False),
        SourceSpec("news", "alt", ("news_sentiment", "news_event_score"), _fetch_news, note="GDELT headlines → standardized sentiment + typed event score (LLM only at ingest)."),
        SourceSpec("macro", "alt", ("macro_regime", "vix_level", "fed_funds_rate", "dxy", "yield_curve_2s10s", "credit_spread", "vix_term_slope"), _fetch_fred, market_wide=True, per_symbol=False, note="FRED macro bundle (memoized shared series)."),
        SourceSpec("defi", "alt", ("defi_tvl",), _fetch_market_wide("defi_tvl", "defi_tvl", "defillama", "defillama"), market_wide=True, per_symbol=False),
        SourceSpec("pm_risk_on", "alt", ("pm_risk_on",), _fetch_risk_on, market_wide=True, per_symbol=False),
        SourceSpec("liquidation_cascade", "alt", ("liquidation_cascade",), lambda store, symbols, providers: ingest_liquidations(store, providers.liquidations, symbols)),
        SourceSpec("putcall", "alt", ("putcall_ratio",), _fetch_market_wide("putcall_ratio", "putcall_ratio", "putcall", "cboe"), market_wide=True, per_symbol=False),
        SourceSpec("open_interest", "alt", ("open_interest",), _fetch_numeric("open_interest", "open_interest", "binance")),
        SourceSpec("basis", "alt", ("perp_spot_basis",), _fetch_numeric("perp_spot_basis", "basis", "binance")),
        SourceSpec("netflow", "alt", ("exchange_netflow",), _fetch_numeric("exchange_netflow", "netflow", "binance")),
        SourceSpec("osint", "alt", ("osint_air_activity",), _fetch_market_wide("osint_air_activity", "osint_air_activity", "osint", "opensky"), market_wide=True, per_symbol=False),
        SourceSpec("polymarket_clob", "alt", ("pm_implied_prob", "pm_prob_velocity", "pm_book_depth"), _fetch_polymarket_clob, market_wide=True, per_symbol=False),
        SourceSpec("reddit", "alt", ("reddit_sentiment",), _fetch_market_wide("reddit_sentiment", "reddit_sentiment", "reddit", "reddit"), market_wide=True, per_symbol=False),
        SourceSpec("lunarcrush", "alt", ("social_volume", "social_sentiment", "galaxy_score"), _fetch_lunarcrush, note="Key-gated: empty without LUNARCRUSH_API_KEY."),
        SourceSpec("xai", "alt", ("twitter_sentiment", "twitter_influencer_sentiment"), _fetch_xai, market_wide=True, per_symbol=False, note="Key-gated: empty without XAI_API_KEY."),
        SourceSpec("venue_fees", "alt", ("venue_fees_maker", "venue_fees_taker"), _fetch_venue_fees, note="Per venue:symbol maker/taker snapshot."),
        SourceSpec(
            "multiasset", "alt",
            ("gold_xau", "silver_xag", "wti_crude", "spx_index", "ndx_index", "eurusd", "usdjpy"),
            _fetch_multiasset, market_wide=True, per_symbol=False,
            note="Free cross-asset daily price levels via Stooq/Yahoo (metals/commodities/equity-index/FX).",
        ),
        SourceSpec("gdelt_tone", "alt", ("gdelt_tone",), _fetch_gdelt_tone, market_wide=True, per_symbol=False, note="GDELT geopolitical news tone (keyless, EU-accessible, market-wide daily)."),
        SourceSpec("dvol", "alt", ("dvol",), _fetch_dvol, note="Deribit DVOL implied vol (keyless, EU-native, BTC/ETH only)."),
        SourceSpec("llm_index", "alt", tuple(_index_metrics()), _fetch_llm_index, market_wide=True, per_symbol=False, note="LLM qualitative→quantitative index scores (key-gated; market-wide)."),
    ]
    return {s.name: s for s in specs}


def _index_metrics() -> tuple[str, ...]:
    """The LLM index metric names, derived from the rubric registry (DRY — never a second hand-listing)."""
    from cosmu.lab.indexes import INDEX_RUBRICS

    return tuple(INDEX_RUBRICS)


def source_names() -> list[str]:
    return sorted(managed_sources())


def expected_alt_specs(symbols: list[str], *, venue: str = "binance") -> list[tuple[str, str, str]]:
    """Every (store_provider, store_symbol, metric) the coverage report should find, derived from the
    CANONICAL `_STORE_PROVIDER_OF` map (not a re-listing). Market-wide metrics live under the MARKET key;
    venue-fee metrics live under a `<venue>:<symbol>` composite key; everything else is per-symbol."""
    out: list[tuple[str, str, str]] = []
    for metric, provider in sorted(_STORE_PROVIDER_OF.items()):
        if metric in ("venue_fees_maker", "venue_fees_taker"):
            for sym in symbols:
                out.append((provider, f"{venue}:{sym}", metric))
        elif metric in _STORE_MARKET_WIDE:
            out.append((provider, "MARKET", metric))
        else:
            for sym in symbols:
                out.append((provider, sym, metric))
    return out


def expected_bar_specs(
    symbols: list[str],
    *,
    venues: tuple[str, ...] = DEFAULT_BAR_VENUES,
    timeframes: tuple[str, ...] = DEFAULT_BAR_TIMEFRAMES,
) -> list[tuple[str, str, str]]:
    """Every (venue, symbol, timeframe) bar series the report should find in the on-disk cache — now across
    MULTIPLE timeframes (the daily spine + intraday reads), so `verify` names a missing 4h/1h cache the same
    way it names a missing source."""
    return [(venue, sym, tf) for venue in venues for sym in symbols for tf in timeframes]


def catalog_metric_set() -> set[str]:
    """Union of every semantic metric the catalog's sources write — used by the consistency test to prove the
    catalog stays in lock-step with `_STORE_PROVIDER_OF`."""
    metrics: set[str] = set()
    for spec in managed_sources().values():
        metrics.update(spec.metrics)
    return metrics
