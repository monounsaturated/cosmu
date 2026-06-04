#!/usr/bin/env python3
# intent: the post-merge funding-depth CLI — backfill ≥1 year of REAL Binance USDⓈ-M funding-rate history
# across the top perp symbols into the append-only point-in-time alt-data store, so the honest carry/neutral
# Gate has real signal instead of the thin ~2mo/2-symbol prod slice; inputs: free paginated Binance
# `fapi/v1/fundingRate` (NO key), the operator's store (Postgres in prod, JSONL locally); outputs: deduped
# funding points + a per-symbol span report; invariants: append-only + idempotent (dedup on
# provider/symbol/metric/ts — a re-run writes 0), each symbol fetched ONCE (the provider paginates
# internally — no redundant external calls), ZERO API keys required.
#
# Run:
#   PYTHONPATH=apps/engine python3 scripts/backfill_funding.py                 # top-20 USDT perps, ~400 days
#   PYTHONPATH=apps/engine python3 scripts/backfill_funding.py --days 730      # 2 years
#   PYTHONPATH=apps/engine python3 scripts/backfill_funding.py --symbols BTCUSDT,ETHUSDT
#   PYTHONPATH=apps/engine python3 scripts/backfill_funding.py --quote USDC    # USDC-margined perps
#   PYTHONPATH=apps/engine python3 scripts/backfill_funding.py --store jsonl --root .cosmu/altdata --dry-run
#
# This is CODE: the actual prod RUN happens post-merge via cron/manual. Offline-safe (no network in tests).

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Allow `python3 scripts/backfill_funding.py` without an explicit PYTHONPATH (mirrors the documented run).
_ENGINE = Path(__file__).resolve().parents[1] / "apps" / "engine"
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from cosmu.data.altdata import AltDataStore, BinanceFundingHistoryProvider  # noqa: E402
from cosmu.ingest.pipeline import BackfillResult, backfill_funding  # noqa: E402

# Top ~20 Binance USDⓈ-M perp BASE assets by liquidity. The quote (USDT default; USDC via --quote) is
# appended at runtime. We default to USDT because that is the perp the gate's carry/neutral arm actually
# reads (BTCUSDT/ETHUSDT funding) AND the only quote with ≥1yr of funding history for the whole list —
# many USDC perps launched recently and have far shorter spans. --quote USDC switches the whole list.
TOP_PERP_BASES: tuple[str, ...] = (
    "BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT",
    "TRX", "LTC", "BCH", "NEAR", "UNI", "APT", "FIL", "ARB", "OP", "INJ",
)


def _symbols(args: argparse.Namespace) -> list[str]:
    if args.symbols:
        return [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    bases = TOP_PERP_BASES[: args.top]
    return [f"{base}{args.quote.upper()}" for base in bases]


def _build_store(args: argparse.Namespace):  # noqa: ANN202
    """JSONL store (local/offline) or the same backend the API uses (Postgres in prod) — picked by --store."""
    if args.store == "jsonl":
        return AltDataStore(args.root)
    # `auto` → reuse the ingest CLI's backend selection (Postgres URL → PgAltDataStore, else JSONL).
    from cosmu.ingest.run import _default_store

    store = _default_store()
    if not hasattr(store, "append"):  # a knowledge Store needs wrapping as the DB-backed alt-data store
        from cosmu.data.altdata import PgAltDataStore

        store = PgAltDataStore(store)
    return store


def _report(results: dict[str, BackfillResult]) -> int:
    total_written = sum(r.written for r in results.values())
    total_points = sum(r.total for r in results.values())
    print("FUNDING BACKFILL — Binance USDⓈ-M fundingRate history (free, no key)")
    print(f"  {'symbol':<12}{'new':>8}{'total':>8}{'days':>8}  span")
    for sym, r in results.items():
        span = f"{r.start.date()} → {r.end.date()}" if r.start and r.end else "(no data)"
        print(f"  {sym:<12}{r.written:>8}{r.total:>8}{r.span_days:>8.0f}  {span}")
    n_year_plus = sum(1 for r in results.values() if r.span_days >= 365)
    print(f"  {'TOTAL':<12}{total_written:>8}{total_points:>8}")
    print(f"  symbols with ≥1yr span: {n_year_plus}/{len(results)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill ≥1yr of Binance funding history into the alt-data store.")
    parser.add_argument("--symbols", default="", help="comma-separated explicit symbols (overrides --top/--quote)")
    parser.add_argument("--top", type=int, default=20, help="number of top perp bases to use (default 20)")
    parser.add_argument("--quote", default="USDT", help="quote asset appended to each base (default USDT; e.g. USDC)")
    parser.add_argument("--days", type=int, default=400, help="lookback window in days (default 400 → ≥1yr)")
    parser.add_argument("--store", choices=("auto", "jsonl"), default="auto", help="store backend (default auto: prod Postgres / local JSONL)")
    parser.add_argument("--root", default=".cosmu/altdata", help="JSONL store root (only with --store jsonl)")
    parser.add_argument("--sleep", type=float, default=0.25, help="seconds between live pages (politeness)")
    parser.add_argument("--dry-run", action="store_true", help="fetch + report spans but DO NOT write to the store")
    args = parser.parse_args(argv)

    symbols = _symbols(args)
    start_ms = int((time.time() - args.days * 86400) * 1000)
    provider = BinanceFundingHistoryProvider(sleep_s=args.sleep)

    if args.dry_run:
        # Fetch + measure spans, but never touch the store (no append) — a safe pre-flight.
        results: dict[str, BackfillResult] = {}
        for sym in symbols:
            pts = provider.fetch_history(sym, start_ms=start_ms)
            results[sym] = BackfillResult(
                symbol=sym, written=0, total=len(pts),
                start=pts[0].ts if pts else None, end=pts[-1].ts if pts else None,
            )
        print("(dry-run: nothing written)")
        return _report(results)

    store = _build_store(args)
    results = backfill_funding(store, provider, symbols, start_ms=start_ms)
    return _report(results)


if __name__ == "__main__":
    raise SystemExit(main())
