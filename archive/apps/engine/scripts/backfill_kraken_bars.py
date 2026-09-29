#!/usr/bin/env python3
# intent: backfill the keyless Kraken bar cache as DEEP as Kraken's PUBLIC OHLC endpoint allows, so long backtests
# have history for the Binance→Kraken bars off-ramp (COSMU_BARS_VENUE=kraken, #360). We PAGINATE forward with
# `since` (the cursor Kraken echoes as result["last"]) and MERGE every page into the SAME on-disk cache the live
# KrakenSpotOHLCVProvider reads from (.cosmu/market_data/kraken, _bars_to_rows shape) via the provider's own
# _write_cache — so the result is byte-identical to what the screen / paper clock would have cached.
#
# ⚠️ HARD KRAKEN LIMIT (verified 2026-06-25): the PUBLIC `/0/public/OHLC` endpoint returns at most ~720 candles
# of the MOST-RECENT history per interval, and `since` only FILTERS WITHIN that head window — it does NOT unlock
# older data. So for 1d bars Kraken's keyless ceiling is ~720 days (~2y); 4h ≈ 120d; 1h ≈ 30d. Paging therefore
# yields the single head page for every frame. This is by design (the public OHLC is a recent-window feed, not a
# deep-history archive). Going DEEPER than ~720 candles needs a different source: (a) the existing Binance-sourced
# cache — `_merge_bars` is a UNION on ts that NEVER shrinks, so any Binance daily history already on disk is kept
# and the Kraken window overlays/extends the recent end; or (b) a paid deep-history vendor at the live phase.
# The pagination loop is retained (correct + harmless + future-proof if Kraken ever lifts the cap) but in practice
# stops after one page on the public endpoint. The script is honest about the ceiling at runtime.
#
# inputs: a symbol list (default a wide Kraken-listed set) + an optional timeframe (default 1d). KEYLESS — no
# account, no API key. outputs: extended provider cache files (never shrinks — _merge_bars is a union dedup on ts).
# invariants: closed-candle-correct (the in-progress candle is dropped before caching via _drop_unclosed);
# idempotent (re-running only ADDS missing bars); offline-safe (a network error stops that symbol's paging and
# keeps what was fetched, never crashes the batch); polite (rate-limited between pages); ZERO LLM, no money path.
#
# Usage (run from repo root with the engine on PYTHONPATH):
#   PYTHONPATH=apps/engine python3 -m scripts.backfill_kraken_bars                    # wide default set, 1d
#   PYTHONPATH=apps/engine python3 -m scripts.backfill_kraken_bars --symbols BTCUSDT,ETHUSDT
#   PYTHONPATH=apps/engine python3 -m scripts.backfill_kraken_bars --timeframe 4h
#   PYTHONPATH=apps/engine python3 -m scripts.backfill_kraken_bars --dry-run          # fetch + count, no write
# (or `cd apps/engine && python3 scripts/backfill_kraken_bars.py …`)

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime

from cosmu.data.market import (
    Bar,
    KrakenSpotOHLCVProvider,
    _bars_from_kraken,
    _drop_unclosed,
    _kraken_pair,
    _merge_bars,
    _ssl_context,
)

# A wide set of liquid Kraken-listed spot symbols, in OUR exchange spelling (BTCUSDT etc.). _kraken_pair maps each
# to Kraken's XBTUSD-style convention; USDT pairs map to Kraken's deep USD books. Kept broad but liquid so a deep
# daily backfill is worthwhile (thin pairs have little history and little use). Extend freely.
_DEFAULT_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT",
    "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT", "LTCUSDT",
    "BCHUSDT", "TRXUSDT", "ATOMUSDT", "XLMUSDT", "ETCUSDT",
    "UNIUSDT", "AAVEUSDT", "FILUSDT", "ALGOUSDT", "NEARUSDT",
    "ICPUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "INJUSDT",
    "SUIUSDT", "SEIUSDT", "TIAUSDT", "RUNEUSDT", "GALAUSDT",
]

_KRAKEN_OHLC_URL = "https://api.kraken.com/0/public/OHLC"
# Kraken takes the interval in MINUTES; same map the provider uses.
_INTERVAL_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440, "1w": 10080}
_PAGE_SLEEP_SECONDS = 1.2   # be polite to the public endpoint between paged calls
_DEFAULT_MAX_PAGES = 200    # generous ceiling; daily history rarely needs this many ~720-bar pages
# The far-past seed for the FIRST page. We page FORWARD with `since` (the documented cursor pattern): seed it
# before any crypto listing and follow result["last"] toward the present. NOTE the verified cap above — for the
# PUBLIC OHLC endpoint `since` is clamped INTO the most-recent ~720-candle window, so this seed lands on the head
# page either way; the forward-paging loop is correct + future-proof but does not reach pre-window history today.
_HISTORY_START_EPOCH = int(datetime(2013, 1, 1, tzinfo=UTC).timestamp())


def _fetch_page(pair: str, interval: int, since: int | None) -> tuple[list[Bar], int | None]:
    """One Kraken OHLC page. Returns (ascending bars, next_since). `since` is Kraken's cursor (epoch seconds);
    Kraken echoes result["last"] as the cursor for the NEXT page. Raises on a transport/SSL error so the caller
    can stop that symbol's paging and keep what it already has (offline-safe)."""
    params: dict[str, str | int] = {"pair": pair, "interval": interval}
    if since is not None:
        params["since"] = int(since)
    url = f"{_KRAKEN_OHLC_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
    with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if payload.get("error"):
        # Kraken returns a non-empty error list (e.g. unknown pair, rate limit) — surface it as a stop signal.
        raise RuntimeError(f"kraken error for {pair}: {payload['error']}")
    bars = _bars_from_kraken(payload)
    last = payload.get("result", {}).get("last")
    next_since = int(last) if last is not None else None
    return bars, next_since


