#!/usr/bin/env python3
# intent: Backfill full LunarCrush v4 daily history (social_volume/social_sentiment/galaxy_score) for all
# PERP_UNIVERSE symbols into the append-only PIT alt-data store. Fetches all three metrics in ONE API call
# per symbol (the v4 time-series endpoint returns them together) so the 10-req/min rate limit is respected
# with one sleep interval between symbols. Idempotent: append_dedup writes 0 on a re-run. Requires
# LUNARCRUSH_API_KEY in the environment (.env.local or Railway).
#
# Run (from the repo root):
#   PYTHONPATH=apps/engine python3 scripts/backfill_lunarcrush.py
#   PYTHONPATH=apps/engine python3 scripts/backfill_lunarcrush.py --symbols BTCUSDT,ETHUSDT
#   PYTHONPATH=apps/engine python3 scripts/backfill_lunarcrush.py --dry-run

from __future__ import annotations

import argparse
import json
import ssl
import sys
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

_ENGINE = Path(__file__).resolve().parents[1] / "apps" / "engine"
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from cosmu.config.settings import get_settings  # noqa: E402
from cosmu.data.altdata import AltDataPoint, AltDataStore  # noqa: E402
from cosmu.data.universe import perp_universe  # noqa: E402
from cosmu.ingest.pipeline import append_dedup  # noqa: E402

# LunarCrush v4 native field → SEMANTIC metric name stored in the alt-data store.
# The v4 API returns `interactions` as the social-volume measure (not `social_volume`).
_FIELD_TO_METRIC: dict[str, str] = {
    "interactions": "social_volume",
    "sentiment": "social_sentiment",
    "galaxy_score": "galaxy_score",
}

PROVIDER_NAME = "lunarcrush"
BASE_URL = "https://lunarcrush.com/api4/public"
# Conservative sleep: 10 req/min limit → 7 s between calls leaves a safety margin.
SLEEP_BETWEEN_SYMBOLS = 7.0


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _coin(symbol: str) -> str:
    return symbol[:-4] if symbol.endswith("USDT") else symbol


def _fetch_coin(api_key: str, coin: str) -> list[dict]:
    """Fetch the full daily time-series for one coin. Returns raw rows or [] on any error."""
    url = f"{BASE_URL}/coins/{urllib.parse.quote(coin)}/time-series/v2?{urllib.parse.urlencode({'bucket': 'day'})}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}", "User-Agent": "cosmu-engine/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return payload.get("data", []) or []
    except Exception as exc:  # noqa: BLE001 — one dead coin never aborts the pass
        print(f"  ERROR fetching {coin}: {exc}")
        return []


def _rows_to_points(rows: list[dict], native_field: str) -> list[AltDataPoint]:
    """Convert raw API rows to AltDataPoints for one metric. Skips rows where the field is None."""
    out: list[AltDataPoint] = []
    for row in rows:
        val = row.get(native_field)
        if val is None:
            continue
        ts = datetime.fromtimestamp(int(row["time"]), tz=UTC)
        out.append(AltDataPoint(ts=ts, available_at=ts + timedelta(days=1), value=float(val)))
    return out


def backfill(symbols: list[str], api_key: str, store: AltDataStore, *, dry_run: bool = False) -> dict[str, dict[str, int]]:
    """Backfill all three LunarCrush metrics for every symbol. Returns {symbol: {metric: written}}."""
    results: dict[str, dict[str, int]] = {}
    total_calls = len(symbols)
    for idx, symbol in enumerate(symbols, 1):
        coin = _coin(symbol)
        print(f"[{idx}/{total_calls}] {symbol} ({coin}) ...", end=" ", flush=True)
        if dry_run:
            print("SKIP (dry-run)")
            results[symbol] = {m: 0 for m in _FIELD_TO_METRIC.values()}
            continue

        rows = _fetch_coin(api_key, coin)
        written_per_metric: dict[str, int] = {}
        for native_field, metric in _FIELD_TO_METRIC.items():
            points = _rows_to_points(rows, native_field)
            w = append_dedup(store, PROVIDER_NAME, symbol, metric, points)
            written_per_metric[metric] = w
        results[symbol] = written_per_metric

        total_new = sum(written_per_metric.values())
        total_rows = len(rows)
        print(f"rows={total_rows} new={total_new} ({', '.join(f'{m}={v}' for m, v in written_per_metric.items())})")

        if idx < total_calls:
            time.sleep(SLEEP_BETWEEN_SYMBOLS)

    return results


def _load_env_local() -> None:
    """Load .env.local from the repo root so the API key is available when running without Railway/dotenv."""
    env_path = Path(__file__).resolve().parents[1] / ".env.local"
    if not env_path.exists():
        return
    import os
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.split("#")[0].strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def main(argv: list[str] | None = None) -> int:
    _load_env_local()

    parser = argparse.ArgumentParser(description="Backfill LunarCrush daily history for the PERP_UNIVERSE.")
    parser.add_argument("--symbols", default="", help="comma-separated symbols (default = full PERP_UNIVERSE)")
    parser.add_argument("--dry-run", action="store_true", help="probe only (no API calls, no writes)")
    args = parser.parse_args(argv)

    settings = get_settings()
    api_key = settings.lunarcrush_api_key or ""
    if not api_key and not args.dry_run:
        print("ERROR: LUNARCRUSH_API_KEY is not set. Export it or add it to .env.local.", file=sys.stderr)
        return 1

    symbols: list[str] = (
        [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        if args.symbols else perp_universe()
    )

    store = AltDataStore()
    print(f"LunarCrush backfill — {len(symbols)} symbols, metrics: {', '.join(_FIELD_TO_METRIC.values())}")
    print(f"Rate limit: ~10 req/min → {SLEEP_BETWEEN_SYMBOLS}s sleep between symbols")
    print(f"Estimated time: ~{len(symbols) * SLEEP_BETWEEN_SYMBOLS / 60:.1f} min")
    print()

    results = backfill(symbols, api_key, store, dry_run=args.dry_run)

    print()
    print("SUMMARY")
    print(f"  {'symbol':<14}{'social_volume':>14}{'social_sentiment':>17}{'galaxy_score':>13}")
    for sym, m in results.items():
        print(f"  {sym:<14}{m.get('social_volume', 0):>14}{m.get('social_sentiment', 0):>17}{m.get('galaxy_score', 0):>13}")
    grand = sum(sum(m.values()) for m in results.values())
    print(f"  {'TOTAL new points':<14}{grand:>44}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
