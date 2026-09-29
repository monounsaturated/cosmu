# intent: point-in-time-honest 1m kline fetcher+cacher for Binance Vision (data.binance.vision) — the
# intraday/microstructure plumbing for future high-frequency research. Inputs: symbol, date range, cache
# dir. Outputs: ascending de-duped Bar records. Invariants: no fabrication (gap days are skipped, not
# zero-filled), caches never shrink (atomic writes, append-merge on ts), a bar is available only AFTER
# its close_time (point-in-time seam), no API key required, offline-testable via an injected _fetcher.
# Composes cosmu.ingest.bars (BinanceVisionBarBackfiller, bar_cache_path, read_cached_bars, write_bars_cache)
# and cosmu.data.market (Bar) — never re-implements what those modules already own.

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

from cosmu.data.market import Bar
from cosmu.ingest.bars import (
    BinanceVisionBarBackfiller,
    bar_cache_path,
    read_cached_bars,
    write_bars_cache,
)

__all__ = [
    "fetch_1m_bars",
    "IntradayBinanceVisionCache",
]

# A closed 1-minute bar is knowable immediately at its close_time (open_time + 60 s). No additional lag
# is applied beyond the bar's own close — this is the tightest point-in-time contract we can declare for
# exchange-sourced klines.
TIMEFRAME = "1m"
_TIMEFRAME_MS = 60_000  # one 1m bar = 60 000 ms


def _date_to_start_ms(d: date) -> int:
    """UTC midnight of `d` in milliseconds (the start of the first 1m bar that opens on this day)."""
    return int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp() * 1000)


def _date_to_end_ms(d: date) -> int:
    """Last millisecond of the last full 1m bar that CLOSES on `d` UTC (23:59 close_time = open 23:58 + 60 s - 1 ms).
    Clamping to this value ensures we never request a bar whose close_time is in the future."""
    # End of day inclusive: the last 1m bar opens at 23:59:00 and closes at 24:00:00 (== next day 00:00:00).
    # We use 23:59:59.999 as the cap so we include that bar's open_time without requesting a future bar.
    return int(datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=UTC).timestamp() * 1000) + 999


class IntradayBinanceVisionCache:
    """Disk-backed 1m bar cache for a single symbol. Calls BinanceVisionBarBackfiller for any missing day
    range and merges into a per-symbol JSON cache (atomic writes, never shrinks). Designed to be composed
    into a pipeline or called directly via `fetch_1m_bars`.

    Offline-testable: inject `_fetcher(url) -> bytes | None` (same contract as BinanceVisionBarBackfiller)
    so tests replay zipped-CSV fixtures without touching the network.
    """

    def __init__(
        self,
        cache_dir: Path | str = ".cosmu/market_data/binance_vision_1m",
        *,
        market: str = "spot",
        _fetcher: Callable[[str], bytes | None] | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.market = market
        self._backfiller = BinanceVisionBarBackfiller(market, _fetcher=_fetcher)

    def fetch(self, symbol: str, start: date, end: date) -> list[Bar]:
        """Return ascending 1m Bars for `symbol` in the closed interval [start, end] (UTC dates).
        Fetches from Binance Vision for any date not yet cached; merges+caches atomically. A gap day
        (Vision 404) is skipped — never zero-filled. `end` is clamped to today to avoid requesting
        future bars. Returns only bars whose open_time falls within [start_ms, end_ms]."""
        today = datetime.now(UTC).date()
        if end > today:
            end = today
        if start > end:
            return []

        path = bar_cache_path(self.cache_dir, symbol, TIMEFRAME)
        cached = read_cached_bars(path)

        # Determine which date range is actually missing.
        # A cached bar's open_time in [start_ms, end_ms] means that day is at least partially covered;
        # we check for the FULL range to decide whether to re-fetch.
        start_ms = _date_to_start_ms(start)
        end_ms = _date_to_end_ms(end)

        cached_in_window = [b for b in cached if start_ms <= int(b.ts.timestamp() * 1000) <= end_ms]
        expected_bars = int((end_ms - start_ms) / _TIMEFRAME_MS) + 1  # theoretical max (no gaps)

        # Re-fetch only if we have fewer bars than expected. Vision gaps (exchange closed, missing archive)
        # mean we can never truly fill to 100%, so we use a conservative threshold: if we have at least
        # 95% of the theoretical max we consider the range cached. This avoids re-fetching on every call
        # over holiday/maintenance gaps. For a brand-new range with 0 cached bars we always fetch.
        coverage_threshold = 0.95
        if cached_in_window and len(cached_in_window) >= expected_bars * coverage_threshold:
            return _slice(cached, start_ms, end_ms)

        fetched = self._backfiller.fetch_history(symbol, TIMEFRAME, start_ms=start_ms, end_ms=end_ms)
        if fetched:
            write_bars_cache(path, fetched)
            # Re-read the merged cache so we serve the authoritative on-disk state.
            cached = read_cached_bars(path)

        return _slice(cached, start_ms, end_ms)


def _slice(bars: list[Bar], start_ms: int, end_ms: int) -> list[Bar]:
    """Return only bars whose open_time is within [start_ms, end_ms]."""
    return [b for b in bars if start_ms <= int(b.ts.timestamp() * 1000) <= end_ms]


def fetch_1m_bars(
    symbol: str,
    start: date,
    end: date,
    *,
    cache_dir: Path | str = ".cosmu/market_data/binance_vision_1m",
    market: str = "spot",
    _fetcher: Callable[[str], bytes | None] | None = None,
) -> list[Bar]:
    """Convenience wrapper — fetch + cache 1m Binance Vision klines for `symbol` over [start, end] UTC dates.

    Returns ascending, de-duped `Bar` records. Gap days (Vision 404, e.g. listing started later) are
    skipped — never zero-filled. `end` is clamped to today (no future bars). Caches on disk atomically
    so repeated calls for the same window pay no network cost once covered.

    Args:
        symbol:    Binance spot symbol (e.g. "BTCUSDT", "ETHUSDT").
        start:     First UTC date (inclusive).
        end:       Last UTC date (inclusive); clamped to today.
        cache_dir: Root cache directory (per-symbol JSON files land here).
        market:    "spot" (default) or "perp" (USDM futures tree).
        _fetcher:  Override the HTTP fetch fn for offline tests. Same contract as
                   BinanceVisionBarBackfiller: `(url: str) -> bytes | None` (None == 404/missing).

    Example::

        from datetime import date
        from cosmu.data.intraday_binance_vision import fetch_1m_bars

        bars = fetch_1m_bars("BTCUSDT", date(2024, 1, 1), date(2024, 1, 3))
        # bars[0].ts == datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    """
    cache = IntradayBinanceVisionCache(cache_dir, market=market, _fetcher=_fetcher)
    return cache.fetch(symbol, start, end)
