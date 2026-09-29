#!/usr/bin/env python3
# Ingest Hyperliquid perpetual candle history into .cosmu/market_data/hyperliquid/<COIN>USDC_1d.json.
# Uses the public Hyperliquid info REST endpoint (no key). Idempotent: re-runs only extend the cache.
#
# Run:
#   PYTHONPATH=apps/engine python3 scripts/ingest_hyperliquid_bars.py
#   PYTHONPATH=apps/engine python3 scripts/ingest_hyperliquid_bars.py --coins BTC,ETH,SOL
#   PYTHONPATH=apps/engine python3 scripts/ingest_hyperliquid_bars.py --min-volume 5000000 --days 1825

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import tempfile
import time
import urllib.request
from decimal import Decimal
from pathlib import Path

_ENGINE = Path(__file__).resolve().parents[1] / "apps" / "engine"
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

CACHE_DIR = Path(os.environ.get("COSMU_HL_CACHE", "<repo>/.cosmu/market_data/hyperliquid"))
HL_API = "https://api.hyperliquid.xyz/info"
# Bars a single candle request can return; HL supports arbitrary windows but throttles heavy requests.
_PAGE_DAYS = 365
_RATE_SLEEP = 0.25  # seconds between requests (be a good citizen)


def _ssl_context() -> ssl.SSLContext:
    """Mirror cosmu.data.market._ssl_context: use certifi's CA bundle so macOS Python (whose default
    context has no system CAs) can verify TLS. Falls back to the default context when certifi is absent."""
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def _post(payload: dict) -> dict | list:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(HL_API, data=body, headers={"Content-Type": "application/json", "User-Agent": "cosmu-engine/0.1"})
    with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:
        return json.loads(resp.read().decode())


def _all_coins(min_volume_usd: float) -> list[str]:
    """Return all coins on Hyperliquid with 24h notional > min_volume_usd, sorted by volume descending."""
    meta = _post({"type": "meta"})
    ctx = _post({"type": "metaAndAssetCtxs"})
    ctxs = ctx[1] if isinstance(ctx, list) else []
    universe = meta.get("universe", [])
    coins: list[tuple[float, str]] = []
    for i, asset in enumerate(universe):
        name = asset.get("name", "")
        if not name:
            continue
        vol = 0.0
        if i < len(ctxs):
            try:
                vol = float(ctxs[i].get("dayNtlVlm", 0))
            except (TypeError, ValueError):
                pass
        if vol >= min_volume_usd:
            coins.append((vol, name))
    return [c for _, c in sorted(coins, reverse=True)]


def _fetch_candles(coin: str, start_ms: int, end_ms: int) -> list[dict]:
    payload = {"type": "candleSnapshot", "req": {"coin": coin, "interval": "1d", "startTime": start_ms, "endTime": end_ms}}
    data = _post(payload)
    return data if isinstance(data, list) else []


def _cache_path(coin: str) -> Path:
    return CACHE_DIR / f"{coin}USDC_1d.json"


def _read_cache(coin: str) -> list[dict]:
    p = _cache_path(coin)
    if not p.exists():
        return []
    return json.loads(p.read_text())


def _write_cache(coin: str, rows: list[dict]) -> None:
    by_ts: dict[int, dict] = {r["ts"]: r for r in _read_cache(coin)}
    for r in rows:
        by_ts[r["ts"]] = r
    merged = sorted(by_ts.values(), key=lambda r: r["ts"])
    p = _cache_path(coin)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(json.dumps(merged, separators=(",", ":")))
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _hl_to_row(c: dict) -> dict | None:
    try:
        ts_ms = int(c["t"])
        return {
            "ts": ts_ms,
            "open": str(c["o"]),
            "high": str(c["h"]),
            "low": str(c["l"]),
            "close": str(c["c"]),
            "volume": str(Decimal(str(c.get("v", "0")))),
        }
    except (KeyError, TypeError, ValueError):
        return None


def ingest_coin(coin: str, days: int) -> int:
    import datetime as dt

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    existing = _read_cache(coin)
    now_ms = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    one_day = 86400 * 1000
    lookback_ms = now_ms - days * one_day
    # Idempotent re-runs EXTEND forward, but must also BACKFILL when the cache doesn't yet reach `lookback_ms`
    # (e.g. a prior shallow run). If the cache's EARLIEST bar already covers the requested lookback, only fetch
    # bars after the latest cached one; otherwise refetch the full window and let _write_cache's ts-merge dedupe.
    if existing and existing[0]["ts"] <= lookback_ms + one_day:
        start_ms = existing[-1]["ts"] + one_day
    else:
        start_ms = lookback_ms

    new_rows: list[dict] = []
    cursor = start_ms
    page_ms = _PAGE_DAYS * 86400 * 1000
    while cursor < now_ms:
        end = min(cursor + page_ms, now_ms)
        candles = _fetch_candles(coin, cursor, end)
        for c in candles:
            row = _hl_to_row(c)
            if row and row["ts"] >= start_ms:
                new_rows.append(row)
        cursor = end + 1
        if cursor < now_ms:
            time.sleep(_RATE_SLEEP)

    if new_rows:
        _write_cache(coin, new_rows)
    return len(new_rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest Hyperliquid perpetual daily OHLCV bars.")
    parser.add_argument("--coins", default="", help="Comma-separated coin names (e.g. BTC,ETH). Default: all by volume.")
    parser.add_argument("--min-volume", type=float, default=1_000_000, help="Min 24h notional USD to include (default 1M).")
    parser.add_argument("--days", type=int, default=1825, help="Lookback days (default 1825 = 5yr).")
    args = parser.parse_args(argv)

    if args.coins:
        coins = [c.strip().upper() for c in args.coins.split(",") if c.strip()]
    else:
        print("Fetching Hyperliquid coin list …")
        coins = _all_coins(args.min_volume)
        print(f"  {len(coins)} coins with 24h volume ≥ ${args.min_volume:,.0f}")

    total_new = 0
    for i, coin in enumerate(coins):
        try:
            n = ingest_coin(coin, args.days)
            total_new += n
            label = f"{coin}USDC"
            print(f"  [{i + 1:3d}/{len(coins)}] {label:<18} +{n:4d} bars  (cache: {_cache_path(coin)})")
        except Exception as e:  # noqa: BLE001
            print(f"  [{i + 1:3d}/{len(coins)}] {coin:<18} ERROR: {e}")
        if i < len(coins) - 1:
            time.sleep(_RATE_SLEEP)

    print(f"\nDone. {total_new} new bars written to {CACHE_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
