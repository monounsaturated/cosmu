from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from cosmu.data._iso import iso_utc

from ._types import AltDataPoint

logger = logging.getLogger("cosmu.data.store")


class UnknownAltMetricError(KeyError):
    """A consumer asked StoreBackedAltProvider for a metric with NO route in `_provider_of`.

    This is ALWAYS a wiring bug (a typo or a renamed/unregistered metric), never a data gap — the old
    behaviour of silently returning [] turned such bugs into invisible no-ops (the P0 risk_on/pm_risk_on
    name split: the gate read "risk_on", routing only knew "pm_risk_on", so the live cross-asset feature was
    silently stripped from every Gate run with no error and no failing test). Raising turns that whole
    silent-miss class into a loud, immediate failure. A KNOWN metric with no stored data still returns []."""


class AltDataStore:
    """Append-only, point-in-time snapshot store. One JSONL file per provider/symbol/metric; each
    append is a new immutable line. Reads filter to `available_at <= as_of`, so a later vendor
    revision can never rewrite what you would have known earlier."""

    def __init__(self, root: Path | str = ".cosmu/altdata") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, provider: str, symbol: str, metric: str) -> Path:
        safe = f"{provider}_{symbol}_{metric}".replace("/", "")
        return self.root / f"{safe}.jsonl"

    def append(self, provider: str, symbol: str, metric: str, points: list[AltDataPoint]) -> None:
        path = self._path(provider, symbol, metric)
        with path.open("a") as fh:
            for p in points:
                fh.write(json.dumps({"ts": iso_utc(p.ts), "available_at": iso_utc(p.available_at), "value": p.value}) + "\n")

    def read_asof(self, provider: str, symbol: str, metric: str, as_of: datetime) -> list[AltDataPoint]:
        path = self._path(provider, symbol, metric)
        if not path.exists():
            return []
        # Last write wins per ts among rows already available by `as_of` (revisions append, newest used).
        latest: dict[str, AltDataPoint] = {}
        for line in path.read_text().splitlines():
            if not line:
                continue
            row = json.loads(line)
            available = datetime.fromisoformat(row["available_at"])
            if available > as_of:
                continue
            latest[row["ts"]] = AltDataPoint(ts=datetime.fromisoformat(row["ts"]), available_at=available, value=float(row["value"]))
        return sorted(latest.values(), key=lambda p: p.ts)

    def read_all(self, provider: str, symbol: str, metric: str) -> list[AltDataPoint]:
        """Every appended point, every revision, sorted by availability — the full point-in-time history.
        A backtest's per-bar as-of join (it keeps the latest value with available_at <= bar time) needs the
        whole revision trail, so this does NOT collapse revisions the way read_asof does."""
        path = self._path(provider, symbol, metric)
        if not path.exists():
            return []
        out: list[AltDataPoint] = []
        for line in path.read_text().splitlines():
            if not line:
                continue
            row = json.loads(line)
            out.append(AltDataPoint(ts=datetime.fromisoformat(row["ts"]), available_at=datetime.fromisoformat(row["available_at"]), value=float(row["value"])))
        return sorted(out, key=lambda p: (p.available_at, p.ts))


