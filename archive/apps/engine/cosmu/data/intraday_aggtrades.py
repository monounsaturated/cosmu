# intent: keyless, point-in-time-honest historical AGGRESSIVE-TRADE-FLOW fetcher from Binance Vision
# (data.binance.vision) — the microstructure plumbing for intraday order-flow research. Reuses the EXACT
# zip-fetch pattern of cosmu.data.intraday_binance_vision / cosmu.ingest.bars.BinanceVisionBarBackfiller,
# just pointed at the daily `aggTrades/` prefix instead of `klines/`. Inputs: symbol, UTC date range, market
# (spot|perp). Outputs: ascending 1-minute FLOW BARS, each carrying the signed-aggressor volume split.
# Invariants:
#   - No API key required; keyless HTTPS GET of immutable daily zips (revision-safe: Vision ships .CHECKSUM).
#   - No fabrication: a 404 day (listing started later / not yet published) is SKIPPED, never zero-filled.
#   - Point-in-time: a 1m flow bar is knowable only AT its close (open_minute + 60s). Each aggTrade is stamped
#     at its own `transact_time` (event time, no revision), bucketed into the minute it occurred in.
#   - Signed aggressor convention is read FROM the data, not guessed: Binance's `is_buyer_maker` flag means
#     `false` => the BUYER was the taker => an aggressive BUY; `true` => the buyer was the maker, the SELLER
#     was the taker => an aggressive SELL. (Confirmed against a live ARBUSDT perp day, 2025-01-15.)
#   - `end` is clamped to today (never request a future day).
#   - Offline-testable: inject `_fetcher(url) -> bytes | None` (None == 404/missing), same contract as
#     BinanceVisionBarBackfiller, so tests replay a zipped-CSV fixture without touching the network.
# This module owns ONLY the aggTrades parse + 1m flow-bar resample; it composes the shared SSL transport
# (cosmu.data.market._ssl_context) and never re-implements bar OHLCV (that stays in ingest/bars.py).

from __future__ import annotations

import csv
import io
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from cosmu.data.market import _ssl_context

__all__ = [
    "FlowBar",
    "AggTradesVisionFetcher",
    "fetch_1m_flow_bars",
    "resample_trades_to_1m_flow",
]

_BASE = "https://data.binance.vision"
_MINUTE_MS = 60_000


@dataclass(frozen=True)
class FlowBar:
    """One CLOSED 1-minute aggressive-trade-flow bar for a single symbol. `open_ms` is the minute's open_time in
    epoch-ms; the bar is point-in-time knowable at open_ms + 60_000 (its close). `close` is the last trade price
    in the minute (the mark we trade against). `buy_vol`/`sell_vol` are the aggressive (taker) BUY and SELL base
    volumes within the minute, split by the `is_buyer_maker` flag. `n_trades` is the aggregated-trade count."""

    open_ms: int
    close: float
    buy_vol: float
    sell_vol: float
    n_trades: int

    @property
    def ts(self) -> datetime:
        """The minute's open_time as a tz-aware UTC datetime."""
        return datetime.fromtimestamp(self.open_ms / 1000, tz=UTC)

    @property
    def total_vol(self) -> float:
        return self.buy_vol + self.sell_vol

    @property
    def imbalance(self) -> float:
        """Signed aggressive-trade imbalance in [-1, 1] = (buy - sell) / total. 0 when the minute had no volume.
        Positive = aggressive buyers dominated; negative = aggressive sellers dominated."""
        tot = self.total_vol
        return (self.buy_vol - self.sell_vol) / tot if tot > 0 else 0.0


def _vision_ms(value: int) -> int:
    """Normalize a Binance Vision transact_time to MILLISECONDS. Vision stamps ms, but some 2025+ archives use
    microseconds; a ms epoch stays < 1e15 until ~year 33658 while a µs epoch is >= 1e15 from 2001 on, so the
    threshold disambiguates without ever mangling a real ms timestamp (same rule as ingest/bars._vision_ms)."""
    return value // 1000 if value >= 1_000_000_000_000_000 else value


