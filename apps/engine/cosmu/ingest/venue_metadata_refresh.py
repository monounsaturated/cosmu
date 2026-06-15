# intent: the per-venue MARKET-METADATA snapshot — last price + 24h (quote) volume per (venue, symbol), stored
# point-in-time so the app can LIST "what trades where, how deep, at what price" and later code can read it.
# Mirrors venue_fees_refresh: a standalone, idempotent (PIT append) Railway cron that writes provider
# 'venue_metadata' rows keyed '<venue>:<symbol>' under metrics venue_last_price / venue_volume_24h. Each venue
# is priced by its OWN DataAdapter (OKX candles for OKX, Kraken-Futures for the perps, Hyperliquid for the DEX,
# Binance for spot) — NOT one asset-class source — so the numbers are genuinely per-venue. invariants: READ-ONLY
# market data, offline-safe (a venue/symbol with no fetchable bar is skipped, never fabricated/zero-filled), no
# LLM, never moves money. Real fetches need live network → runs on Railway/local, not a cloud code agent.

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from cosmu.data.alt_join import resolve_alt_store
from cosmu.data.providers._types import AltDataPoint
from cosmu.spine.venue import default_catalog

VENUE_METADATA = "venue_metadata"
METRIC_PRICE = "venue_last_price"
METRIC_VOLUME = "venue_volume_24h"  # quote-currency notional (last close × bar volume) — comparable across venues


def _default_adapters(catalog: Any, settings: Any) -> dict[str, Any]:
    """Construct a DataAdapter per venue we can fetch per-venue bars for, seeded with that venue's catalogued
    symbols. Each adapter defaults to its LIVE provider (offline → empty bars → skipped). Lazily imported so this
    cron module stays light and a missing optional adapter never breaks the others."""
    by_venue: dict[str, list[str]] = {}
    for inst in catalog.instruments:
        by_venue.setdefault(inst.venue_id, []).append(inst.symbol)
    adapters: dict[str, Any] = {}
    if "binance" in by_venue:
        from cosmu.adapters.data.crypto import CryptoDataAdapter

        adapters["binance"] = CryptoDataAdapter(by_venue["binance"])
    if "okx" in by_venue:
        from cosmu.adapters.data.okx import OKXDataAdapter

        adapters["okx"] = OKXDataAdapter(by_venue["okx"])
    if "kraken_futures" in by_venue:
        from cosmu.adapters.data.kraken_futures import KrakenFuturesDataAdapter

        adapters["kraken_futures"] = KrakenFuturesDataAdapter(by_venue["kraken_futures"])
    if "hyperliquid" in by_venue:
        from cosmu.adapters.data.hyperliquid import HyperliquidDataAdapter

        adapters["hyperliquid"] = HyperliquidDataAdapter(by_venue["hyperliquid"])
    return adapters


def refresh_venue_metadata(
    store: Any,
    *,
    catalog: Any | None = None,
    adapters: Mapping[str, Any] | None = None,
    now: datetime | None = None,
    lookback_days: int = 5,
    alt_store: Any | None = None,
) -> dict:
    """Snapshot last price + 24h notional volume per (venue, symbol) into the venue_metadata PIT store, via each
    venue's OWN data adapter. Returns {snapshots, venues, instruments}. Idempotent + offline-safe."""
    catalog = catalog or default_catalog()
    now = now or datetime.now(tz=UTC)
    adapters = adapters if adapters is not None else _default_adapters(catalog, getattr(store, "settings", None))
    alt_store = alt_store if alt_store is not None else resolve_alt_store(getattr(store, "settings", None), store)
    start = now - timedelta(days=lookback_days)

    snapshots = 0
    instruments = 0
    venues_seen: set[str] = set()
    for venue_id, adapter in adapters.items():
        try:
            insts = adapter.universe(now)
        except Exception:  # noqa: BLE001 — a venue whose universe can't be read is skipped, never fabricated
            continue
        for inst in insts:
            try:
                bars = adapter.bars(inst.id, start, now, "1d")
            except Exception:  # noqa: BLE001 — offline / unknown symbol: skip this instrument, never zero-fill
                continue
            if not bars:
                continue
            last = bars[-1]
            try:
                close = float(last.close)
                base_vol = float(last.volume)
            except (TypeError, ValueError, AttributeError):
                continue
            instruments += 1
            key = f"{venue_id}:{inst.symbol}"
            quote_vol = close * base_vol  # notional, comparable across venues regardless of base-unit quoting
            for metric, value in ((METRIC_PRICE, close), (METRIC_VOLUME, quote_vol)):
                try:
                    alt_store.append(VENUE_METADATA, key, metric, [AltDataPoint(ts=now, available_at=now, value=value)])
                    snapshots += 1
                except Exception:  # noqa: BLE001 — one failed write never aborts the refresh
                    continue
            venues_seen.add(venue_id)

    try:
        store.append_event(
            actor="master", kind="venue_metadata_snapshot", ref_type="venue_metadata", ref_id="aggregate",
            payload={"snapshots": snapshots, "instruments": instruments, "venues": sorted(venues_seen)},
        )
    except Exception:  # noqa: BLE001 — the snapshot rows are the product; the audit event is best-effort
        pass
    return {"snapshots": snapshots, "instruments": instruments, "venues": sorted(venues_seen)}


def read_pit_venue_metadata(
    store: Any,
    venue_id: str,
    symbol: str,
    metric: str,  # METRIC_PRICE | METRIC_VOLUME
    as_of: datetime,
    *,
    fallback: float | None = None,
    alt_store: Any | None = None,
) -> float | None:
    """Read the latest PIT venue-metadata value (price or 24h volume) for a venue × symbol as of `as_of`. Resolves
    the SAME alt-store backend the writer used (resolve_alt_store: Parquet/PG/JSONL), so reader and writer never
    diverge across environments. Store key (provider='venue_metadata', symbol='<venue>:<symbol>', metric). None
    when unseen."""
    backend = alt_store if alt_store is not None else resolve_alt_store(getattr(store, "settings", None), store)
    try:
        points = backend.read_asof(VENUE_METADATA, f"{venue_id}:{symbol}", metric, as_of)
    except Exception:  # noqa: BLE001 — never crash a read over missing metadata
        return fallback
    return points[-1].value if points else fallback


def _main() -> int:
    from cosmu.config.settings import Settings
    from cosmu.knowledge.store import Store

    store = Store(Settings())
    result = refresh_venue_metadata(store)
    print(
        f"venue-metadata refreshed — {result['snapshots']} snapshots across "
        f"{result['instruments']} instruments, venues={result['venues']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
