# intent: the MANAGED bar layer — paginated multi-venue OHLCV history (Binance + Kraken via ccxt) plus a
# dedup-merge bar cache, the bar analogue of the alt-data backfill+store; inputs: ccxt OHLCV pages (or an
# injected fetcher in tests); outputs: ascending de-duped Bars + an append-merged `<symbol>_<tf>.json` cache
# the coverage report reads; invariants: idempotent (merge dedups on ts — a re-run writes 0), point-in-time
# (a closed bar is known at its close; the walk only moves forward so a re-run is byte-identical), ccxt is
# OPTIONAL (no ccxt + no injected fetcher → [] = honest, never a fabricated bar), offline-testable. This
# composes `cosmu.data.market` (Bar + its parse helpers) — it never re-implements bar parsing.

from __future__ import annotations

import csv
import io
import json
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from cosmu.data.market import Bar, _bar_from_ccxt, _bar_from_json, _ccxt_symbol, _ssl_context

__all__ = [
    "Bar",
    "BinanceVisionBarBackfiller",
    "BulkTailBarBackfiller",
    "CcxtBarBackfiller",
    "StooqBarBackfiller",
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


def _klines_to_ohlcv(rows: list[list]) -> list[list]:
    """Binance REST kline rows → ccxt OHLCV shape `[ms, open, high, low, close, volume]` (floats), so a REST
    page is treated identically to a ccxt page by the paginated walk + `_bar_from_ccxt`. Pure (no network)."""
    return [[int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])] for r in rows]


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

    # our exchange symbol (BTCUSDT) → the venue's ccxt unified symbol. Bybit + OKX use the same BASE/USDT
    # unified shape as Binance, so the crypto-deep venues come for free (more spot price history per asset).
    _VENUE_SYMBOL = {
        "binance": _ccxt_symbol,
        "kraken": _kraken_ccxt_symbol,
        "bybit": _ccxt_symbol,
        "okx": _ccxt_symbol,
    }

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
        """ccxt first; if ccxt is absent or returns nothing, fall back to the keyless Binance REST klines
        path (stdlib urllib) so `backfill bars` works WITHOUT ccxt installed — the same self-healing the
        runtime `BinanceSpotOHLCVProvider` already has. Non-Binance venues stay ccxt-only (Binance is the
        primary deep-history venue; its public REST needs no key, mirroring the funding backfill path)."""
        rows = self._fetch_ccxt(symbol, timeframe, since, limit)
        if rows or self.exchange_id != "binance":
            return rows
        return self._fetch_rest_binance(symbol, timeframe, since, limit)

    def _fetch_ccxt(self, symbol: str, timeframe: str, since: int, limit: int) -> list[list]:
        try:
            import ccxt  # type: ignore[import-not-found]
        except ImportError:
            return []  # no ccxt → fall through to the REST path (never a fabricated bar)
        exchange = getattr(ccxt, self.exchange_id)({"enableRateLimit": True})
        market_symbol = self._VENUE_SYMBOL.get(self.exchange_id, _ccxt_symbol)(symbol)
        return exchange.fetch_ohlcv(market_symbol, timeframe=timeframe, since=since, limit=limit)

    def _fetch_rest_binance(self, symbol: str, timeframe: str, since: int, limit: int) -> list[list]:
        """Keyless Binance public klines via stdlib urllib — the bar analogue of the funding REST path.
        Returns ccxt-shaped OHLCV rows `[ms, open, high, low, close, volume]` ascending from `since`; any
        transport/parse failure → [] (honest empty, never a fabricated bar)."""
        query = urllib.parse.urlencode(
            {"symbol": symbol, "interval": timeframe, "startTime": int(since), "limit": min(max(limit, 1), 1000)}
        )
        url = f"https://api.binance.com/api/v3/klines?{query}"
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
                rows = json.loads(resp.read().decode("utf-8"))
        except Exception:  # noqa: BLE001 — any network/parse failure degrades to empty, never fabricates a bar
            return []
        return _klines_to_ohlcv(rows)

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


