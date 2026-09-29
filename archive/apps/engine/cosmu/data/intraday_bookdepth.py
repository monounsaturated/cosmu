# intent: keyless, point-in-time-honest historical BOOK-DEPTH (resting limit-order liquidity) fetcher from
# Binance Vision (data.binance.vision) — the microstructure plumbing for intraday BOOK-IMBALANCE research.
# This is the RESTING-LIQUIDITY counterpart to cosmu.data.intraday_aggtrades (which captures executed
# AGGRESSIVE flow): bookDepth snapshots the standing bid/ask depth at fixed ±%-from-mid bands, NOT the trades
# that executed. Reuses the EXACT keyless zip-fetch idiom (urllib + _ssl_context, daily immutable zips, 404 ==
# skipped gap never zero-filled, offline-injectable _fetcher), pointed at the USDⓈ-M futures `bookDepth/` prefix.
# Inputs: symbol, UTC date range, market (only perp has bookDepth). Outputs: ascending 1-minute DEPTH BARS, each
# carrying the resting bid-side / ask-side depth+notional within a chosen ±% band.
#
# Binance Vision bookDepth CSV schema (verified against a live ARBUSDT perp day, 2025-02-01):
#   columns: timestamp, percentage, depth, notional
#   - one SNAPSHOT = 10 rows sharing a timestamp, one row per band percentage in {-5,-4,-3,-2,-1,1,2,3,4,5}.
#   - percentage < 0  -> a BID band that many percent BELOW mid (resting buy liquidity).
#   - percentage > 0  -> an ASK band that many percent ABOVE mid (resting sell liquidity).
#   - `depth`    = cumulative resting BASE-asset quantity out to that band (monotone in |percentage|).
#   - `notional` = cumulative resting USD value out to that band.
#   - cadence ~30s (≈2880 snapshots/day); snapshot times are irregular (event-ish), so we resample to 1m.
#   - bookDepth carries NO price/mid — depth-imbalance is a pure ratio; a caller that needs to MARK P&L joins a
#     parallel 1m kline series (cosmu.data.intraday_binance_vision.fetch_1m_bars market="perp") on the minute.
#
# Invariants:
#   - No API key required; keyless HTTPS GET of immutable daily zips (revision-safe).
#   - No fabrication: a 404 day (listing started later / not yet published) is SKIPPED, never zero-filled.
#   - Point-in-time: a 1m depth bar aggregates only snapshots that OCCURRED within that minute; it is knowable at
#     the minute's close. Each snapshot is stamped at its own UTC `timestamp` (event time, no revision).
#   - `end` is clamped to today (never request a future day).
#   - Offline-testable: inject `_fetcher(url) -> bytes | None` (None == 404/missing), same contract as the
#     aggTrades / kline fetchers, so tests replay a zipped-CSV fixture without touching the network.
# This module owns ONLY the bookDepth parse + 1m depth-bar resample; it composes the shared SSL transport
# (cosmu.data.market._ssl_context) and never re-implements bar OHLCV or executed-flow (those stay elsewhere).

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
    "DepthBar",
    "DepthSnapshot",
    "BookDepthVisionFetcher",
    "fetch_1m_depth_bars",
    "resample_snapshots_to_1m_depth",
]

_BASE = "https://data.binance.vision"
_MINUTE_MS = 60_000


@dataclass(frozen=True)
class DepthSnapshot:
    """ONE bookDepth snapshot, reduced to the resting bid/ask depth+notional WITHIN a chosen ±% band. `ts_ms` is
    the snapshot's event time in epoch-ms. `bid_depth`/`ask_depth` are the cumulative resting BASE-asset quantity
    on the bid (percentage in [-band, -1]) and ask (percentage in [1, band]) sides; `bid_notional`/`ask_notional`
    are the matching USD values. Because Vision's `depth` is cumulative-out-to-band, the value AT band b already
    sums the inner bands — so the band-b row alone is the within-band cumulative depth (we read the outermost row
    <= band)."""

    ts_ms: int
    bid_depth: float
    ask_depth: float
    bid_notional: float
    ask_notional: float


