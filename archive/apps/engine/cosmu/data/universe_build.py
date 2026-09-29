# intent: the OPERATOR-DRIVEN builder that turns the live venue universe into a PERSISTED, survivorship-honest,
# liquidity-ranked source — fetch all venues (venue_universe.fetch/collect), optionally backfill DELISTED Binance
# spot pairs from the FREE Binance Vision archive (so a historical backtest sees that date's tradable set), rank
# into tiers, then upsert into the `universe_pairs` DB table + write a dated JSON snapshot to R2. inputs: the
# public venue APIs + the Vision S3 listing; outputs: universe_pairs rows + r2://<bucket>/universe/<date>.json.
# invariants: COMPOSES venue_universe (never re-implements a fetch); idempotent upsert keyed on id; delisted rows
# are active=0 with a real delisted_at (never a fabricated date — only Vision's last archived month); R2 write is
# best-effort + key-gated (no creds → local-only, honest skip); heavy run → operator/Modal, but the code + an
# OFFLINE deterministic test (inject the fetch seams) are complete here. No API key, ever.

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from cosmu.data.venue_universe import (
    GetJson,
    PostJson,
    UniversePair,
    binance_vision_spot_symbols,
    binance_vision_symbol_window,
    collect_all_venues,
    rank_and_tier,
)

logger = logging.getLogger("cosmu.data.universe_build")

__all__ = [
    "BuildResult",
    "build_binance_vision_delisted",
    "build_universe",
    "persist_universe",
    "snapshot_to_r2",
    "main",
]


@dataclass(frozen=True)
class BuildResult:
    pairs: list[UniversePair]
    per_venue: dict[str, int]
    per_tier: dict[int, int]
    delisted: int
    listed_dated: int   # pairs carrying a listed_at (PIT coverage)


# ---------------------------------------------------------------------------------------------------------------
# Survivorship backbone — the DELISTED Binance spot pairs. Enumerate the Vision archive's full historical symbol
# set, diff against the venues currently TRADING, and for each delisted symbol read its listed/delisted window
# from the archive key range. These become active=0 universe rows so the UniverseCalendar excludes them after
# their delisting and INCLUDES them before it — the exact survivorship fix.
# ---------------------------------------------------------------------------------------------------------------
def build_binance_vision_delisted(
    current_spot_symbols: set[str],
    *,
    get_text: Callable[[str], str] | None = None,
    quotes: tuple[str, ...] = ("USDT",),
    max_windows: int | None = None,
) -> list[UniversePair]:
    """Delisted Binance spot pairs from Vision (in the archive, NOT currently TRADING). One S3 listing enumerates
    the historical superset; one more per delisted symbol reads its [first_month, last_month] window. `quotes`
    filters which delisted pairs to probe (default USDT — the survivorship-critical set); `max_windows` caps the
    per-symbol window probes for a bounded run (None = all). Returns active=0 rows with source='vision'."""
    historical = binance_vision_spot_symbols(get_text)
    delisted_syms = [
        s for s in historical
        if s not in current_spot_symbols and any(s.endswith(q) for q in quotes)
    ]
    if max_windows is not None:
        delisted_syms = delisted_syms[:max_windows]
    out: list[UniversePair] = []
    for sym in delisted_syms:
        first, last = binance_vision_symbol_window(sym, market="spot", timeframe="1d", get_text=get_text)
        if first is None:
            continue
        quote = next((q for q in quotes if sym.endswith(q)), "")
        base = sym[: -len(quote)] if quote else sym
        out.append(
            UniversePair(
                venue="binance", symbol=sym, base=base, quote=quote,
                asset_class="crypto", instrument_type="spot", liquidity_usd_24h=0.0, source="vision",
                listed_at=first, delisted_at=last, active=False,
            )
        )
    logger.info("vision delisted: %d historical, %d delisted (quotes=%s), %d windowed",
                len(historical), len(delisted_syms), ",".join(quotes), len(out))
    return out


