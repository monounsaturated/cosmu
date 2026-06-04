# intent: the MANAGED bar layer — paginated multi-venue OHLCV history (Binance + Kraken via ccxt) plus a
# dedup-merge bar cache, the bar analogue of the alt-data backfill+store; inputs: ccxt OHLCV pages (or an
# injected fetcher in tests); outputs: ascending de-duped Bars + an append-merged `<symbol>_<tf>.json` cache
# the coverage report reads; invariants: idempotent (merge dedups on ts — a re-run writes 0), point-in-time
# (a closed bar is known at its close; the walk only moves forward so a re-run is byte-identical), ccxt is
# OPTIONAL (no ccxt + no injected fetcher → [] = honest, never a fabricated bar), offline-testable. This
# composes `cosmu.data.market` (Bar + its parse helpers) — it never re-implements bar parsing.

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from cosmu.data.market import Bar, _bar_from_ccxt, _bar_from_json, _ccxt_symbol

__all__ = [
    "Bar",
    "CcxtBarBackfiller",
    "TIMEFRAME_MS",
    "bar_cache_path",
    "read_cached_bars",
    "write_bars_cache",
]

# Timeframe → milliseconds, for walking a paginated bar-history cursor forward.
TIMEFRAME_MS: dict[str, int] = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000, "1w": 604_800_000,
}


def _kraken_ccxt_symbol(symbol: str) -> str:
    """Kraken's deepest spot books are USD, so a USDT pair maps to the USD book (mirrors market._kraken_pair)."""
    if "/" in symbol:
        return symbol
    if symbol.endswith("USDT"):
        return f"{symbol[:-4]}/USD"
    if symbol.endswith("USD"):
        return f"{symbol[:-3]}/USD"
    return symbol


class CcxtBarBackfiller:
    """Paginated multi-venue OHLCV HISTORY over ccxt (Binance + Kraken) — the bar analogue of
    `BinanceFundingHistoryProvider`. ccxt's `fetch_ohlcv` returns at most a few hundred-to-1000 bars per
    call; this walks `since` forward one page at a time until it reaches `end_ms` (or now), de-duping on bar
    `ts` so an overlapping page boundary never double-counts. ONE call yields years of history per
    symbol/timeframe. ccxt is OPTIONAL: with no ccxt installed AND no injected fetcher the history is empty
    ([]) — honest degradation, never a fabricated bar (same contract as market's `_fetch_with_ccxt`).
    Offline-testable: inject `_fetcher(symbol, timeframe, since, limit) -> list[list]` returning ccxt-shaped
    `[ms, open, high, low, close, volume]` rows; tests never touch the network (live runs sleep `sleep_s`
    between pages to stay polite)."""

    # our exchange symbol (BTCUSDT) → the venue's ccxt unified symbol.
    _VENUE_SYMBOL = {"binance": _ccxt_symbol, "kraken": _kraken_ccxt_symbol}

    def __init__(
        self,
        exchange_id: str = "binance",
        *,
        page_limit: int = 720,
        sleep_s: float = 0.25,
        max_pages: int = 5000,
        _fetcher: Callable[[str, str, int, int], list[list]] | None = None,
    ) -> None:
        self.exchange_id = exchange_id.lower()
        self.page_limit = max(1, min(page_limit, 1000))
        self.sleep_s = sleep_s
        self.max_pages = max_pages
        self._live = _fetcher is None  # only the live path sleeps between pages
        self._fetcher = _fetcher or self._fetch

    def _fetch(self, symbol: str, timeframe: str, since: int, limit: int) -> list[list]:
        try:
            import ccxt  # type: ignore[import-not-found]
        except ImportError:
            return []  # no ccxt → honest empty (never a fabricated bar)
        exchange = getattr(ccxt, self.exchange_id)({"enableRateLimit": True})
        market_symbol = self._VENUE_SYMBOL.get(self.exchange_id, _ccxt_symbol)(symbol)
        return exchange.fetch_ohlcv(market_symbol, timeframe=timeframe, since=since, limit=limit)

    def fetch_history(self, symbol: str, timeframe: str, *, start_ms: int, end_ms: int | None = None) -> list[Bar]:
        """Walk pages forward from `start_ms` to `end_ms` (default = now). Returns ascending, de-duped Bars.
        A short (<page_limit) page means the history is exhausted → stop. No look-ahead: a bar is stamped at
        its own close time and the walk only moves forward, so a re-run is byte-identical."""
        import time

        step = TIMEFRAME_MS.get(timeframe, TIMEFRAME_MS["1d"])
        end = int(end_ms) if end_ms is not None else int(time.time() * 1000)
        cursor = int(start_ms)
        seen: set[int] = set()
        out: list[Bar] = []
        for _ in range(self.max_pages):
            if cursor > end:
                break
            rows = self._fetcher(symbol, timeframe, cursor, self.page_limit)
            if not rows:
                break
            last_ts = cursor
            for row in rows:
                ts_ms = int(row[0])
                if ts_ms > end:
                    continue
                last_ts = max(last_ts, ts_ms)
                if ts_ms in seen:
                    continue
                seen.add(ts_ms)
                out.append(_bar_from_ccxt(row))
            if len(rows) < self.page_limit:
                break  # last partial page → history exhausted
            nxt = last_ts + step
            if nxt <= cursor:
                break  # no forward progress (defensive against a stuck cursor)
            cursor = nxt
            if self._live and self.sleep_s:
                time.sleep(self.sleep_s)
        out.sort(key=lambda b: b.ts)
        return out


def bar_cache_path(cache_dir: Path | str, symbol: str, timeframe: str) -> Path:
    """The on-disk bar-cache path for one venue dir × symbol × timeframe (the shared `<symbol>_<tf>.json`
    layout every bar provider in `market.py` writes). Centralised so the manager and coverage read/write the
    same files the live providers populate."""
    safe = f"{symbol}_{timeframe}".replace("/", "")
    return Path(cache_dir) / f"{safe}.json"


def read_cached_bars(path: Path | str) -> list[Bar]:
    """Read a bar-cache JSON file into ascending Bars (empty list if absent) — the venue-agnostic reader the
    coverage report uses so it never needs to know which provider wrote the file."""
    p = Path(path)
    if not p.exists():
        return []
    return sorted((_bar_from_json(r) for r in json.loads(p.read_text())), key=lambda b: b.ts)


def write_bars_cache(path: Path | str, bars: list[Bar]) -> int:
    """Append-merge `bars` into the cache at `path`, de-duped on ts (idempotent: a re-run writes 0 new bars).
    Returns the count of genuinely-new bars. The bar analogue of `append_dedup` for the alt store — backfill
    walks deep history then merges it here without ever double-writing an existing bar."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    existing = {b.ts: b for b in read_cached_bars(p)}
    before = len(existing)
    for b in bars:
        existing.setdefault(b.ts, b)
    merged = sorted(existing.values(), key=lambda b: b.ts)
    rows = [
        {"ts": int(b.ts.timestamp() * 1000), "open": str(b.open), "high": str(b.high),
         "low": str(b.low), "close": str(b.close), "volume": str(b.volume)}
        for b in merged
    ]
    p.write_text(json.dumps(rows, separators=(",", ":")))
    return len(merged) - before