def backfill_symbol(
    provider: KrakenSpotOHLCVProvider,
    symbol: str,
    timeframe: str,
    *,
    max_pages: int,
    dry_run: bool,
    now: datetime,
) -> int:
    """Walk Kraken's paginated OHLC for one symbol FORWARD from a far-past seed, dropping the unclosed candle and
    merging every page into the provider cache (unless dry-run). Returns the total bar count now in the cache
    (or, in dry-run, the count of distinct fetched bars). Stops on: no next cursor, a non-advancing cursor, an
    empty page, the page ceiling, or a network error (keeping everything fetched so far)."""
    pair = _kraken_pair(symbol)
    interval = _INTERVAL_MINUTES.get(timeframe, 1440)
    collected: dict[datetime, Bar] = {}
    # Seed `since` at a pre-listing epoch and page FORWARD: a None `since` returns ONLY the recent head (~720
    # bars), which is exactly what the live provider already fetches — useless for DEEP history. Seeding far in
    # the past makes Kraken start at the symbol's inception and the `last` cursor walks us forward to the present.
    since: int | None = _HISTORY_START_EPOCH
    seen_cursors: set[int] = set()

    for page_i in range(max_pages):
        try:
            bars, next_since = _fetch_page(pair, interval, since)
        except Exception as exc:  # noqa: BLE001 — offline/refused/rate-limit: stop paging, keep what we have
            print(f"  [{symbol}] page {page_i + 1}: stopped ({exc})")
            break
        if not bars:
            break
        for b in bars:
            collected[b.ts] = b
        newest = max(b.ts for b in bars)
        print(f"  [{symbol}] page {page_i + 1}: +{len(bars)} bars  newest={newest.date()}  total={len(collected)}")
        # Paging termination: Kraken hands back `last` as the next cursor; once it stops advancing (or repeats)
        # we've reached the head of the series. A repeated cursor would loop forever, so guard on it explicitly.
        if next_since is None or next_since in seen_cursors or (since is not None and next_since <= since):
            break
        seen_cursors.add(next_since)
        since = next_since
        time.sleep(_PAGE_SLEEP_SECONDS)

    if not collected:
        print(f"  [{symbol}] no bars fetched (unknown pair on Kraken, or offline)")
        return 0

    # Drop the in-progress candle so we never freeze a mid-bar snapshot as a final close (same rule the live
    # provider applies). Then merge into the provider cache via its OWN writer so the on-disk shape is identical.
    fetched = _drop_unclosed(sorted(collected.values(), key=lambda x: x.ts), timeframe, now)
    if not fetched:
        print(f"  [{symbol}] only the unclosed candle was available — nothing to cache")
        return 0

    if dry_run:
        merged = _merge_bars(provider._read_cache(symbol, timeframe), fetched)  # noqa: SLF001 — intentional cache peek
        span = f"{merged[0].ts.date()} → {merged[-1].ts.date()}" if merged else "—"
        print(f"  [{symbol}] DRY-RUN: would cache {len(merged)} bars ({span})  [not written]")
        return len(merged)

    merged = provider._write_cache(symbol, timeframe, fetched)  # noqa: SLF001 — reuse the provider's merge+atomic write
    span = f"{merged[0].ts.date()} → {merged[-1].ts.date()}" if merged else "—"
    print(f"  [{symbol}] cached {len(merged)} bars ({span})")
    return len(merged)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deep daily-OHLC backfill from Kraken's keyless public endpoint.")
    parser.add_argument(
        "--symbols",
        default=",".join(_DEFAULT_SYMBOLS),
        help="comma-separated symbols in our spelling (BTCUSDT,ETHUSDT,…). Default: a wide Kraken-listed set.",
    )
    parser.add_argument("--timeframe", default="1d", help="bar timeframe (default 1d). 1m/5m/15m/30m/1h/4h/1d/1w.")
    parser.add_argument("--max-pages", type=int, default=_DEFAULT_MAX_PAGES, help="page ceiling per symbol.")
    parser.add_argument("--cache-dir", default=".cosmu/market_data/kraken", help="provider cache dir (advanced).")
    parser.add_argument("--dry-run", action="store_true", help="fetch + count only; do NOT write the cache.")
    args = parser.parse_args(argv)

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if args.timeframe not in _INTERVAL_MINUTES:
        print(f"unknown timeframe {args.timeframe!r}; choose {sorted(_INTERVAL_MINUTES)}", file=sys.stderr)
        return 2

    provider = KrakenSpotOHLCVProvider(cache_dir=args.cache_dir)
    now = datetime.now(tz=UTC)
    mode = "DRY-RUN (no writes)" if args.dry_run else f"writing → {args.cache_dir}"
    print(f"Kraken keyless backfill: {len(symbols)} symbols × {args.timeframe}  [{mode}]")

    grand_total = 0
    for symbol in symbols:
        total = backfill_symbol(
            provider, symbol, args.timeframe,
            max_pages=args.max_pages, dry_run=args.dry_run, now=now,
        )
        grand_total += total
    print(f"Done. {len(symbols)} symbols, {grand_total} total bars in cache.")
    print(
        "NOTE: Kraken's PUBLIC OHLC caps at ~720 most-recent candles per interval — `since` cannot reach older "
        "history. The cache never shrinks (_merge_bars union), so any deeper Binance-sourced history already on "
        "disk is preserved; true multi-year depth beyond ~720 candles needs a paid deep-history vendor."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