class PgAltDataStore:
    """Central, append-only, point-in-time alt-data store backed by the Postgres `alt_data` table —
    the production replacement for the JSONL `AltDataStore`. Drop-in: same append/read_asof interface,
    so the ingestion pipeline doesn't change. Reads return the latest-revised value per ts that was
    available by `as_of`, so vendor revisions never rewrite history."""

    def __init__(self, store: Any) -> None:  # store: knowledge.store.Store (avoid import cycle)
        self.store = store

    def append(self, provider: str, symbol: str, metric: str, points: list[AltDataPoint]) -> None:
        from cosmu.knowledge.store import utcnow

        if not points:
            return
        now = utcnow()
        avails = [iso_utc(p.available_at) for p in points]
        rows = [
            (provider, symbol, metric, iso_utc(p.ts), avail, float(p.value), now)
            for p, avail in zip(points, avails, strict=True)
        ]
        # Batched multi-row insert: one round-trip per ~1000 rows, not per row. Row-by-row over the
        # Supabase pooler made a 1.3M-row backfill take ~6h; this is the same data in minutes.
        with self.store.batch() as writer:
            # ON CONFLICT DO NOTHING against uq_alt_data_pit (provider,symbol,metric,ts,available_at): a repeat
            # or raced append of an already-stored window is a no-op, never a raise — the DB-level idempotency
            # the 15-min ingest cron relies on. (The scheduled path already dedups upstream, so n_rows below
            # equals the rows actually inserted in normal operation; the summary is rebuilt from truth during
            # compaction, so a rare raced over-count self-heals.)
            writer.insert_many(
                "alt_data",
                ["provider", "symbol", "metric", "ts", "available_at", "value", "ingested_at"],
                rows,
                ignore_duplicates=True,
            )
            # Roll this just-written batch into the per-(provider, metric) summary IN THE SAME transaction —
            # an INCREMENTAL upsert (n_rows += len(points), latest_available_at = max), never a full re-aggregate
            # of alt_data. The UI's freshness reads (/intelligence, /scores) hit that tiny table instead of a
            # GROUP BY over the ~17M-row alt_data. Best-effort: a summary failure never aborts the ingest.
            from cosmu.ingest.alt_summary import record_ingest

            # The VALUE of the newest-available row in this batch (PIT: newest available_at wins) — so the
            # summary can serve the Mind's "latest value per metric" without a JOIN over the ~17M-row alt_data.
            latest_pt = max(points, key=lambda p: p.available_at)
            record_ingest(
                writer, provider, metric,
                n_rows=len(points), latest_available_at=max(avails),
                latest_value=str(float(latest_pt.value)),
            )

    def read_asof(self, provider: str, symbol: str, metric: str, as_of: datetime) -> list[AltDataPoint]:
        # Latest-revision row (LATEST available_at) per ts among rows available by `as_of`, ordered by ts. Uses a
        # window function instead of Postgres-only `DISTINCT ON (ts)` so it runs IDENTICALLY on SQLite — the old
        # `DISTINCT ON` errored on SQLite, which made read_pit_fee silently return its fallback for every local/
        # test fee read. Ordering by available_at (NOT id) is the true PIT revision winner and is what makes the
        # Parquet/DuckLake read byte-identical; uq_alt_data_pit guarantees available_at is unique per (series,ts),
        # so no secondary tiebreak is needed. as_of is canonicalized so the string<= cut matches the stored form.
        rows = self.store.rows(
            "SELECT ts, available_at, value FROM ("
            "  SELECT ts, available_at, value, row_number() OVER (PARTITION BY ts ORDER BY available_at DESC) AS rn "
            "  FROM alt_data WHERE provider = ? AND symbol = ? AND metric = ? AND available_at <= ?"
            ") t WHERE rn = 1 ORDER BY ts",
            (provider, symbol, metric, iso_utc(as_of)),
        )
        return [AltDataPoint(ts=datetime.fromisoformat(r["ts"]), available_at=datetime.fromisoformat(r["available_at"]), value=float(r["value"])) for r in rows]

    def read_all(self, provider: str, symbol: str, metric: str) -> list[AltDataPoint]:
        """Full revision history (see AltDataStore.read_all) — the per-bar as-of join collapses it correctly."""
        rows = self.store.rows(
            "SELECT ts, available_at, value FROM alt_data WHERE provider = ? AND symbol = ? AND metric = ? ORDER BY available_at, ts",
            (provider, symbol, metric),
        )
        return [AltDataPoint(ts=datetime.fromisoformat(r["ts"]), available_at=datetime.fromisoformat(r["available_at"]), value=float(r["value"])) for r in rows]


