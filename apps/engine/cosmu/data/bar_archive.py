# intent: the R2 PRICE ARCHIVE — persist fetched OHLCV bars to Cloudflare R2, keyed by venue/symbol/timeframe, so
# the SHALLOW keyless windows (Kraken REST serves only ~720 bars, Bybit/Binance a single ~1000-bar page) ACCUMULATE
# into DEEP history over time, for free. Every screen run fetches the latest window; archiving it UNION-MERGES into
# the R2 object so the stored series only ever GROWS — exactly the never-shrink discipline the on-disk bar cache and
# the alt_data → R2 age-out already enforce, applied to bars at the object-store layer.
#
# Two halves, both REUSING the existing R2 + bar serialization patterns (data/pg_backup._r2_client; market._merge_bars
# / _bars_to_rows / _bar_from_json):
#   - WRITE: archive_bars(venue, symbol, timeframe, bars) idempotently UNION-MERGES `bars` into the R2 object (read,
#     merge deduped-on-ts, write back) — never shrinks. `sync_local_cache(...)` is the standalone job that pushes the
#     whole local `.cosmu/market_data/<venue>/` cache to R2 in one pass (run LOCAL or on Modal; `python -m
#     cosmu.data.bar_archive sync`).
#   - READ: load_archived_bars(venue, symbol, timeframe, live=...) UNION-MERGES the deep R2 history with the live
#     ~720-bar window so a caller sees the full accumulated series (live bars win on a ts collision — a freshly closed
#     bar repairs any row archived mid-candle, the same _merge_bars contract).
#
# invariants: R2 creds ABSENT → a loud no-op (write returns the input unchanged; read returns the live window
# unchanged) — keyless degradation, identical to pg_backup / the cold tier; NEVER crashes a caller. READ-ONLY on the
# local cache (the sync job only uploads). Idempotent: archiving the same bars twice is a no-op merge; the union can
# only ADD or REPAIR rows, never remove one. Deterministic for fixed inputs; ZERO LLM.
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from cosmu.config.settings import Settings, get_settings
from cosmu.data.market import Bar, _bar_from_json, _bars_to_rows, _merge_bars

logger = logging.getLogger("cosmu.data.bar_archive")

# The R2 object-key prefix for the bar archive. Sibling to backups/pg and the alt lake prefixes; one object per
# (venue, symbol, timeframe) so a venue's deep history is a single addressable, union-merged series.
_PREFIX = "bars"

# The local on-disk bar cache root (each provider writes `.cosmu/market_data/<venue>/<symbol>_<tf>.json`). The sync
# job mirrors this whole tree to R2.
_LOCAL_CACHE_ROOT = ".cosmu/market_data"


def _r2_ready(settings: Settings) -> bool:
    """True iff all four R2 creds are present — else the archive is a keyless no-op (like pg_backup / the cold tier)."""
    return all(
        (settings.r2_account_id, settings.r2_access_key_id, settings.r2_secret_access_key, settings.r2_bucket)
    )


def _r2_client(settings: Settings):  # noqa: ANN202 — boto3 client; lazy import keeps boto3 out of the base deps
    """The R2 S3-compatible client — the SAME construction pg_backup / the cold tier use (one auth path)."""
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",
    )


def archive_key(venue: str, symbol: str, timeframe: str) -> str:
    """The R2 object key for one (venue, symbol, timeframe) series: 'bars/<venue>/<SYMBOL>_<tf>.json'. The '/' in a
    symbol is stripped (XBT/USD → XBTUSD) so the key mirrors the local cache filename and never nests a stray path
    segment — exactly the on-disk cache's `f"{symbol}_{timeframe}".replace("/", "")` rule."""
    safe = f"{symbol}_{timeframe}".replace("/", "")
    return f"{_PREFIX}/{venue}/{safe}.json"