def _stooq_bar_symbol(symbol: str) -> str:
    """Our symbol → the Stooq native ticker. An already-native ticker (`spy.us`, `^spx`, `eurusd`) passes
    through; a known FX/metal pair lower-cases; everything else is assumed a US equity (`SPY` → `spy.us`)."""
    if "." in symbol or symbol.startswith("^"):
        return symbol.lower()
    if symbol.upper() in {"EURUSD", "USDJPY", "GBPUSD", "XAUUSD", "XAGUSD"}:
        return symbol.lower()
    return f"{symbol.lower()}.us"


class StooqBarBackfiller:
    """FREE, keyless DAILY OHLCV history for non-crypto assets (stocks / FX / metals / indexes) via Stooq's
    public CSV — the bar analogue of `CcxtBarBackfiller` for the venues ccxt does not cover. Same
    `fetch_history(symbol, timeframe, *, start_ms, end_ms)` seam so the managed backfill path treats it like any
    other bar venue. Stooq serves DAILY bars only, so a non-`1d` timeframe → [] (honest). Each bar is stamped
    at its own close (point-in-time; the walk is just a window filter, so a re-run is byte-identical). No ccxt,
    no key. Offline-testable: inject `_fetcher(url) -> str` (canned CSV; no live network in tests)."""

    def __init__(self, *, _fetcher: Callable[[str], str] | None = None) -> None:
        from cosmu.data.sources.multiasset import StooqDailyProvider

        # Reuse the Stooq CSV transport + parser (one fetcher, no duplication).
        self._provider = StooqDailyProvider(_fetcher=_fetcher) if _fetcher is not None else StooqDailyProvider()

    def fetch_history(self, symbol: str, timeframe: str, *, start_ms: int, end_ms: int | None = None) -> list[Bar]:
        from cosmu.data.sources.multiasset import parse_stooq_csv, stooq_daily_url

        if timeframe != "1d":
            return []  # Stooq daily CSV serves 1d bars only
        import time

        end = int(end_ms) if end_ms is not None else int(time.time() * 1000)
        text = self._provider._fetcher(stooq_daily_url(_stooq_bar_symbol(symbol)))
        out: list[Bar] = []
        for r in parse_stooq_csv(text):
            ts_ms = int(r["ts"].timestamp() * 1000)  # type: ignore[union-attr]
            if ts_ms < start_ms or ts_ms > end:
                continue
            out.append(Bar(
                ts=r["ts"], open=Decimal(str(r["open"])), high=Decimal(str(r["high"])),
                low=Decimal(str(r["low"])), close=Decimal(str(r["close"])), volume=Decimal(str(r["volume"])),
            ))
        out.sort(key=lambda b: b.ts)
        return out


def _vision_ms(value: int) -> int:
    """Normalize a Binance Vision kline open_time to MILLISECONDS. Vision klines are ms, but some 2025+ archives
    stamp microseconds; a ms epoch stays < 1e15 until year ~33658 while a µs epoch is ≥ 1e15 from 2001 on, so the
    threshold cleanly disambiguates without ever mangling a real ms timestamp."""
    return value // 1000 if value >= 1_000_000_000_000_000 else value


def _iter_months(start: datetime, end: datetime) -> Iterator[str]:
    """Yield `YYYY-MM` labels for every month from `start`'s month through `end`'s month, inclusive (ascending)."""
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield f"{y:04d}-{m:02d}"
        m += 1
        if m > 12:
            m, y = 1, y + 1


def _iter_days(start: datetime, end: datetime) -> Iterator[str]:
    """Yield `YYYY-MM-DD` labels for every UTC day from `start`'s date through `end`'s date, inclusive."""
    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    last = end.replace(hour=0, minute=0, second=0, microsecond=0)
    while day <= last:
        yield f"{day.year:04d}-{day.month:02d}-{day.day:02d}"
        day += timedelta(days=1)