def hot_alt_store(settings: Any, store: Any = None) -> Any:
    """The SINGLE factory for the HOT (write + money/UI) alt-data store: a Postgres URL → PgAltDataStore over the
    knowledge Store, else the JSONL AltDataStore. Ingest, the research loop, and resolve_alt_store's non-cold
    branch ALL route through this, so the choice can never diverge again (it did: two ingest paths hardcoded PG
    while the read resolver could pick the lake). Writes ALWAYS land in PG (the hot tier) — this NEVER returns the
    cold Parquet/lake store; the cold tier is a read-only research path chosen by resolve_alt_store."""
    url = getattr(settings, "database_url", "") or ""
    if url.startswith(("postgres://", "postgresql://")):
        if store is None:
            from cosmu.knowledge.store import Store

            store = Store(settings)
        return PgAltDataStore(store)
    return AltDataStore()


# Default routing: the gate asks for a SEMANTIC metric name; the store keyed it under the ingesting
# provider. Market-wide metrics live under the "MARKET" symbol (one series for the whole tape).
_STORE_PROVIDER_OF = {
    "venue_fees_maker": "venue_fees",
    "venue_fees_taker": "venue_fees",
    "funding_rate": "binance",
    "fear_greed": "alternative.me",
    "news_sentiment": "news",
    "news_event_score": "news",  # typed event/news scorer: sign × magnitude, stored per-symbol
    "pm_risk_on": "polymarket",
    "macro_regime": "fred",
    "liquidation_cascade": "coinglass",
    "putcall_ratio": "cboe",
    "vix_level": "fred",
    "fed_funds_rate": "fred",
    "defi_tvl": "defillama",
    "open_interest": "binance",
    "perp_spot_basis": "binance",
    "exchange_netflow": "binance",
    "dxy": "fred",
    "yield_curve_2s10s": "fred",
    "credit_spread": "fred",
    "vix_term_slope": "fred",
    "osint_air_activity": "opensky",
    "pm_implied_prob": "polymarket",
    "pm_prob_velocity": "polymarket",
    "pm_book_depth": "polymarket",
    "reddit_sentiment": "reddit",
    "social_volume": "lunarcrush",
    "social_sentiment": "lunarcrush",
    "galaxy_score": "lunarcrush",
    # The remaining LunarCrush coin time-series fields hoarded alongside the three above
    # (scripts/lunarcrush_max_extract.py _COIN_FIELDS stores all twelve per coin). Routing them here makes
    # them readable by the gate's per-bar as-of join. tier1, low-confidence.
    "alt_rank": "lunarcrush",
    "market_cap_usd": "lunarcrush",
    "volume_24h_usd": "lunarcrush",
    "price_usd": "lunarcrush",
    # The final five LunarCrush coin fields the bulk grab hoards (scripts/lunarcrush_max_extract.py
    # _COIN_FIELDS) — banked-but-unwired until now. Per-symbol (NOT market-wide); routing them here makes
    # them readable by the gate's per-bar as-of join. tier1, low-confidence.
    "social_dominance": "lunarcrush",
    "market_dominance": "lunarcrush",
    "contributors_active": "lunarcrush",
    "posts_active": "lunarcrush",
    "spam": "lunarcrush",
    "twitter_sentiment": "xai",
    "twitter_influencer_sentiment": "xai",
    # Geopolitical news tone (GDELT, keyless, market-wide) and crypto options IV (Deribit, keyless, per-symbol).
    "gdelt_tone": "gdelt",
    "dvol": "deribit",
    # LLM qualitative→quantitative index scores (market-wide; the LLM standardizes text only, never the money path).
    "reg_risk_crypto": "llm_index",
    "risk_on_off": "llm_index",
    # Cross-asset daily price levels (free, no key) via Stooq/Yahoo — metals, commodities, equity indexes, FX.
    "gold_xau": "stooq",
    "silver_xag": "stooq",
    "wti_crude": "stooq",
    "spx_index": "stooq",
    "ndx_index": "stooq",
    "eurusd": "stooq",
    "usdjpy": "stooq",
    # --- 10 new alt-data sources (PIT-honest; non-causal ones flagged in feature_registry priors) ---
    # Extended FRED macro (ALFRED initial-release vintages — available_at == realtime_start, no look-ahead).
    "nfci": "fred",
    "initial_claims": "fred",
    # Wikipedia pageviews (free, no key, immutable counts; per-symbol via entity map; available_at = T+1).
    "wiki_pageviews": "wikimedia",
    "wiki_pageviews_log": "wikimedia",
    "wiki_pageviews_zscore": "wikimedia",
    # Reddit post/comment volume (key-gated: REDDIT_CLIENT_ID/SECRET → [] offline; market-wide; available_at = day+1).
    "reddit_post_volume": "reddit_volume",
    "reddit_comment_volume": "reddit_volume",
    # CryptoPanic news-vote counts (key-gated: CRYPTOPANIC_API_KEY → [] offline; per-symbol; 24h window).
    "cryptopanic_bullish_votes": "cryptopanic",
    "cryptopanic_bearish_votes": "cryptopanic",
    # RSS headline count (free, no key, LLM-free; market-wide; available_at = fetch time).
    "rss_news_count": "rss",
    # Google Trends search interest (REVISION HAZARD — rescales history; market-wide; available_at = fetch time).
    "gtrends_search_interest": "gtrends",
    # OpenSky daily flight count (free OSINT, thin history; market-wide; available_at = day+1).
    "opensky_daily_flights": "opensky_daily",
    # Open-Meteo weather hub-stress (NON-CAUSAL control; market-wide; available_at = obs+1).
    "weather_hub_stress": "openmeteo",
    # Deterministic astro ephemeris (NON-CAUSAL controls; market-wide; available_at = day midnight UTC).
    "astro_lunar_phase": "astro",
    "astro_sun_longitude": "astro",
    "astro_jupiter_longitude": "astro",
    "astro_saturn_longitude": "astro",
    "astro_sun_jupiter_aspect": "astro",
    # Exotic ORTHOGONALITY CONTROLS (USGS earthquakes + NOAA Kp — non-causal; market-wide; Gate must kill them).
    "usgs_earthquake_count": "usgs",
    "usgs_max_magnitude": "usgs",
    "noaa_kp_index": "noaa",
    # --- TOOL-WAVE-A: 4 more free, no-key sources (PIT-honest; daily aggregates knowable T+1) ---
    # DefiLlama total stablecoin market cap (free, market-wide). The legacy defi_tvl keeps its own metric
    # under the SAME "defillama" provider bucket — this only adds the orthogonal stablecoin_mcap metric.
    "stablecoin_mcap": "defillama",
    # CoinGecko (free public tier): per-coin mcap + 24h volume + market-wide BTC dominance.
    "cg_market_cap": "coingecko",
    "cg_total_volume": "coingecko",
    "cg_btc_dominance": "coingecko",
    # blockchain.com BTC on-chain fundamentals (free, market-wide — they describe the whole BTC network).
    "btc_hashrate": "blockchain.com",
    "btc_tx_count": "blockchain.com",
    "btc_mempool_size": "blockchain.com",
    "btc_active_addresses": "blockchain.com",
    # GDELT daily news-VOLUME counts (free, LLM-free; PER-SYMBOL via topic map; distinct from gdelt_tone).
    "gdelt_news_volume": "gdelt_counts",
    # --- TOOL-WAVE-C: 2 more free, no-key market-wide FLOW sources (PIT-honest; degrade to [] offline) ---
    # FRED keyless macro-liquidity (WALCL + net-of-TGA). Stored under the SAME "fred" provider bucket as the
    # other FRED macro metrics — these add the system-liquidity LEVEL/flow, distinct metrics, knowable ~T+8.
    "fed_balance_sheet_usd": "fred",
    "net_liquidity_usd": "fred",
    # DefiLlama stablecoin FLOW (day-over-day mcap CHANGE) + ETH chain-share. Stored under the SAME "defillama"
    # provider bucket as defi_tvl / stablecoin_mcap — the orthogonal DERIVATIVE of the level, knowable T+1.
    "stablecoin_net_flow_usd": "defillama",
    "stablecoin_eth_share": "defillama",
}
_STORE_MARKET_WIDE = frozenset({
    "fear_greed", "pm_risk_on", "macro_regime", "putcall_ratio", "vix_level", "fed_funds_rate",
    "defi_tvl", "dxy", "yield_curve_2s10s", "credit_spread", "vix_term_slope",
    "osint_air_activity", "pm_implied_prob", "pm_prob_velocity", "pm_book_depth",
    "reddit_sentiment", "twitter_sentiment", "twitter_influencer_sentiment",
    "gdelt_tone", "reg_risk_crypto", "risk_on_off",
    "gold_xau", "silver_xag", "wti_crude", "spx_index", "ndx_index", "eurusd", "usdjpy",
    # New market-wide alt sources (the per-symbol ones — wiki_pageviews*, cryptopanic_* — are NOT here).
    "nfci", "initial_claims",
    "reddit_post_volume", "reddit_comment_volume",
    "rss_news_count", "gtrends_search_interest", "opensky_daily_flights", "weather_hub_stress",
    "astro_lunar_phase", "astro_sun_longitude", "astro_jupiter_longitude",
    "astro_saturn_longitude", "astro_sun_jupiter_aspect",
    "usgs_earthquake_count", "usgs_max_magnitude", "noaa_kp_index",
    # TOOL-WAVE-A market-wide metrics. The per-symbol ones — cg_market_cap, cg_total_volume,
    # gdelt_news_volume — are deliberately NOT here (they live under the symbol key, like wiki_pageviews).
    "stablecoin_mcap", "cg_btc_dominance",
    "btc_hashrate", "btc_tx_count", "btc_mempool_size", "btc_active_addresses",
    # TOOL-WAVE-C market-wide FLOW metrics — system liquidity + stablecoin flow describe the whole tape.
    "fed_balance_sheet_usd", "net_liquidity_usd",
    "stablecoin_net_flow_usd", "stablecoin_eth_share",
})
# Registry name → stored metric name, for features renamed after their first ingest.
# StoreBackedAltProvider tries the registry name first; if the store returns nothing it falls back here
# so data written under the old name is still accessible until re-ingested under the canonical name.
_STORE_METRIC_ALIAS: dict[str, str] = {
    "pm_risk_on": "risk_on",
    "liquidation_cascade": "liquidations",
}

