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
    if cmd != "sync":
        print(f"usage: python -m cosmu.data.bar_archive sync [cache_root]\n  (unknown command {cmd!r})")
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
