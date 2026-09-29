# intent: the OPERATOR-DRIVEN bulk OHLCV backbone — one CLI that bulk-downloads YEARS of klines from the FREE
# Binance Vision public archive (https://data.binance.vision, the static archive host — NOT the geo-blocked
# api.binance.com REST) into the existing PIT-honest bar cache, for many symbols × timeframes × a date range.
# Inputs: symbols, --spot/--perp, --start/--end UTC dates, --timeframes. Outputs: append-merged
# `<dir>/<venue>/<symbol>_<tf>.json` caches + a per-target append-count summary. Invariants: COMPOSES
# cosmu.ingest.bars (BinanceVisionBarBackfiller, bar_cache_path, read/write_bars_cache) — NEVER re-implements
# the fetch/parse/merge; idempotent (a re-run writes 0 and an already-covered target is SKIPPED without a
# network hit); no fabrication (a 404 month is a skipped gap, never zero-filled); caches never shrink (atomic
# append-merge on ts); never emits a future ts. The DOWNLOAD run is heavy/local — but the code + an OFFLINE
# deterministic test (inject `_fetcher`) are complete here. No API key, ever.

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from cosmu.ingest.bars import (
    BinanceVisionBarBackfiller,
    bar_cache_path,
    read_cached_bars,
    write_bars_cache,
)

__all__ = [
    "BackfillTargetResult",
    "VISION_VENUE",
    "backfill_vision_bars",
    "main",
]

# The on-disk venue dir per market — the SAME layout the live providers + the managed `verify` coverage read,
# so a Vision bulk pull and a runtime fetch land in one cache (spot vs the USDⓈ-M perpetual-futures tree).
VISION_VENUE = {"spot": "binance", "perp": "binanceperp"}

# Default operator cache root (mirrors cosmu.ingest.manage.DEFAULT_MARKET_DATA_DIR) and the timeframes the
# research stack actually backtests on. Daily + 1h is the bulk backbone; 1m is intraday/microstructure plumbing.
DEFAULT_MARKET_DATA_DIR = ".cosmu/market_data"
DEFAULT_TIMEFRAMES = ("1d", "1h")


@dataclass(frozen=True)
class BackfillTargetResult:
    """Outcome for ONE (market, symbol, timeframe) bulk pull — the unit the CLI summary prints."""

    market: str
    symbol: str
    timeframe: str
    new_bars: int          # genuinely-new bars merged into the cache (0 == fully idempotent re-run)
    cached_bars: int       # total bars on disk after the merge
    skipped: bool          # True == already covered, so NO archive was downloaded (the idempotent fast path)


def _date_to_start_ms(d: date) -> int:
    """UTC midnight of `d` in ms — the open_time of the first bar that opens on this day."""
    return int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp() * 1000)


def _date_to_end_ms(d: date) -> int:
    """Last ms of `d` UTC (23:59:59.999) — the inclusive end of the window so we keep the day's last bar
    without ever requesting a bar whose open_time is the next day."""
    return int(datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=UTC).timestamp() * 1000) + 999


def _is_covered(path: Path, start_ms: int, end_ms: int, timeframe: str) -> bool:
    """Idempotent fast path: True if the on-disk cache ALREADY spans `[start_ms, end_ms]` densely enough that a
    re-download would add nothing. Vision has real gaps (a listing that started later, exchange maintenance), so
    we can never hit 100% of the theoretical bar count — we use a conservative 95% coverage threshold over the
    window, exactly like the intraday cache. A brand-new (0-bar) target is never 'covered', so it always fetches."""
    from cosmu.ingest.bars import TIMEFRAME_MS

    cached = read_cached_bars(path)
    in_window = [b for b in cached if start_ms <= int(b.ts.timestamp() * 1000) <= end_ms]
    if not in_window:
        return False
    step = TIMEFRAME_MS.get(timeframe, TIMEFRAME_MS["1d"])
    expected = int((end_ms - start_ms) / step) + 1   # theoretical max bars in the window (no gaps)
    return len(in_window) >= expected * 0.95