class BinanceVisionBarBackfiller:
    """FREE, keyless BULK OHLCV history from Binance Vision (https://data.binance.vision) — the bulk-backbone
    analogue of `CcxtBarBackfiller`. Where ccxt/REST paginate a few hundred bars per call, Vision serves a whole
    MONTH as one zipped CSV, so a single `fetch_history` pulls years of 1m/1h/1d bars per symbol without a key.
    Monthly archives cover the bulk; DAILY archives fill the current partial month (the month monthly hasn't
    published yet). `market="spot"` reads `data/spot/monthly/klines/...`; `market="perp"` reads the USDⓈ-M
    `data/futures/um/monthly/klines/...` tree. Same `fetch_history(symbol, timeframe, *, start_ms, end_ms)` seam
    as every other backfiller, so the managed path treats it like any bar venue. A 404 on a month is a GAP (the
    listing started later, or the month isn't published yet) → skip, never zero-fill. Never emits a future ts.
    Offline-testable: inject `_fetcher(url) -> bytes | None` returning the raw zip bytes (None == 404/missing); a
    test replays a zipped-CSV fixture and never touches the network (live runs sleep `sleep_s` between archives
    to stay polite)."""

    _BASE = "https://data.binance.vision"

    def __init__(
        self,
        market: str = "spot",
        *,
        sleep_s: float = 0.2,
        _fetcher: Callable[[str], bytes | None] | None = None,
    ) -> None:
        if market not in ("spot", "perp"):
            raise ValueError(f"market must be 'spot' or 'perp', got {market!r}")
        self.market = market
        self.sleep_s = sleep_s
        self._live = _fetcher is None  # only the live path sleeps between archive downloads
        self._fetcher = _fetcher or self._fetch

    def _root(self) -> str:
        """The Vision path root for this market: spot vs the USDⓈ-M perpetual-futures tree."""
        return "data/spot" if self.market == "spot" else "data/futures/um"

    def _archive_url(self, symbol: str, timeframe: str, period: str, label: str) -> str:
        """One archive URL. `period` ∈ {monthly, daily}; `label` is `YYYY-MM` (monthly) or `YYYY-MM-DD` (daily)."""
        return f"{self._BASE}/{self._root()}/{period}/klines/{symbol}/{timeframe}/{symbol}-{timeframe}-{label}.zip"

    def _fetch(self, url: str) -> bytes | None:
        """Keyless HTTPS GET of one archive via stdlib urllib. A 404 (or any transport failure) → None so the
        caller skips that month as a gap — never a fabricated bar."""
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=60, context=_ssl_context()) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None  # month not published / listing started later → gap, skip (never zero-fill)
            return None
        except Exception:  # noqa: BLE001 — any transport failure degrades to a skipped gap, never a fabricated bar
            return None

    def _parse_zip(self, raw: bytes) -> list[list]:
        """Unzip → parse the Binance kline CSV → ccxt-shaped `[ms, o, h, l, c, v]` rows. Columns are
        `open_time, open, high, low, close, volume, close_time, ...`; we keep the first six. A leading header row
        (`open_time,...`) is detected by a non-numeric first cell and skipped. Pure (no network)."""
        rows: list[list] = []
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for name in zf.namelist():
                if not name.endswith(".csv"):
                    continue
                with zf.open(name) as fh:
                    for cells in csv.reader(io.TextIOWrapper(fh, encoding="utf-8")):
                        if len(cells) < 6:
                            continue
                        try:
                            ts = _vision_ms(int(cells[0]))
                        except ValueError:
                            continue  # header row → skip
                        rows.append([ts, cells[1], cells[2], cells[3], cells[4], cells[5]])
        return _klines_to_ohlcv(rows)

    def _collect(self, url: str, start: int, end: int, seen: set[int], out: list[Bar]) -> None:
        """Fetch + parse ONE archive, appending its in-window, not-yet-seen bars to `out`. A missing archive
        (None) is a gap → skipped. The live path sleeps after each download to stay polite."""
        import time

        raw = self._fetcher(url)
        if self._live and self.sleep_s:
            time.sleep(self.sleep_s)
        if not raw:
            return
        for row in self._parse_zip(raw):
            ts_ms = int(row[0])
            if ts_ms < start or ts_ms > end or ts_ms in seen:
                continue
            seen.add(ts_ms)
            out.append(_bar_from_ccxt(row))

    def fetch_history(self, symbol: str, timeframe: str, *, start_ms: int, end_ms: int | None = None) -> list[Bar]:
        """Download monthly archives for every COMPLETE month in `[start_ms, end_ms]` plus daily archives for the
        current partial month, then return ascending, de-duped Bars. `end_ms` (default now) is clamped to now so a
        future ts is never emitted. A 404 month is a gap (skipped, not zero-filled)."""
        import time

        now_ms = int(time.time() * 1000)
        end = min(int(end_ms), now_ms) if end_ms is not None else now_ms
        start = int(start_ms)
        if end < start:
            return []
        start_dt = datetime.fromtimestamp(start / 1000, tz=UTC)
        end_dt = datetime.fromtimestamp(end / 1000, tz=UTC)
        current_month = f"{end_dt.year:04d}-{end_dt.month:02d}"

        seen: set[int] = set()
        out: list[Bar] = []
        # Bulk: one monthly archive per COMPLETE month (the current partial month is daily-only — its monthly
        # archive isn't published yet, so fetching it would 404).
        for label in _iter_months(start_dt, end_dt):
            if label == current_month:
                continue
            self._collect(self._archive_url(symbol, timeframe, "monthly", label), start, end, seen, out)
        # Current partial month: daily archives, from the later of start or the 1st of this month through end.
        month_first = end_dt.replace(day=1)
        for label in _iter_days(max(start_dt, month_first), end_dt):
            self._collect(self._archive_url(symbol, timeframe, "daily", label), start, end, seen, out)
        out.sort(key=lambda b: b.ts)
        return out


