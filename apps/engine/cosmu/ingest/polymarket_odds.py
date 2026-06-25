# intent: per-MARKET Polymarket YES-odds ingest → the append-only, point-in-time alt-data store, keyed by
# conditionId — the data foundation that lets a prediction StrategySpec backtest each market on its OWN odds
# series. inputs: the most-liquid OPEN polymarket conditionIds from universe_pairs + the per-market CLOB source
# (PerMarketOddsSource); outputs: alt_data rows (provider="polymarket", symbol=conditionId, metric="odds") the
# PredictionDataAdapter reads back. invariants: append-only + point-in-time (re-runs never rewrite the view),
# idempotent via append_dedup (ts-keyed — odds buckets are revision-free midpoints), per-market failure is
# isolated (one dead resolution/fetch is 0 rows for that market, never aborts the batch), offline-testable via
# an injected source. This is the per-conditionId analogue of the MACRO aggregates in ingest/run.py (which stay
# under symbol="MARKET"); it does NOT touch them.

from __future__ import annotations

import logging
from dataclasses import dataclass

from cosmu.data.altdata import AltDataStore
from cosmu.data.sources.polymarket import PerMarketOddsSource
from cosmu.ingest.pipeline import append_dedup

logger = logging.getLogger("cosmu.ingest.polymarket_odds")

# The alt-data shape the PredictionDataAdapter reads back: it calls
# read_asof(provider="polymarket", symbol=conditionId, metric="odds", as_of).
_PROVIDER = "polymarket"
_METRIC = "odds"

# Hourly variant: the SAME per-market YES-odds, but at fidelity=60 (hourly buckets). Stored under a DISTINCT
# metric ("odds_60") so the two cadences never co-mingle in one (provider,symbol,metric) series — mixing daily
# and hourly ts in one keyspace would corrupt the ts-keyed dedup and the adapter's bar read. The daily series is
# correctly refused by the per-cell min-trades Gate (~1 trade/market); the hourly series is ~24× the rows, which
# lets a cell clear MIN_TRADES/_BRUT_MIN_TRADES HONESTLY (the fix is denser bars, never a looser Gate).
_METRIC_HOURLY = "odds_60"

# CLOB `fidelity` is the bucket size in MINUTES. 1440 = daily (the macro-feature cadence), 60 = hourly.
_FIDELITY_DAILY = 1440
_FIDELITY_HOURLY = 60

# Default breadth: the top ~30 most-liquid open polymarket markets. Matches the venue-universe HL/PERP width —
# enough to test the prediction lane wide without hammering the public CLOB. Override per call.
DEFAULT_MAX_MARKETS = 30


@dataclass(frozen=True)
class PerMarketIngestResult:
    """Per-conditionId outcome: how many NEW odds points landed (0 on an idempotent re-run / unfetchable market)
    and the total the source returned for the window."""

    condition_id: str
    written: int
    total: int


def top_liquid_condition_ids(store: object, *, max_markets: int = DEFAULT_MAX_MARKETS) -> list[str]:
    """The conditionIds of the most-liquid OPEN polymarket markets, by `liquidity_usd_24h` desc (book depth USD
    for a prediction market). `active=1` only — a resolved/closed market has no live odds to test. The
    universe_pairs `symbol` for a polymarket row IS the conditionId (see data/venue_universe.fetch_polymarket)."""
    rows = store.rows(
        "SELECT symbol FROM universe_pairs WHERE venue = ? AND asset_class = ? AND active = 1 "
        "ORDER BY liquidity_usd_24h DESC, symbol LIMIT ?",  # column is NOT NULL → no NULLS-LAST (SQLite-safe)
        ("polymarket", "prediction", int(max_markets)),
    )
    return [r["symbol"] for r in rows if r.get("symbol")]


def ingest_per_market_odds(
    alt_store: AltDataStore,
    store: object,
    *,
    source: PerMarketOddsSource | None = None,
    max_markets: int = DEFAULT_MAX_MARKETS,
    fidelity: int = _FIDELITY_DAILY,
    metric: str = _METRIC,
    limit: int = 100_000,
) -> list[PerMarketIngestResult]:
    """Ingest the per-MARKET YES-odds series for the top-`max_markets` liquid open polymarket conditionIds into
    `alt_store`, keyed by conditionId under (provider="polymarket", metric). Idempotent (append_dedup, ts-keyed).
    `store` is the knowledge Store that backs universe_pairs (the conditionId source). `fidelity` is the CLOB
    bucket size in MINUTES (1440 = daily → metric="odds"; 60 = hourly → metric="odds_60"); the caller pairs the
    cadence with the matching metric so the two never co-mingle in one series. Per-market failure (unresolvable
    token, dead CLOB fetch, empty history) is isolated — that market contributes 0 rows and the batch continues.
    Returns one result per conditionId attempted."""
    src = source or PerMarketOddsSource()
    condition_ids = top_liquid_condition_ids(store, max_markets=max_markets)
    results: list[PerMarketIngestResult] = []
    for cid in condition_ids:
        try:
            points = src.fetch_odds(cid, fidelity=fidelity, limit=limit)
        except Exception:  # noqa: BLE001 — one market's failure never aborts the batch
            logger.warning("polymarket per-market odds fetch failed for %s", cid, exc_info=True)
            points = []
        written = append_dedup(alt_store, _PROVIDER, cid, metric, points)
        results.append(PerMarketIngestResult(condition_id=cid, written=written, total=len(points)))
    return results


def ingest_per_market_odds_hourly(
    alt_store: AltDataStore,
    store: object,
    *,
    source: PerMarketOddsSource | None = None,
    max_markets: int = DEFAULT_MAX_MARKETS,
    limit: int = 100_000,
) -> list[PerMarketIngestResult]:
    """The HOURLY (fidelity=60) per-market odds variant, stored under metric="odds_60". Hourly is ~24× the daily
    rows, so a per-market cell can clear the per-cell min-trades Gate (MIN_TRADES/_BRUT_MIN_TRADES) honestly —
    daily odds (~1 trade/market) is correctly refused. Same idempotent, per-market-isolated contract as the daily
    `ingest_per_market_odds`; differs only in the cadence + the destination metric."""
    return ingest_per_market_odds(
        alt_store, store, source=source, max_markets=max_markets,
        fidelity=_FIDELITY_HOURLY, metric=_METRIC_HOURLY, limit=limit,
    )


__all__ = [
    "DEFAULT_MAX_MARKETS",
    "PerMarketIngestResult",
    "ingest_per_market_odds",
    "ingest_per_market_odds_hourly",
    "top_liquid_condition_ids",
]