def backfill_vision_bars(
    symbols: list[str],
    *,
    market: str = "spot",
    start: date,
    end: date,
    timeframes: tuple[str, ...] = DEFAULT_TIMEFRAMES,
    market_data_dir: Path | str = DEFAULT_MARKET_DATA_DIR,
    force: bool = False,
    sleep_s: float = 0.2,
    _fetcher: Callable[[str], bytes | None] | None = None,
) -> list[BackfillTargetResult]:
    """Bulk-backfill OHLCV from Binance Vision for every (symbol × timeframe) into the PIT-honest bar cache.

    Composes `BinanceVisionBarBackfiller` (one zipped CSV per month) — this function only orchestrates the
    symbol/timeframe/date-range loop, the idempotent skip, and the cache write. Returns one
    `BackfillTargetResult` per target (caller prints the summary).

    Args:
        symbols:         Binance symbols, e.g. ["BTCUSDT", "ETHUSDT"].
        market:          "spot" → data/spot tree; "perp" → the USDⓈ-M data/futures/um tree.
        start:           First UTC date (inclusive).
        end:             Last UTC date (inclusive); clamped to today (no future archives requested).
        timeframes:      Kline intervals to pull, e.g. ("1d", "1h").
        market_data_dir: Cache root; per-venue dir + `<symbol>_<tf>.json` land under it.
        force:           Re-download even if the window is already cached (default: skip covered targets).
        sleep_s:         Politeness delay between live archive downloads (ignored when `_fetcher` is injected).
        _fetcher:        Inject the archive HTTP fetch for OFFLINE tests — `(url) -> bytes | None`
                         (None == 404/missing). Tests replay a zipped-CSV fixture, never touching the network.
    """
    if market not in VISION_VENUE:
        raise ValueError(f"market must be one of {sorted(VISION_VENUE)}, got {market!r}")
    today = datetime.now(UTC).date()
    if end > today:
        end = today
    if start > end:
        raise ValueError(f"start {start} is after end {end}")

    start_ms = _date_to_start_ms(start)
    end_ms = _date_to_end_ms(end)
    venue_dir = Path(market_data_dir) / VISION_VENUE[market]
    backfiller = BinanceVisionBarBackfiller(market, sleep_s=sleep_s, _fetcher=_fetcher)

    results: list[BackfillTargetResult] = []
    for symbol in symbols:
        for timeframe in timeframes:
            path = bar_cache_path(venue_dir, symbol, timeframe)
            if not force and _is_covered(path, start_ms, end_ms, timeframe):
                results.append(
                    BackfillTargetResult(
                        market=market, symbol=symbol, timeframe=timeframe,
                        new_bars=0, cached_bars=len(read_cached_bars(path)), skipped=True,
                    )
                )
                continue
            bars = backfiller.fetch_history(symbol, timeframe, start_ms=start_ms, end_ms=end_ms)
            new = write_bars_cache(path, bars) if bars else 0
            results.append(
                BackfillTargetResult(
                    market=market, symbol=symbol, timeframe=timeframe,
                    new_bars=new, cached_bars=len(read_cached_bars(path)), skipped=False,
                )
            )
    return results


def _parse_date(value: str) -> date:
    """Parse a `YYYY-MM-DD` UTC date (argparse type), with a clear error for a malformed value."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC).date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected a YYYY-MM-DD date, got {value!r}") from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="binance-vision-backfill",
        description=(
            "Bulk-download keyless OHLCV history from the FREE Binance Vision archive "
            "(https://data.binance.vision) into the PIT-honest bar cache. Idempotent: a re-run, or a target "
            "whose window is already cached, downloads nothing."
        ),
    )
    parser.add_argument("symbols", nargs="+", help="Binance symbols, e.g. BTCUSDT ETHUSDT")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--spot", dest="market", action="store_const", const="spot", help="spot market (default)")
    group.add_argument("--perp", dest="market", action="store_const", const="perp", help="USDⓈ-M perpetual futures")
    parser.set_defaults(market="spot")
    parser.add_argument("--start", type=_parse_date, required=True, help="first UTC date, YYYY-MM-DD (inclusive)")
    parser.add_argument(
        "--end", type=_parse_date, default=None,
        help="last UTC date, YYYY-MM-DD (inclusive; default = today, clamped to today)",
    )
    parser.add_argument(
        "--timeframes", default=",".join(DEFAULT_TIMEFRAMES),
        help=f"comma-separated kline intervals (default: {','.join(DEFAULT_TIMEFRAMES)})",
    )
    parser.add_argument(
        "--market-data-dir", default=DEFAULT_MARKET_DATA_DIR,
        help=f"cache root (default: {DEFAULT_MARKET_DATA_DIR})",
    )
    parser.add_argument("--force", action="store_true", help="re-download even if the window is already cached")
    parser.add_argument("--sleep", type=float, default=0.2, help="seconds between archive downloads (politeness)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    end = args.end or datetime.now(UTC).date()
    timeframes = tuple(tf.strip() for tf in args.timeframes.split(",") if tf.strip())

    print(
        f"Binance Vision bulk backfill · market={args.market} · {args.start} → {end} · "
        f"timeframes={','.join(timeframes)} · symbols={','.join(args.symbols)}"
    )
    results = backfill_vision_bars(
        args.symbols,
        market=args.market,
        start=args.start,
        end=end,
        timeframes=timeframes,
        market_data_dir=args.market_data_dir,
        force=args.force,
        sleep_s=args.sleep,
    )
    new_total = sum(r.new_bars for r in results)
    skipped = sum(1 for r in results if r.skipped)
    for r in results:
        tag = "skip (cached)" if r.skipped else f"+{r.new_bars} new"
        print(f"  {r.market:4} {r.symbol:12} {r.timeframe:4} {tag:16} ({r.cached_bars} cached)")
    print(f"Done · {new_total} new bars across {len(results)} targets · {skipped} already covered")
    return 0


if __name__ == "__main__":
    sys.exit(main())