# Semantic-REQUEST alias: a metric NAME a consumer asks for that is not itself a canonical stored series, but
# is served by an existing one. Unlike _STORE_METRIC_ALIAS (a read-time fallback on the SAME canonical metric
# for legacy renames), this rewrites the request to the canonical metric BEFORE provider/market-wide routing —
# so it never enters _STORE_PROVIDER_OF / _STORE_MARKET_WIDE and the catalog + coverage report stay derived
# purely from the canonical stored names (no phantom coverage rows, no lock-step break).
#
# The live cross-asset gate REQUESTS the prediction-market transfer feature under the semantic name "risk_on"
# (gate.py: fetch_series("MARKET","risk_on")), but ingest banks it under the canonical "pm_risk_on". Without
# this rewrite fetch_series("MARKET","risk_on") returned [] → the gate's risk-on feature was silently EMPTY on
# real data (the synthetic fixture hid it by supplying "risk_on" directly). Resolving it to pm_risk_on here
# inherits pm_risk_on's provider + market-wide routing, so the feature is actually populated on the live path.
_STORE_REQUEST_ALIAS: dict[str, str] = {
    "risk_on": "pm_risk_on",
}

# Providers whose per-symbol series may be stored under the BASE-ASSET form (e.g. "BTC") rather than the
# venue pair the backtest keys by ("BTCUSDT"). The bulk LunarCrush hoard (scripts/lunarcrush_max_extract.py)
# keys each coin by its base symbol (the API entity id), while the scheduled ingest path keys by the full
# pair. fetch_series tries the EXACT symbol first and only falls back to the base-asset form when nothing was
# found — so an exact match always wins and no series is ever silently re-routed. Conservative + additive.
_STORE_BASE_ASSET_PROVIDERS = frozenset({"lunarcrush"})


