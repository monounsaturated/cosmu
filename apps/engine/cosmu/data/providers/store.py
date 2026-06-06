from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ._types import AltDataPoint


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
                fh.write(json.dumps({"ts": p.ts.isoformat(), "available_at": p.available_at.isoformat(), "value": p.value}) + "\n")

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
        rows = [
            (provider, symbol, metric, p.ts.isoformat(), p.available_at.isoformat(), float(p.value), now)
            for p in points
        ]
        # Batched multi-row insert: one round-trip per ~1000 rows, not per row. Row-by-row over the
        # Supabase pooler made a 1.3M-row backfill take ~6h; this is the same data in minutes.
        with self.store.batch() as writer:
            writer.insert_many(
                "alt_data",
                ["provider", "symbol", "metric", "ts", "available_at", "value", "ingested_at"],
                rows,
            )

    def read_asof(self, provider: str, symbol: str, metric: str, as_of: datetime) -> list[AltDataPoint]:
        rows = self.store.rows(
            "SELECT DISTINCT ON (ts) ts, available_at, value FROM alt_data "
            "WHERE provider = ? AND symbol = ? AND metric = ? AND available_at <= ? "
            "ORDER BY ts, id DESC",
            (provider, symbol, metric, as_of.isoformat()),
        )
        return [AltDataPoint(ts=datetime.fromisoformat(r["ts"]), available_at=datetime.fromisoformat(r["available_at"]), value=float(r["value"])) for r in rows]

    def read_all(self, provider: str, symbol: str, metric: str) -> list[AltDataPoint]:
        """Full revision history (see AltDataStore.read_all) — the per-bar as-of join collapses it correctly."""
        rows = self.store.rows(
            "SELECT ts, available_at, value FROM alt_data WHERE provider = ? AND symbol = ? AND metric = ? ORDER BY available_at, id",
            (provider, symbol, metric),
        )
        return [AltDataPoint(ts=datetime.fromisoformat(r["ts"]), available_at=datetime.fromisoformat(r["available_at"]), value=float(r["value"])) for r in rows]


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
}
_STORE_MARKET_WIDE = frozenset({
    "fear_greed", "pm_risk_on", "macro_regime", "putcall_ratio", "vix_level", "fed_funds_rate",
    "defi_tvl", "dxy", "yield_curve_2s10s", "credit_spread", "vix_term_slope",
    "osint_air_activity", "pm_implied_prob", "pm_prob_velocity", "pm_book_depth",
    "reddit_sentiment", "twitter_sentiment", "twitter_influencer_sentiment",
    "gdelt_tone", "reg_risk_crypto", "risk_on_off",
    "gold_xau", "silver_xag", "wti_crude", "spx_index", "ndx_index", "eurusd", "usdjpy",
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
            return []
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
        return points[-limit:]