class BulkTailBarBackfiller:
    """Compose a BULK backfiller (Binance Vision archives — years of keyless history) with a recent-TAIL
    backfiller (ccxt/REST — the last days/hours Vision hasn't archived yet) behind ONE `fetch_history` seam, so
    the manager sees a single venue that returns deep history AND a fresh tail. The tail walk resumes one step
    before the last bulk bar (a small overlap so a boundary bar is never dropped) and the two sets are merged,
    deduped on ts with the BULK bar authoritative. If bulk returns nothing (e.g. a symbol Vision hasn't listed)
    the tail still runs from `start_ms` — honest degradation, never a fabricated bar."""

    def __init__(self, bulk: object, tail: object) -> None:
        self._bulk = bulk
        self._tail = tail

    def fetch_history(self, symbol: str, timeframe: str, *, start_ms: int, end_ms: int | None = None) -> list[Bar]:
        bulk = self._bulk.fetch_history(symbol, timeframe, start_ms=start_ms, end_ms=end_ms)  # type: ignore[attr-defined]
        step = TIMEFRAME_MS.get(timeframe, TIMEFRAME_MS["1d"])
        if bulk:
            last_ms = int(bulk[-1].ts.timestamp() * 1000)
            tail_start = max(int(start_ms), last_ms - step)  # small overlap → no boundary gap
        else:
            tail_start = int(start_ms)
        tail = self._tail.fetch_history(symbol, timeframe, start_ms=tail_start, end_ms=end_ms)  # type: ignore[attr-defined]
        merged: dict[int, Bar] = {int(b.ts.timestamp() * 1000): b for b in bulk}
        for b in tail:
            merged.setdefault(int(b.ts.timestamp() * 1000), b)  # bulk wins on overlap (Vision is authoritative)
        return sorted(merged.values(), key=lambda b: b.ts)


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