def _enrich_listed_at(live: list[UniversePair], get_text: Callable[[str], str] | None, cap: int) -> list[UniversePair]:
    """Fill listed_at on the deepest `cap` Binance spot pairs from their Vision first-archived month (perp already
    carries onboardDate). Bounded — one S3 listing per symbol — so the operator dials PIT depth vs runtime."""
    if cap <= 0:
        return live
    targets = [p for p in live if p.venue == "binance" and p.instrument_type == "spot" and p.listed_at is None]
    targets = sorted(targets, key=lambda p: -(p.liquidity_usd_24h or 0.0))[:cap]
    by_id = {p.id: p for p in targets}
    for p in targets:
        first, _ = binance_vision_symbol_window(p.symbol, market="spot", get_text=get_text)
        if first is not None:
            by_id[p.id] = replace(p, listed_at=first)
    enriched = {pid: pp for pid, pp in by_id.items()}
    return [enriched.get(p.id, p) for p in live]


def build_universe(
    *,
    get: GetJson | None = None,
    post: PostJson | None = None,
    get_text: Callable[[str], str] | None = None,
    include_curated: bool = True,
    vision_delisted: bool = False,
    delisted_quotes: tuple[str, ...] = ("USDT",),
    max_delisted_windows: int | None = None,
    enrich_listed_cap: int = 0,
) -> BuildResult:
    """Collect every venue → (optionally) enrich listed_at + backfill Vision-delisted → ONE rank+tier pass."""
    live = collect_all_venues(get=get, post=post, include_curated=include_curated)
    if enrich_listed_cap > 0:
        live = _enrich_listed_at(live, get_text, enrich_listed_cap)

    delisted: list[UniversePair] = []
    if vision_delisted:
        current_spot = {p.symbol for p in live if p.venue == "binance" and p.instrument_type == "spot"}
        delisted = build_binance_vision_delisted(
            current_spot, get_text=get_text, quotes=delisted_quotes, max_windows=max_delisted_windows
        )

    ranked = rank_and_tier(live + delisted)
    per_venue: dict[str, int] = {}
    per_tier: dict[int, int] = {}
    for p in ranked:
        per_venue[p.venue] = per_venue.get(p.venue, 0) + 1
        if p.tier is not None:
            per_tier[p.tier] = per_tier.get(p.tier, 0) + 1
    return BuildResult(
        pairs=ranked,
        per_venue=dict(sorted(per_venue.items())),
        per_tier=dict(sorted(per_tier.items())),
        delisted=len(delisted),
        listed_dated=sum(1 for p in ranked if p.listed_at is not None),
    )


# ---------------------------------------------------------------------------------------------------------------
# Persistence — DB upsert (idempotent on id) + a dated R2 JSON snapshot.
# ---------------------------------------------------------------------------------------------------------------
def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def persist_universe(store: Any, pairs: list[UniversePair], *, now: datetime | None = None) -> int:
    """Idempotent upsert of every pair into universe_pairs (one transaction). Re-running refreshes liquidity/tier/
    rank/active/fetched_at for an existing id and inserts new ones. Returns the rows written.
    The `multiplier` column is included when present (futures sizing); NULL for spot/equity/perp."""
    now = now or datetime.now(UTC)
    stamp = now.isoformat()
    cols = (
        "id", "venue", "symbol", "base", "quote", "asset_class", "instrument_type",
        "liquidity_usd_24h", "tier", "rank", "listed_at", "delisted_at", "active", "source",
        "multiplier", "fetched_at",
    )
    update = ", ".join(f"{c} = excluded.{c}" for c in cols if c != "id")
    sql = (
        f"INSERT INTO universe_pairs ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) "
        f"ON CONFLICT (id) DO UPDATE SET {update}"
    )
    with store.batch() as writer:
        for p in pairs:
            writer.execute(
                sql,
                (
                    p.id, p.venue, p.symbol, p.base, p.quote, p.asset_class, p.instrument_type,
                    float(p.liquidity_usd_24h or 0.0), p.tier, p.rank,
                    _iso(p.listed_at), _iso(p.delisted_at), int(p.active), p.source,
                    float(p.multiplier) if p.multiplier is not None else None, stamp,
                ),
            )
    return len(pairs)


def _pair_to_dict(p: UniversePair) -> dict[str, Any]:
    return {
        "id": p.id, "venue": p.venue, "symbol": p.symbol, "base": p.base, "quote": p.quote,
        "asset_class": p.asset_class, "instrument_type": p.instrument_type,
        "liquidity_usd_24h": p.liquidity_usd_24h, "tier": p.tier, "rank": p.rank,
        "listed_at": _iso(p.listed_at), "delisted_at": _iso(p.delisted_at),
        "active": p.active, "source": p.source,
        "multiplier": p.multiplier,
    }