def _read_object_bars(s3: Any, bucket: str, key: str) -> list[Bar]:
    """Read + parse the bars stored at `key`, or [] when the object is absent/unreadable (a first archive, or a
    transient read error → treat as empty so the merge below simply writes the fresh window). Never raises."""
    try:
        body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    except Exception:  # noqa: BLE001 — NoSuchKey on a first write, or a transient read error → empty (degrade)
        return []
    try:
        rows = json.loads(body.decode("utf-8"))
        return [_bar_from_json(r) for r in rows]
    except Exception:  # noqa: BLE001 — a corrupt/half-written object must not poison the merge → treat as empty
        logger.warning("bar_archive: unreadable object r2://%s/%s — treating as empty", bucket, key)
        return []


def _write_object_bars(s3: Any, bucket: str, key: str, bars: list[Bar]) -> None:
    """Serialize `bars` to the on-disk cache row shape (ts in ms; OHLCV as strings) and PUT to `key`."""
    payload = json.dumps(_bars_to_rows(bars), separators=(",", ":")).encode("utf-8")
    s3.put_object(Bucket=bucket, Key=key, Body=payload, ContentType="application/json")


def archive_bars(
    venue: str,
    symbol: str,
    timeframe: str,
    bars: list[Bar],
    *,
    settings: Settings | None = None,
    s3: Any | None = None,
) -> list[Bar]:
    """Idempotently UNION-MERGE `bars` into the R2 archive object for (venue, symbol, timeframe) and return the merged
    (deep) series. NEVER shrinks: reads the current object, merges deduped-on-ts (the fetched bar wins a ts collision
    — a freshly closed bar repairs a row archived mid-candle, the _merge_bars contract), writes back. Archiving the
    same window twice is a no-op merge.

    R2 creds ABSENT → a loud no-op: returns `bars` UNCHANGED (keyless degradation, never crashes the caller). `s3` is
    injectable so tests use a fake/local client without hitting real R2."""
    settings = settings or get_settings()
    if s3 is None:
        if not _r2_ready(settings):
            logger.warning("bar_archive: R2 creds absent — archive is a no-op for %s:%s %s.", venue, symbol, timeframe)
            return bars
        s3 = _r2_client(settings)
    bucket = settings.r2_bucket
    key = archive_key(venue, symbol, timeframe)
    existing = _read_object_bars(s3, bucket, key)
    merged = _merge_bars(existing, bars)
    # Only write when the merge actually changed the stored series (a re-archive of the same window is a pure no-op,
    # so an idempotent re-run costs one GET, no PUT).
    if len(merged) != len(existing) or merged != existing:
        _write_object_bars(s3, bucket, key, merged)
        logger.info(
            "bar_archive: %s:%s %s — archived %d bars → %d total (r2://%s/%s)",
            venue, symbol, timeframe, len(bars), len(merged), bucket, key,
        )
    return merged


def load_archived_bars(
    venue: str,
    symbol: str,
    timeframe: str,
    *,
    live: list[Bar] | None = None,
    settings: Settings | None = None,
    s3: Any | None = None,
) -> list[Bar]:
    """The DEEP series for (venue, symbol, timeframe): the R2-archived history UNION-MERGED with the `live` window (the
    ~720/1000-bar keyless fetch). Live bars WIN on a ts collision (a freshly closed bar repairs a row archived
    mid-candle). So a caller gets the full accumulated depth even though each live fetch is shallow.

    R2 creds ABSENT (or no archive object yet) → returns the `live` window UNCHANGED (keyless degradation). `live`
    None → [] when there is no archive, else the archive alone."""
    settings = settings or get_settings()
    live = live or []
    if s3 is None:
        if not _r2_ready(settings):
            return live
        s3 = _r2_client(settings)
    bucket = settings.r2_bucket
    archived = _read_object_bars(s3, bucket, archive_key(venue, symbol, timeframe))
    if not archived:
        return live
    # `live` second so a freshly-closed live bar WINS over an archived row at the same ts (the _merge_bars contract).
    return _merge_bars(archived, live)