def _strip_quote(symbol: str) -> str | None:
    """Base-asset form of a venue pair (BTCUSDT -> BTC), or None if `symbol` is not a recognised quote pair."""
    for quote in ("USDT", "USDC", "USD", "BUSD"):
        if symbol.endswith(quote) and len(symbol) > len(quote):
            return symbol[: -len(quote)]
    return None


class StoreBackedAltProvider:
    """Adapts the append-only point-in-time store (AltDataStore / PgAltDataStore) into the AltDataProvider
    seam the gate consumes — so the SAME `evaluate_*` code runs on real ingested data, not just fixtures.
    Returns the full revision history (read_all); the gate's per-bar as-of join does the point-in-time
    selection, so no future revision can leak into a past bar."""

    def __init__(self, store: Any, *, provider_of: dict[str, str] | None = None, market_wide: frozenset[str] = _STORE_MARKET_WIDE) -> None:
        self._store = store
        self._provider_of = provider_of or dict(_STORE_PROVIDER_OF)
        self._market_wide = market_wide

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        # Resolve a semantic-request alias (e.g. the gate's "risk_on") to its canonical stored metric
        # ("pm_risk_on") BEFORE routing, so it inherits the canonical metric's provider + market-wide rules.
        metric = _STORE_REQUEST_ALIAS.get(metric, metric)
        provider = self._provider_of.get(metric)
        if provider is None:
            # No route for this metric — ALWAYS a wiring bug (typo / unregistered / renamed metric), never a
            # data gap. Fail LOUD instead of silently returning [] (the silent-miss class that hid the P0
            # risk_on/pm_risk_on split). A KNOWN metric with no stored data still falls through to [] below.
            logger.warning(
                "StoreBackedAltProvider: no store route for metric %r (symbol %r) — unknown/unrouted metric, raising",
                metric, symbol,
            )
            raise UnknownAltMetricError(
                f"no store route for metric {metric!r}: it is absent from _provider_of. This is a wiring bug "
                f"(typo, unregistered, or renamed metric), not a data gap. Add it to _STORE_PROVIDER_OF (and "
                f"_STORE_MARKET_WIDE if market-wide) or fix the request name. Known routes: "
                f"{sorted(self._provider_of)}"
            )
        key = "MARKET" if metric in self._market_wide else symbol
        points = self._store.read_all(provider, key, metric)
        if not points:
            alias = _STORE_METRIC_ALIAS.get(metric)
            if alias:
                points = self._store.read_all(provider, key, alias)
        # Base-asset fallback: a provider hoarded by coin id (e.g. LunarCrush "BTC") is read by the backtest
        # under the venue pair ("BTCUSDT"). Only fires when the exact key found nothing, so an exact match
        # always wins and the point-in-time semantics are unchanged (we just look under the other key form).
        if not points and provider in _STORE_BASE_ASSET_PROVIDERS and key != "MARKET":
            base = _strip_quote(key)
            if base:
                points = self._store.read_all(provider, base, metric)
                if not points:
                    alias = _STORE_METRIC_ALIAS.get(metric)
                    if alias:
                        points = self._store.read_all(provider, base, alias)
        # Collapse exact re-appended duplicates (same ts AND available_at; last write wins, matching
        # read_asof's id-DESC rule) BEFORE the trailing slice — the slice must count DISTINCT points, or a
        # store that accreted duplicate copies of a window (the pre-dedup scheduled ingest did this every
        # pass) silently shrinks the history the gate sees to a fraction of what it asked for.
        if points:
            by_key = {(p.ts, p.available_at): p for p in points}
            if len(by_key) != len(points):
                points = list(by_key.values())
        return points[-limit:]