@dataclass(frozen=True)
class DepthBar:
    """One 1-minute resting-book-depth bar for a single symbol, aggregated from all snapshots that occurred in the
    minute. `open_ms` is the minute's open_time in epoch-ms; the bar is PIT-knowable at open_ms + 60_000 (close).
    `bid_depth`/`ask_depth` are the MEAN within-band resting depth over the minute's snapshots (mean, not last, so
    a single transient pulled wall does not define the minute). `n_snaps` is how many snapshots fed the minute."""

    open_ms: int
    bid_depth: float
    ask_depth: float
    bid_notional: float
    ask_notional: float
    n_snaps: int

    @property
    def ts(self) -> datetime:
        """The minute's open_time as a tz-aware UTC datetime."""
        return datetime.fromtimestamp(self.open_ms / 1000, tz=UTC)

    @property
    def total_depth(self) -> float:
        return self.bid_depth + self.ask_depth

    @property
    def imbalance(self) -> float:
        """Signed resting-DEPTH imbalance in [-1, 1] = (bid_depth - ask_depth) / total_depth, 0 when empty.
        Positive = resting BID liquidity dominates (a support wall); negative = resting ASK dominates."""
        tot = self.total_depth
        return (self.bid_depth - self.ask_depth) / tot if tot > 0 else 0.0

    @property
    def notional_imbalance(self) -> float:
        """Signed resting-NOTIONAL imbalance in [-1, 1] = (bid_notional - ask_notional)/total_notional. The
        USD-weighted twin of `imbalance` (depth is base-qty, notional is USD); reported for sensitivity."""
        tot = self.bid_notional + self.ask_notional
        return (self.bid_notional - self.ask_notional) / tot if tot > 0 else 0.0


def _vision_ms(value: int) -> int:
    """Normalize a Binance Vision epoch to MILLISECONDS (ms epoch stays < 1e15 until ~year 33658; a µs epoch is
    >= 1e15 from 2001 on) — same disambiguation rule as the kline/aggTrades fetchers."""
    return value // 1000 if value >= 1_000_000_000_000_000 else value


def _parse_ts_ms(raw: str) -> int | None:
    """Parse a bookDepth `timestamp` cell to epoch-ms. Vision ships it as a UTC 'YYYY-MM-DD HH:MM:SS' string (no
    tz suffix); newer archives may ship a numeric epoch. Returns None for an unparseable cell (header row)."""
    s = raw.strip()
    if not s:
        return None
    try:  # numeric epoch (ms or µs)
        return _vision_ms(int(s))
    except ValueError:
        pass
    try:
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        return int(dt.timestamp() * 1000)
    except ValueError:
        return None


def _iter_days(start: date, end: date) -> Iterator[date]:
    """Yield every UTC date from `start` through `end` inclusive (ascending)."""
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def _reduce_snapshot(
    rows: list[tuple[int, float, float]],  # (percentage, depth, notional)
    *,
    band: int,
) -> tuple[float, float, float, float]:
    """Reduce ONE snapshot's 10 band rows to (bid_depth, ask_depth, bid_notional, ask_notional) WITHIN ±`band`%.
    Vision's `depth`/`notional` are cumulative-out-to-band, so the within-band cumulative is simply the OUTERMOST
    row whose |percentage| <= band on each side (bid = most-negative band >= -band, ask = most-positive <= band).
    Pure; missing a side (degenerate snapshot) contributes 0 on that side."""
    bid_depth = ask_depth = bid_notional = ask_notional = 0.0
    best_bid = best_ask = -1  # track the outermost |pct| <= band seen per side
    for pct, depth, notional in rows:
        if pct < 0:
            if -pct <= band and -pct > best_bid:
                best_bid = -pct
                bid_depth, bid_notional = depth, notional
        elif pct > 0:
            if pct <= band and pct > best_ask:
                best_ask = pct
                ask_depth, ask_notional = depth, notional
    return bid_depth, ask_depth, bid_notional, ask_notional