# ------------------------------------------------------------------------------------------------------------------
# The HOARD step — actively GATHER bars from the keyless-native venues into R2 from the running fleet.
#
# WHY a fetch loop (not just write-through): the Modal fleet is CACHELESS (data/market.RemoteBarsProvider fetches
# bars at RUNTIME from the Railway EU endpoint, keeps no local cache to sync). So nothing ever lands on disk for
# sync_local_cache to push. This step instead pulls each (venue, symbol) keyless window directly via
# `keyless_venue_provider` and archive_bars()→R2 it. Run hourly from the `ingest` cron: each pass captures the
# latest shallow ~720-bar keyless window and UNION-MERGES it into the deep R2 series, so the stored history only
# ever GROWS — accumulating depth the keyless REST window can never serve in one call. Free + cheap.
#
# BOUNDED by construction (so one run can't blow the budget): the crypto universe is capped to the Tier-0/1 set
# (the ~30 deepest names) × the keyless venues (kraken/binance/bybit) × the requested timeframes — a few hundred
# small REST GETs, each idempotent (a re-archive of the same window is a no-op merge → one GET, no PUT). A fetch
# error for one (venue, symbol) is logged + skipped, NEVER aborts the loop. R2 creds ABSENT → a loud no-op.
# ------------------------------------------------------------------------------------------------------------------

# The keyless-NATIVE crypto venues we hoard from (each serves ITS OWN book — never one as source-of-truth for all,
# the per-venue directive). These are exactly the venues data/market.keyless_venue_provider resolves to a LIVE
# keyless route; cache-only venues (hyperliquid/equity) have no live keyless fetch, so they are not hoarded here.
HOARD_VENUES: tuple[str, ...] = ("kraken", "binance", "bybit")

# Hard caps so one hoard run stays cheap and can NEVER fan out unboundedly (defence-in-depth alongside the
# Tier-0/1 symbol cap). At the defaults: ≤30 symbols × 3 venues × 1 timeframe = ≤90 small REST GETs per pass.
_HOARD_MAX_SYMBOLS = 30   # the Tier-0 depth (data.universe.TIER0_N) — the deepest, most-liquid names
_HOARD_MAX_CELLS = 300    # absolute ceiling on (venue × symbol × timeframe) fetches in a single run


def _hoard_symbols(store: Any | None, *, max_symbols: int) -> list[str]:
    """The Tier-0/1 crypto symbols to hoard, deepest first, capped at `max_symbols`. Reads the liquidity-ranked
    universe_pairs table when a `store` is given (Tier-0/1, crypto), else the static PERP_UNIVERSE fallback — the
    SAME source/fallback contract the screen uses. Symbols are the canonical PERP spelling (BTCUSDT); each keyless
    provider maps to its own venue spelling internally (Kraken → XBTUSD) and caches/keys under the symbol passed."""
    from cosmu.data.universe import PERP_UNIVERSE, dedupe_symbols, load_universe

    syms: list[str] = []
    if store is not None:
        try:
            # Tier-0/1 = the deepest ~30 + next band; active crypto only (the live keyless venues serve only the
            # currently-listed book, so a delisted name would just fetch empty). Liquidity-ordered, deepest first.
            rows = [
                r for r in load_universe(store, asset_class="crypto", active_only=True)
                if r.tier in (0, 1)
            ]
            syms = [r.symbol for r in rows]
        except Exception:  # noqa: BLE001 — table absent / store hiccup → fall back to the static universe
            syms = []
    if not syms:
        syms = list(PERP_UNIVERSE)
    # Dedupe (a symbol can appear under several venue rows) + cap to the deepest `max_symbols`.
    return list(dedupe_symbols(syms))[: max(0, max_symbols)]