def _iter_days(start: date, end: date) -> Iterator[date]:
    """Yield every UTC date from `start` through `end` inclusive (ascending)."""
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def resample_trades_to_1m_flow(
    trades: Iterator[tuple[int, float, float, bool]],
) -> list[FlowBar]:
    """Bucket signed aggTrades into ascending 1m FlowBars. Each input row is
    `(transact_ms, price, quantity, is_buyer_maker)`:
      - is_buyer_maker == False -> the buyer was the TAKER -> aggressive BUY  -> quantity adds to buy_vol
      - is_buyer_maker == True  -> the buyer was the MAKER (seller is taker) -> aggressive SELL -> sell_vol
    `close` is the last trade price seen in the minute. Pure (no network). Minutes with no trades are simply
    absent (never zero-filled) — the caller treats a missing minute as a no-data gap, not a flat bar."""
    buckets: dict[int, dict[str, float]] = {}
    for transact_ms, price, qty, is_buyer_maker in trades:
        minute = (transact_ms // _MINUTE_MS) * _MINUTE_MS
        b = buckets.get(minute)
        if b is None:
            b = {"buy": 0.0, "sell": 0.0, "n": 0.0, "last_ms": -1.0, "close": 0.0}
            buckets[minute] = b
        if is_buyer_maker:
            b["sell"] += qty
        else:
            b["buy"] += qty
        b["n"] += 1.0
        if transact_ms >= b["last_ms"]:  # keep the last-by-time trade's price as the minute close
            b["last_ms"] = float(transact_ms)
            b["close"] = price
    return [
        FlowBar(open_ms=m, close=b["close"], buy_vol=b["buy"], sell_vol=b["sell"], n_trades=int(b["n"]))
        for m, b in sorted(buckets.items())
    ]


class AggTradesVisionFetcher:
    """Keyless daily-aggTrades fetcher from Binance Vision, resampled to 1m flow bars and cached on disk per
    (symbol, day). `market="spot"` reads `data/spot/daily/aggTrades/...`; `market="perp"` reads the USDⓈ-M tree
    `data/futures/um/daily/aggTrades/...`. A 404 day is a gap (skipped). Offline-testable via an injected
    `_fetcher`."""

    def __init__(
        self,
        cache_dir: str = ".cosmu/market_data/binance_vision_aggtrades_1m",
        *,
        market: str = "perp",
        sleep_s: float = 0.2,
        _fetcher: Callable[[str], bytes | None] | None = None,
    ) -> None:
        if market not in ("spot", "perp"):
            raise ValueError(f"market must be 'spot' or 'perp', got {market!r}")
        from pathlib import Path

        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.market = market
        self.sleep_s = sleep_s
        self._live = _fetcher is None
        self._fetcher = _fetcher or self._http_get

    def _root(self) -> str:
        return "data/spot" if self.market == "spot" else "data/futures/um"

    def _archive_url(self, symbol: str, day: date) -> str:
        label = f"{day.year:04d}-{day.month:02d}-{day.day:02d}"
        return f"{_BASE}/{self._root()}/daily/aggTrades/{symbol}/{symbol}-aggTrades-{label}.zip"

    def _http_get(self, url: str) -> bytes | None:
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=120, context=_ssl_context()) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            return None
        except Exception:  # noqa: BLE001 — any transport failure degrades to a skipped gap, never fabricated flow
            return None

    @staticmethod
    def _parse_zip(raw: bytes) -> Iterator[tuple[int, float, float, bool]]:
        """Unzip + parse the aggTrades CSV into `(transact_ms, price, quantity, is_buyer_maker)` rows. Columns:
        `agg_trade_id, price, quantity, first_trade_id, last_trade_id, transact_time, is_buyer_maker`. A leading
        header row (perp archives carry one) is detected by a non-numeric first cell and skipped."""
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for name in zf.namelist():
                if not name.endswith(".csv"):
                    continue
                with zf.open(name) as fh:
                    for cells in csv.reader(io.TextIOWrapper(fh, encoding="utf-8")):
                        if len(cells) < 7:
                            continue
                        try:
                            transact_ms = _vision_ms(int(cells[5]))
                            price = float(cells[1])
                            qty = float(cells[2])
                        except ValueError:
                            continue  # header row -> skip
                        is_buyer_maker = cells[6].strip().lower() == "true"
                        yield (transact_ms, price, qty, is_buyer_maker)

    def _cache_path(self, symbol: str, day: date):
        from pathlib import Path

        safe = symbol.replace("/", "")
        label = f"{day.year:04d}-{day.month:02d}-{day.day:02d}"
        return Path(self.cache_dir) / f"{safe}_{label}.csv"

    def _read_cache(self, symbol: str, day: date) -> list[FlowBar] | None:
        path = self._cache_path(symbol, day)
        if not path.exists():
            return None
        out: list[FlowBar] = []
        with path.open() as fh:
            for row in csv.reader(fh):
                if len(row) < 5:
                    continue
                try:
                    out.append(
                        FlowBar(
                            open_ms=int(row[0]), close=float(row[1]),
                            buy_vol=float(row[2]), sell_vol=float(row[3]), n_trades=int(row[4]),
                        )
                    )
                except ValueError:
                    continue
        return out

    def _write_cache(self, symbol: str, day: date, bars: list[FlowBar]) -> None:
        path = self._cache_path(symbol, day)
        tmp = path.with_suffix(".csv.tmp")
        with tmp.open("w", newline="") as fh:
            w = csv.writer(fh)
            for b in bars:
                w.writerow([b.open_ms, b.close, b.buy_vol, b.sell_vol, b.n_trades])
        tmp.replace(path)

    def fetch_day(self, symbol: str, day: date) -> list[FlowBar]:
        """Return ascending 1m flow bars for `symbol` on the UTC `day`. Cached on disk after the first fetch; a
        404 day returns [] and is cached as an empty file so a re-run pays no network cost over a known gap."""
        cached = self._read_cache(symbol, day)
        if cached is not None:
            return cached
        import time

        raw = self._fetcher(self._archive_url(symbol, day))
        if self._live and self.sleep_s:
            time.sleep(self.sleep_s)
        bars = resample_trades_to_1m_flow(self._parse_zip(raw)) if raw else []
        self._write_cache(symbol, day, bars)  # cache even an empty day (a known 404 gap) to avoid re-fetching
        return bars

    def fetch(self, symbol: str, start: date, end: date) -> list[FlowBar]:
        """Ascending 1m flow bars for `symbol` over the closed [start, end] UTC-date interval. `end` is clamped to
        today. Days that 404 are skipped (never zero-filled)."""
        today = datetime.now(UTC).date()
        if end > today:
            end = today
        if start > end:
            return []
        out: list[FlowBar] = []
        for day in _iter_days(start, end):
            out.extend(self.fetch_day(symbol, day))
        out.sort(key=lambda b: b.open_ms)
        return out


def fetch_1m_flow_bars(
    symbol: str,
    start: date,
    end: date,
    *,
    cache_dir: str = ".cosmu/market_data/binance_vision_aggtrades_1m",
    market: str = "perp",
    _fetcher: Callable[[str], bytes | None] | None = None,
) -> list[FlowBar]:
    """Convenience wrapper — fetch + cache 1m aggressive-flow bars for `symbol` over [start, end] UTC dates.

    Returns ascending FlowBars (each carrying signed-aggressor buy/sell volume + the minute close price). Gap
    days (Vision 404) are skipped — never zero-filled. `end` is clamped to today. Keyless. Caches each day to
    disk so repeated calls pay no network cost once covered.

    Example::

        from datetime import date
        bars = fetch_1m_flow_bars("ARBUSDT", date(2025, 2, 1), date(2025, 2, 3), market="perp")
        bars[0].imbalance  # signed aggressive-trade imbalance for the first minute
    """
    fetcher = AggTradesVisionFetcher(cache_dir, market=market, _fetcher=_fetcher)
    return fetcher.fetch(symbol, start, end)