def resample_snapshots_to_1m_depth(
    snapshots: Iterator[DepthSnapshot],
) -> list[DepthBar]:
    """Bucket DepthSnapshots into ascending 1m DepthBars by minute, averaging the within-band bid/ask depth+notional
    over the minute's snapshots (mean — a transient one-snapshot wall does not define the minute). Pure (no network).
    Minutes with no snapshot are simply absent (never zero-filled) — a missing minute is a no-data gap, not a flat bar."""
    buckets: dict[int, dict[str, float]] = {}
    for s in snapshots:
        minute = (s.ts_ms // _MINUTE_MS) * _MINUTE_MS
        b = buckets.get(minute)
        if b is None:
            b = {"bid_d": 0.0, "ask_d": 0.0, "bid_n": 0.0, "ask_n": 0.0, "n": 0.0}
            buckets[minute] = b
        b["bid_d"] += s.bid_depth
        b["ask_d"] += s.ask_depth
        b["bid_n"] += s.bid_notional
        b["ask_n"] += s.ask_notional
        b["n"] += 1.0
    out: list[DepthBar] = []
    for m, b in sorted(buckets.items()):
        n = b["n"] or 1.0
        out.append(
            DepthBar(
                open_ms=m,
                bid_depth=b["bid_d"] / n,
                ask_depth=b["ask_d"] / n,
                bid_notional=b["bid_n"] / n,
                ask_notional=b["ask_n"] / n,
                n_snaps=int(b["n"]),
            )
        )
    return out


class BookDepthVisionFetcher:
    """Keyless daily-bookDepth fetcher from Binance Vision, reduced to a chosen ±% band and resampled to 1m depth
    bars, cached on disk per (symbol, day, band). Only the USDⓈ-M futures tree
    (`data/futures/um/daily/bookDepth/...`) publishes bookDepth — spot does NOT, so `market` is fixed to "perp".
    A 404 day is a gap (skipped). Offline-testable via an injected `_fetcher`."""

    def __init__(
        self,
        cache_dir: str = ".cosmu/market_data/binance_vision_bookdepth_1m",
        *,
        band: int = 2,
        sleep_s: float = 0.2,
        _fetcher: Callable[[str], bytes | None] | None = None,
    ) -> None:
        if not (1 <= band <= 5):
            raise ValueError(f"band must be in 1..5 (Vision publishes ±1..±5%), got {band!r}")
        from pathlib import Path

        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.band = band
        self.sleep_s = sleep_s
        self._live = _fetcher is None
        self._fetcher = _fetcher or self._http_get

    def _archive_url(self, symbol: str, day: date) -> str:
        label = f"{day.year:04d}-{day.month:02d}-{day.day:02d}"
        return f"{_BASE}/data/futures/um/daily/bookDepth/{symbol}/{symbol}-bookDepth-{label}.zip"

    def _http_get(self, url: str) -> bytes | None:
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=120, context=_ssl_context()) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            return None
        except Exception:  # noqa: BLE001 — any transport failure degrades to a skipped gap, never fabricated depth
            return None

    def _parse_zip(self, raw: bytes) -> Iterator[DepthSnapshot]:
        """Unzip + parse the bookDepth CSV into within-band DepthSnapshots. The CSV is row-per-band; we group the
        10 rows sharing a timestamp into one snapshot, then reduce to the chosen ±band. A leading header row
        (non-numeric `percentage`) is skipped. Rows are assumed contiguous per timestamp (Vision ships them so);
        we flush a snapshot whenever the timestamp changes."""
        cur_ts: int | None = None
        rows: list[tuple[int, float, float]] = []
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for name in zf.namelist():
                if not name.endswith(".csv"):
                    continue
                with zf.open(name) as fh:
                    for cells in csv.reader(io.TextIOWrapper(fh, encoding="utf-8")):
                        if len(cells) < 4:
                            continue
                        ts_ms = _parse_ts_ms(cells[0])
                        if ts_ms is None:
                            continue  # header row -> skip
                        try:
                            pct = int(float(cells[1]))
                            depth = float(cells[2])
                            notional = float(cells[3])
                        except ValueError:
                            continue
                        if cur_ts is not None and ts_ms != cur_ts:
                            bd, ad, bn, an = _reduce_snapshot(rows, band=self.band)
                            yield DepthSnapshot(cur_ts, bd, ad, bn, an)
                            rows = []
                        cur_ts = ts_ms
                        rows.append((pct, depth, notional))
        if cur_ts is not None and rows:
            bd, ad, bn, an = _reduce_snapshot(rows, band=self.band)
            yield DepthSnapshot(cur_ts, bd, ad, bn, an)

    def _cache_path(self, symbol: str, day: date):
        from pathlib import Path

        safe = symbol.replace("/", "")
        label = f"{day.year:04d}-{day.month:02d}-{day.day:02d}"
        return Path(self.cache_dir) / f"{safe}_b{self.band}_{label}.csv"

    def _read_cache(self, symbol: str, day: date) -> list[DepthBar] | None:
        path = self._cache_path(symbol, day)
        if not path.exists():
            return None
        out: list[DepthBar] = []
        with path.open() as fh:
            for row in csv.reader(fh):
                if len(row) < 6:
                    continue
                try:
                    out.append(
                        DepthBar(
                            open_ms=int(row[0]),
                            bid_depth=float(row[1]), ask_depth=float(row[2]),
                            bid_notional=float(row[3]), ask_notional=float(row[4]),
                            n_snaps=int(row[5]),
                        )
                    )
                except ValueError:
                    continue
        return out

    def _write_cache(self, symbol: str, day: date, bars: list[DepthBar]) -> None:
        path = self._cache_path(symbol, day)
        tmp = path.with_suffix(".csv.tmp")
        with tmp.open("w", newline="") as fh:
            w = csv.writer(fh)
            for b in bars:
                w.writerow([b.open_ms, b.bid_depth, b.ask_depth, b.bid_notional, b.ask_notional, b.n_snaps])
        tmp.replace(path)

    def fetch_day(self, symbol: str, day: date) -> list[DepthBar]:
        """Return ascending 1m depth bars for `symbol` on the UTC `day`. Cached on disk after the first fetch; a
        404 day returns [] and is cached as an empty file so a re-run pays no network cost over a known gap."""
        cached = self._read_cache(symbol, day)
        if cached is not None:
            return cached
        import time

        raw = self._fetcher(self._archive_url(symbol, day))
        if self._live and self.sleep_s:
            time.sleep(self.sleep_s)
        bars = resample_snapshots_to_1m_depth(self._parse_zip(raw)) if raw else []
        self._write_cache(symbol, day, bars)  # cache even an empty day (a known 404 gap) to avoid re-fetching
        return bars

    def fetch(self, symbol: str, start: date, end: date) -> list[DepthBar]:
        """Ascending 1m depth bars for `symbol` over the closed [start, end] UTC-date interval. `end` is clamped to
        today. Days that 404 are skipped (never zero-filled)."""
        today = datetime.now(UTC).date()
        if end > today:
            end = today
        if start > end:
            return []
        out: list[DepthBar] = []
        for day in _iter_days(start, end):
            out.extend(self.fetch_day(symbol, day))
        out.sort(key=lambda b: b.open_ms)
        return out


def fetch_1m_depth_bars(
    symbol: str,
    start: date,
    end: date,
    *,
    band: int = 2,
    cache_dir: str = ".cosmu/market_data/binance_vision_bookdepth_1m",
    _fetcher: Callable[[str], bytes | None] | None = None,
) -> list[DepthBar]:
    """Convenience wrapper — fetch + cache 1m resting-book-depth bars for `symbol` over [start, end] UTC dates,
    reduced to the ±`band`% book region.

    Returns ascending DepthBars (each carrying mean within-band resting bid/ask depth+notional over the minute).
    Gap days (Vision 404) are skipped — never zero-filled. `end` is clamped to today. Keyless. Caches each day to
    disk so repeated calls pay no network cost once covered. Only the USDⓈ-M futures tree publishes bookDepth.

    Example::

        from datetime import date
        bars = fetch_1m_depth_bars("ARBUSDT", date(2025, 2, 1), date(2025, 2, 3), band=2)
        bars[0].imbalance  # signed resting-depth imbalance for the first minute (+ = bid wall dominates)
    """
    fetcher = BookDepthVisionFetcher(cache_dir, band=band, _fetcher=_fetcher)
    return fetcher.fetch(symbol, start, end)