def archive_universe_bars(
    *,
    store: Any | None = None,
    timeframes: tuple[str, ...] = ("1d",),
    venues: tuple[str, ...] = HOARD_VENUES,
    max_symbols: int = _HOARD_MAX_SYMBOLS,
    max_cells: int = _HOARD_MAX_CELLS,
    limit: int = 1000,
    settings: Settings | None = None,
    s3: Any | None = None,
    provider_for: Any | None = None,
) -> dict:
    """HOARD the Tier-0/1 crypto universe's bars from each keyless-native venue into R2 — the active gather step
    the cacheless Modal fleet needs (it keeps no local cache to sync). For each (venue, symbol, timeframe): fetch
    the keyless window via `keyless_venue_provider(venue)` and archive_bars()→R2 (idempotent union-merge, never
    shrinks). Accumulates deep history across runs from the shallow keyless window.

    BOUNDED: ≤`max_symbols` (Tier-0 depth) × `venues` × `timeframes`, hard-capped at `max_cells` total fetches.
    BEST-EFFORT: a fetch error for one (venue, symbol, timeframe) is logged + skipped, never aborts the loop.
    R2 creds ABSENT → a loud no-op ({'archived': 0, ...}); never crashes the caller, never touches a client.

    `provider_for` is injectable (defaults to data.market.keyless_venue_provider) so tests run with stub providers
    and no network; `s3` is injectable so tests use the fake in-memory client.

    Returns a summary {archived, skipped, cells, archived_bars, venues, symbols}."""
    settings = settings or get_settings()
    # R2 creds absent → loud no-op BEFORE any fetch (don't even hit the venues if we can't persist).
    if s3 is None:
        if not _r2_ready(settings):
            logger.warning("bar_archive: R2 creds absent — universe-bar hoard is a no-op.")
            return {"archived": 0, "skipped": 0, "cells": 0, "archived_bars": 0, "venues": 0, "symbols": 0}
        s3 = _r2_client(settings)

    if provider_for is None:
        # lazy import keeps the market module (and its providers) off the base import path
        from cosmu.data.market import keyless_venue_provider
        provider_for = keyless_venue_provider

    symbols = _hoard_symbols(store, max_symbols=max_symbols)
    archived = skipped = cells = total_bars = 0

    for venue in venues:
        provider = provider_for(venue)
        if provider is None:  # cache-only / unknown venue → no live keyless route, skip honestly (no fabrication)
            logger.info("bar_archive: hoard — venue %s has no keyless route, skipping.", venue)
            continue
        for symbol in symbols:
            for timeframe in timeframes:
                if cells >= max_cells:  # hard ceiling — refuse to fan out past the cost cap
                    logger.warning(
                        "bar_archive: hoard hit the %d-cell ceiling — stopping (archived %d, skipped %d).",
                        max_cells, archived, skipped,
                    )
                    return {
                        "archived": archived, "skipped": skipped, "cells": cells,
                        "archived_bars": total_bars, "venues": len(venues), "symbols": len(symbols),
                    }
                cells += 1
                try:
                    bars = provider.fetch_bars(symbol, timeframe, limit=limit)
                except Exception:  # noqa: BLE001 — one venue/symbol fetch error is logged + skipped, never aborts
                    logger.warning("bar_archive: hoard fetch failed for %s:%s %s — skipping.", venue, symbol, timeframe)
                    skipped += 1
                    continue
                if not bars:  # offline / delisted / not on this venue → nothing to archive (never fabricate)
                    skipped += 1
                    continue
                try:
                    archive_bars(venue, symbol, timeframe, bars, settings=settings, s3=s3)
                except Exception:  # noqa: BLE001 — an R2 write hiccup on one series must not abort the hoard
                    logger.warning("bar_archive: hoard archive failed for %s:%s %s — skipping.", venue, symbol, timeframe)
                    skipped += 1
                    continue
                archived += 1
                total_bars += len(bars)
    logger.info(
        "bar_archive: universe-bar hoard complete — %d series archived, %d skipped (%d cells), %d bars across "
        "%d venues × %d symbols.",
        archived, skipped, cells, total_bars, len(venues), len(symbols),
    )
    return {
        "archived": archived, "skipped": skipped, "cells": cells,
        "archived_bars": total_bars, "venues": len(venues), "symbols": len(symbols),
    }


