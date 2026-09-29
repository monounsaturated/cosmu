#!/usr/bin/env python3
# intent: ONE convenience entrypoint to backfill the FREE multi-asset data this PR adds — crypto-deep bars
# (Bybit/OKX), non-crypto daily bars (stocks/FX/metals via Stooq), and the cross-asset alt price levels —
# composing the managed-data surface (cosmu.ingest.manage.DataManager); inputs: NO keys (every source is
# free + key-gated-to-[] where a key would help); outputs: append/backfill counts into the alt store + bar
# cache; invariants: idempotent + point-in-time (a re-run writes 0), each (source,symbol,window) fetched
# ONCE, offline-safe (the real RUN happens post-merge via cron/manual). Thin wrapper — no logic of its own.
#
# Run (from the repo root):
#   PYTHONPATH=apps/engine python3 scripts/backfill_multiasset.py --days 730
#   PYTHONPATH=apps/engine python3 scripts/backfill_multiasset.py --crypto BTCUSDT,ETHUSDT --equities SPY,AAPL

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running without an explicit PYTHONPATH (mirrors scripts/manage_data.py).
_ENGINE = Path(__file__).resolve().parents[1] / "apps" / "engine"
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from cosmu.ingest.manage import DataManager, _report_bars  # noqa: E402

# Free non-crypto daily-bar symbols (Stooq tickers / aliases the bar mapper understands).
DEFAULT_EQUITIES = ("SPY", "QQQ", "AAPL", "MSFT")
# Crypto-deep ccxt venues this PR enables beyond Binance/Kraken.
CRYPTO_VENUES = ("bybit", "okx")


def _csv(arg: str, default: tuple[str, ...]) -> list[str]:
    return [s.strip().upper() for s in arg.split(",") if s.strip()] if arg else list(default)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill the free multi-asset data (crypto-deep + stocks/FX/metals).")
    parser.add_argument("--days", type=int, default=730, help="lookback window in days (default 730 → ~2yr)")
    parser.add_argument("--crypto", default="", help="crypto symbols for Bybit/OKX bars (default BTCUSDT,ETHUSDT)")
    parser.add_argument("--equities", default="", help="Stooq daily-bar symbols (default SPY,QQQ,AAPL,MSFT)")
    args = parser.parse_args(argv)

    crypto = _csv(args.crypto, ("BTCUSDT", "ETHUSDT"))
    equities = _csv(args.equities, DEFAULT_EQUITIES)

    mgr = DataManager()

    for venue in CRYPTO_VENUES:
        print(f"\n=== crypto-deep bars: {venue} ===")
        result = mgr.backfill(f"bars:{venue}", days=args.days, symbols=crypto)
        _report_bars(result["results"])

    print("\n=== non-crypto daily bars: stooq (stocks/FX/metals) ===")
    result = mgr.backfill("bars:stooq", days=args.days, symbols=equities)
    _report_bars(result["results"])

    print("\n=== cross-asset alt price levels (metals/commodities/equity-index/FX) ===")
    n = mgr.fetch("multiasset", crypto)
    print(f"fetched multiasset: {n} points")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