def snapshot_to_r2(settings: Any, pairs: list[UniversePair], *, now: datetime | None = None) -> str | None:
    """Write a dated JSON snapshot of the universe to r2://<bucket>/universe/<date>.json (+ latest.json). Best-
    effort + key-gated: no R2 creds → return None (local-only honest skip), never crash the build."""
    acct = getattr(settings, "r2_account_id", None)
    key = getattr(settings, "r2_access_key_id", None)
    secret = getattr(settings, "r2_secret_access_key", None)
    bucket = getattr(settings, "r2_bucket", None)
    if not (acct and key and secret and bucket):
        logger.info("snapshot_to_r2: no R2 creds → skipping (local-only)")
        return None
    now = now or datetime.now(UTC)
    body = json.dumps(
        {"generated_at": now.isoformat(), "count": len(pairs), "pairs": [_pair_to_dict(p) for p in pairs]},
        separators=(",", ":"),
    ).encode()
    try:
        import boto3

        s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{acct}.r2.cloudflarestorage.com",
            aws_access_key_id=key, aws_secret_access_key=secret, region_name="auto",
        )
        dated = f"universe/{now.strftime('%Y-%m-%d')}.json"
        for k in (dated, "universe/latest.json"):
            s3.put_object(Bucket=bucket, Key=k, Body=body, ContentType="application/json")
        uri = f"r2://{bucket}/{dated}"
        logger.info("snapshot_to_r2: wrote %s (%.2f KB)", uri, len(body) / 1024)
        return uri
    except Exception as e:  # noqa: BLE001 — snapshot is best-effort; the DB upsert is the source of truth
        logger.warning("snapshot_to_r2 failed: %s", e)
        return None


# ---------------------------------------------------------------------------------------------------------------
# CLI — `python -m cosmu.data.universe_build [--vision-delisted] [--no-persist] [--no-r2] ...`
# ---------------------------------------------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="universe-build",
        description="Fetch the live venue universe (+ optional Vision delisted backfill), rank into tiers, and "
        "persist to the universe_pairs DB table + an R2 snapshot. Keyless venue APIs; heavy run is local/Modal.",
    )
    p.add_argument("--vision-delisted", action="store_true",
                   help="backfill DELISTED Binance spot pairs from the Vision archive (survivorship)")
    p.add_argument("--delisted-quotes", default="USDT",
                   help="comma-separated quote filter for delisted pairs (default: USDT)")
    p.add_argument("--max-delisted", type=int, default=None,
                   help="cap the per-symbol Vision window probes (default: all delisted)")
    p.add_argument("--enrich-listed", type=int, default=0,
                   help="fill listed_at on the N deepest Binance spot pairs from Vision (default: 0 = skip)")
    p.add_argument("--no-curated", action="store_true", help="exclude the curated IBKR equity universe")
    p.add_argument("--no-persist", action="store_true", help="don't write the universe_pairs DB table")
    p.add_argument("--no-r2", action="store_true", help="don't write the R2 snapshot")
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = _build_parser().parse_args(argv)
    quotes = tuple(q.strip().upper() for q in args.delisted_quotes.split(",") if q.strip())

    print("universe-build · fetching all venues …")
    result = build_universe(
        include_curated=not args.no_curated,
        vision_delisted=args.vision_delisted,
        delisted_quotes=quotes,
        max_delisted_windows=args.max_delisted,
        enrich_listed_cap=args.enrich_listed,
    )
    print(f"  total pairs : {len(result.pairs)}")
    print(f"  per venue   : {result.per_venue}")
    print(f"  per tier    : {result.per_tier}")
    print(f"  delisted    : {result.delisted}  ·  with listed_at: {result.listed_dated}")

    if not args.no_persist:
        from cosmu.config.settings import get_settings
        from cosmu.knowledge.store import Store

        settings = get_settings()
        store = Store(settings)
        store.migrate()
        n = persist_universe(store, result.pairs)
        print(f"  persisted   : {n} rows → universe_pairs")
        if not args.no_r2:
            uri = snapshot_to_r2(settings, result.pairs)
            print(f"  r2 snapshot : {uri or '(skipped — no creds)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