# ------------------------------------------------------------------------------------------------------------------
# The standalone SYNC job — push the whole local `.cosmu/market_data/<venue>/` bar cache to R2 (union-merge per file).
# Run LOCAL or on Modal (never a Railway hot cron — R2 IO). `python -m cosmu.data.bar_archive sync [cache_root]`.
# ------------------------------------------------------------------------------------------------------------------
def _parse_cache_filename(name: str) -> tuple[str, str] | None:
    """Split a cache filename '<SYMBOL>_<tf>.json' into (symbol, timeframe), or None when it isn't a bar cache file.
    The timeframe is the LAST underscore-delimited token before '.json' (symbols never contain '_'; equity/HL symbols
    are bare). E.g. 'BTCUSDT_1d.json' → ('BTCUSDT', '1d')."""
    if not name.endswith(".json"):
        return None
    stem = name[: -len(".json")]
    if "_" not in stem:
        return None
    symbol, timeframe = stem.rsplit("_", 1)
    if not symbol or not timeframe:
        return None
    return symbol, timeframe


def sync_local_cache(
    *,
    cache_root: str | Path = _LOCAL_CACHE_ROOT,
    settings: Settings | None = None,
    s3: Any | None = None,
) -> dict:
    """Mirror the local bar cache → R2: for every `<cache_root>/<venue>/<SYMBOL>_<tf>.json`, UNION-MERGE its bars into
    the R2 archive object (never shrinks). READ-ONLY on the local cache. Returns a summary
    {synced, skipped, files, archived_bars}. R2 creds absent → a loud no-op ({'synced': 0, ...})."""
    settings = settings or get_settings()
    root = Path(cache_root)
    if s3 is None:
        if not _r2_ready(settings):
            logger.warning("bar_archive: R2 creds absent — local-cache sync is a no-op.")
            return {"synced": 0, "skipped": 0, "files": 0, "archived_bars": 0}
        s3 = _r2_client(settings)

    synced = skipped = total_bars = 0
    files = 0
    if not root.exists():
        logger.warning("bar_archive: local cache root %s does not exist — nothing to sync.", root)
        return {"synced": 0, "skipped": 0, "files": 0, "archived_bars": 0}

    for venue_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        venue = venue_dir.name
        for cache_file in sorted(venue_dir.glob("*.json")):
            files += 1
            parsed = _parse_cache_filename(cache_file.name)
            if parsed is None:
                skipped += 1
                continue
            symbol, timeframe = parsed
            try:
                rows = json.loads(cache_file.read_text())
                bars = [_bar_from_json(r) for r in rows]
            except Exception:  # noqa: BLE001 — a corrupt local file is skipped, never aborts the whole sync
                logger.warning("bar_archive: skipping unreadable local cache file %s", cache_file)
                skipped += 1
                continue
            if not bars:
                skipped += 1
                continue
            archive_bars(venue, symbol, timeframe, bars, settings=settings, s3=s3)
            synced += 1
            total_bars += len(bars)
    logger.info(
        "bar_archive: local-cache sync complete — %d series synced, %d skipped (%d files), %d bars archived.",
        synced, skipped, files, total_bars,
    )
    return {"synced": synced, "skipped": skipped, "files": files, "archived_bars": total_bars}


def main(argv: list[str] | None = None) -> int:
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = args[0] if args else "sync"
    if cmd == "hoard":
        # Pull the Tier-0/1 crypto universe's bars from the keyless venues into R2 (the active gather step the
        # cacheless fleet needs). Reads the liquidity-ranked universe from the store; falls back to PERP_UNIVERSE.
        from cosmu.knowledge.store import Store

        try:
            store: Any | None = Store(get_settings())
        except Exception:  # noqa: BLE001 — no DB locally → hoard the static PERP_UNIVERSE fallback
            store = None
        result = archive_universe_bars(store=store)
        print(
            f"bar_archive hoard: {result['archived']} series archived, {result['skipped']} skipped "
            f"({result['cells']} cells, {result['venues']} venues × {result['symbols']} symbols), "
            f"{result['archived_bars']:,} bars."
        )
        return 0
    if cmd != "sync":
        print(f"usage: python -m cosmu.data.bar_archive sync [cache_root] | hoard\n  (unknown command {cmd!r})")
        return 2
    cache_root = args[1] if len(args) > 1 else _LOCAL_CACHE_ROOT
    result = sync_local_cache(cache_root=cache_root)
    print(
        f"bar_archive sync: {result['synced']} series synced, {result['skipped']} skipped "
        f"({result['files']} files), {result['archived_bars']:,} bars archived."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
