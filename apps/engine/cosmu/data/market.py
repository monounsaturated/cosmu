# intent: fetch and cache Binance spot OHLCV bars; inputs: symbol/timeframe requests; outputs: ordered Bar records;
# invariants: secrets are never needed, cached bars remain exchange-sourced, tests can inject a provider, and the
# crypto providers serve only CLOSED candles — the in-progress candle is dropped before caching, a cache whose
# newest bar is no longer the latest closed bar is refetched, and a fetched row replaces a cached row on ts
# collision (a row cached while its candle was still forming must not freeze the executor's view forever).

from __future__ import annotations

import json
import os
import ssl
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Bar:
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


class MarketDataProvider(Protocol):
    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        """Return ascending OHLCV bars for one venue symbol."""


# Timeframe → period seconds for the closed-bar / freshness math. An unknown timeframe maps to None and
# keeps the legacy cache behaviour (no freshness check) rather than guessing a period.
_TIMEFRAME_SECONDS: dict[str, int] = {
    "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3_600, "4h": 14_400, "1d": 86_400, "1w": 604_800,
}


def _drop_unclosed(bars: list[Bar], timeframe: str, now: datetime) -> list[Bar]:
    """Drop trailing bars whose candle has not CLOSED yet (close time = ts + period > now). Exchange kline
    endpoints return the live in-progress candle as the last row; caching it freezes a mid-bar snapshot as if
    it were a final close — the executor-freshness trap. Unknown timeframe → unchanged (no period to judge by)."""
    period = _TIMEFRAME_SECONDS.get(timeframe)
    if period is None:
        return bars
    cutoff = now.timestamp() - period
    out = list(bars)
    while out and out[-1].ts.timestamp() > cutoff:
        out.pop()
    return out


def _cache_is_fresh(cached: list[Bar], timeframe: str, now: datetime) -> bool:
    """True when the cache's newest bar IS the latest closed candle (newest.ts + 2*period > now) — then a
    network fetch can add nothing. False forces a refetch even when the cache covers the requested limit.
    Unknown timeframe → treated as fresh (legacy behaviour: serve the covering cache)."""
    period = _TIMEFRAME_SECONDS.get(timeframe)
    if period is None:
        return True
    if not cached:
        return False
    return now.timestamp() < cached[-1].ts.timestamp() + 2 * period


class BinanceSpotOHLCVProvider:
    """Binance spot OHLCV provider with a ccxt path and a stdlib REST fallback. Serves CLOSED candles only:
    the in-progress candle is dropped before caching, and a covering-but-stale cache is refetched rather than
    served (`now_fn` is injectable so tests pin the clock)."""

    def __init__(
        self,
        cache_dir: Path | str = ".cosmu/market_data/binance",
        *,
        now_fn=None,  # noqa: ANN001 — Callable[[], datetime]; injected by tests to pin the clock
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._now_fn = now_fn or (lambda: datetime.now(tz=UTC))

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        now = self._now_fn()
        cached = self._read_cache(symbol, timeframe)
        if len(cached) >= limit and _cache_is_fresh(cached, timeframe, now):
            return cached[-limit:]

        # +1 so dropping the in-progress last candle still leaves `limit` closed bars (page cap 1000).
        page = min(limit + 1, 1000)
        try:
            bars = self._fetch_with_ccxt(symbol, timeframe, page)
        except Exception:  # noqa: BLE001 — a ccxt transport error must still fall through to the REST path
            bars = []
        if not bars:
            try:
                bars = self._fetch_with_rest(symbol, timeframe, page)
            except Exception:  # noqa: BLE001 — offline/refused: a covering-but-stale cache still serves
                bars = []      # (degrade, never raise where the pre-freshness code served the cache silently)
        bars = _drop_unclosed(bars, timeframe, now)
        if not bars:
            return cached[-limit:]  # network empty → never shrink; serve what we have
        # A single REST/ccxt page caps at 1000 bars; merge into (never overwrite) the cache so a
        # limit>cache fetch can only EXTEND a deep cache, never truncate it (see _write_cache).
        merged = self._write_cache(symbol, timeframe, bars)
        return merged[-limit:]

    def _fetch_with_ccxt(self, symbol: str, timeframe: str, limit: int) -> list[Bar]:
        try:
            import ccxt  # type: ignore[import-not-found]
        except ImportError:
            return []

        exchange = ccxt.binance({"enableRateLimit": True})
        market_symbol = _ccxt_symbol(symbol)
        rows = exchange.fetch_ohlcv(market_symbol, timeframe=timeframe, limit=limit)
        return [_bar_from_ccxt(row) for row in rows]

    def _fetch_with_rest(self, symbol: str, timeframe: str, limit: int) -> list[Bar]:
        query = urllib.parse.urlencode({"symbol": symbol, "interval": timeframe, "limit": limit})
        url = f"https://api.binance.com/api/v3/klines?{query}"
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            rows = json.loads(resp.read().decode("utf-8"))
        return [_bar_from_binance(row) for row in rows]

    def _cache_path(self, symbol: str, timeframe: str) -> Path:
        safe = f"{symbol}_{timeframe}".replace("/", "")
        return self.cache_dir / f"{safe}.json"

    def _read_cache(self, symbol: str, timeframe: str) -> list[Bar]:
        path = self._cache_path(symbol, timeframe)
        if not path.exists():
            return []
        rows = json.loads(path.read_text())
        return [_bar_from_json(row) for row in rows]

    def _write_cache(self, symbol: str, timeframe: str, bars: list[Bar]) -> list[Bar]:
        """Append-merge `bars` into the on-disk cache, deduped on ts — NEVER shrinks the cache.
        Re-reads the current file right before writing (and writes atomically), so a single 1000-bar
        page can't truncate a deep 2000-bar cache, and a concurrent writer's bars survive. Returns
        the merged, ascending bars so callers can serve the up-to-date window."""
        path = self._cache_path(symbol, timeframe)
        merged = _merge_bars(self._read_cache(symbol, timeframe), bars)
        _atomic_write_text(path, json.dumps(_bars_to_rows(merged), separators=(",", ":")))
        return merged


# PROCESS-SCOPED memo for RemoteBarsProvider: a cohort screens N specs and each builds a fresh provider, so
# WITHOUT this every spec would re-fetch the same pair's bars from Railway (N×M HTTP calls per tick). Memoizing
# per (base_url, symbol, timeframe, limit) for the life of the process collapses that to ONE fetch per pair per
# tick — recovering the local-cache efficiency the cacheless design otherwise loses — while staying account-
# swappable (the memo is built from Railway at runtime, not a bundled file, and a new container starts empty so
# bars are never stale across ticks). In-memory only; never persisted.
_REMOTE_BARS_MEMO: dict[tuple[str, str, str, int], list[Bar]] = {}


class RemoteBarsProvider:
    """Fetch OHLCV from a Binance-REACHABLE HTTP engine (the always-on Railway EU `/market/bars` endpoint) instead
    of calling Binance directly. THE FIX for Binance geo-blocking cloud IPs (Modal US returns nothing on a live
    fetch): the remote does the venue fetch in a region that CAN reach Binance and returns closed-candle bars as
    JSON; this provider just relays them. That removes the per-deploy local bar cache — so the compute fleet stays
    MODULAR and ACCOUNT-SWAPPABLE (any Modal account deploys cacheless; point COSMU_BARS_URL at the EU engine).
    EFFICIENCY: a process-scoped memo (_REMOTE_BARS_MEMO) means each pair is fetched from Railway ONCE per tick,
    not once per spec — so a 100-spec cohort makes ~M (not N×M) HTTP calls.
    Read-only + offline-safe (any transport error / non-200 → [] → the caller degrades, never fabricates). Sends
    `x-api-key` when COSMU_BARS_KEY / API_SECRET_KEY is set — the same shared secret the engine middleware checks."""

    def __init__(self, base_url: str, *, api_key: str | None = None, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key if api_key is not None else (
            os.environ.get("COSMU_BARS_KEY") or os.environ.get("API_SECRET_KEY") or None
        )
        self.timeout = timeout

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        memo_key = (self.base_url, symbol, timeframe, int(limit))
        cached = _REMOTE_BARS_MEMO.get(memo_key)
        if cached is not None:
            return cached
        query = urllib.parse.urlencode({"symbol": symbol, "timeframe": timeframe, "limit": int(limit)})
        url = f"{self.base_url}/market/bars?{query}"
        headers = {"User-Agent": "cosmu-engine/0.1"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=self.timeout, context=_ssl_context()) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception:  # noqa: BLE001 — offline / refused / non-200 → empty, the caller degrades honestly (NOT memoized: a transient failure must be retryable next call)
            return []
        rows = payload.get("bars", []) if isinstance(payload, dict) else payload
        out: list[Bar] = []
        for row in rows:
            try:
                out.append(_bar_from_json(row))
            except Exception:  # noqa: BLE001 — skip a malformed row, never fabricate
                continue
        result = out[-int(limit):] if limit else out
        if result:  # memoize only a non-empty fetch (an empty/failed result stays retryable)
            _REMOTE_BARS_MEMO[memo_key] = result
        return result


def keyless_crypto_reference() -> MarketDataProvider:
    """The keyless crypto reference provider for the configured bars venue. `COSMU_BARS_VENUE` (default
    'binance', BYTE-IDENTICAL to before) flips the whole keyless crypto-bar source in ONE place — e.g. to
    'kraken' when Binance is geo-/regulatory-blocked. Both providers share the SAME symbol contract
    ('BTCUSDT'; Kraken maps it to XBTUSD internally) and degrade identically (offline → cache → empty), so
    the swap is transparent to every caller. An unknown value falls back to Binance (safe default)."""
    providers = {
        "binance": BinanceSpotOHLCVProvider,
        "kraken": KrakenSpotOHLCVProvider,
    }
    venue = os.environ.get("COSMU_BARS_VENUE", "binance").strip().lower() or "binance"
    return providers.get(venue, BinanceSpotOHLCVProvider)()


def default_crypto_reference() -> MarketDataProvider:
    """The default crypto reference provider for the screen / paper clock. When COSMU_BARS_URL is set, bars come
    from that HTTP engine at RUNTIME (the geo-unblocked Railway EU box) → no bundled cache, so the Modal fleet
    is modular + account-swappable. Unset (local / tests / current deploys) → the keyless provider for
    COSMU_BARS_VENUE (default Binance, BYTE-IDENTICAL to before; 'kraken' when Binance is blocked). A single
    env flag flips the whole crypto-bar source; nothing else changes."""
    base = os.environ.get("COSMU_BARS_URL")
    return RemoteBarsProvider(base) if base else keyless_crypto_reference()


class UniversalOHLCVProvider:
    """The UNIVERSAL PRICE LAYER reference provider: fetch a canonical PAIR's REFERENCE OHLCV ONCE and serve it to
    EVERY venue that UNIFIES onto it (data/reference.decision). Composes the keyless `BinanceSpotOHLCVProvider`
    (the deepest keyless crypto book = the natural reference) and caches ONE series per PAIR (not per venue): so a
    BTC/USDT reference is fetched a single time and a Kraken-XBTUSD cell that UNIFIES reuses the SAME bars instead
    of fetching its own near-identical series. Keying the cache by the canonical pair id is what makes the reuse a
    real de-dup (the underlying Binance cache is per venue-symbol; this is the pair-level contract on top).

    A pair id is 'BASE/QUOTE' (e.g. 'BTC/USDT'); the reference venue-symbol is the concatenation (BTCUSDT) — the
    Binance spelling. Offline-safe + closed-candle-correct via the composed provider; this class adds no network
    behaviour of its own, only the pair-keyed in-process memo so one screen pass fetches each reference once."""

    def __init__(self, reference: MarketDataProvider | None = None) -> None:
        # The reference is injectable for tests / alternate references; defaults to the keyless Binance spot book —
        # or, when COSMU_BARS_URL is set, the Railway EU bars engine (geo-block-free, cacheless deploys).
        self._reference = reference or default_crypto_reference()
        self._memo: dict[tuple[str, str, int], list[Bar]] = {}  # (pair_id, timeframe, limit) -> bars

    @staticmethod
    def _venue_symbol(pair_id: str) -> str:
        """The reference venue-symbol for a canonical pair id ('BTC/USDT' -> 'BTCUSDT'). The reference book is
        Binance, whose spelling is the bare concatenation; the '/' is purely the pair-identity separator."""
        return pair_id.replace("/", "")

    def fetch_reference(self, pair_id: str, timeframe: str, *, limit: int) -> list[Bar]:
        """The canonical reference bars for a PAIR, fetched ONCE and memoized per (pair, timeframe, limit) for the
        life of this provider — so N venues that unify onto the same pair share ONE fetch. Degrades exactly like
        the composed provider (offline -> cached -> empty)."""
        key = (pair_id, timeframe, int(limit))
        cached = self._memo.get(key)
        if cached is not None:
            return cached
        bars = self._reference.fetch_bars(self._venue_symbol(pair_id), timeframe, limit=limit)
        self._memo[key] = bars
        return bars

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        """MarketDataProvider contract: `symbol` is treated as a canonical pair id (BASE/QUOTE) OR a bare venue
        symbol (BTCUSDT) — both resolve to the same reference series via `_venue_symbol`, so this can stand in for
        a plain provider while still memoizing per pair."""
        return self.fetch_reference(symbol, timeframe, limit=limit)


_US_EQUITY_CLOSE_UTC = time(21, 5)  # 16:00 ET close; 21:05 UTC is exact+buffer in winter, ~1h conservative in summer


def _drop_unclosed_us_daily(bars: list[Bar], now: datetime) -> list[Bar]:
    """Drop trailing daily bar(s) whose US cash session has not CLOSED yet (a daily bar dated D is final only
    once `now` ≥ D 21:05 UTC). The keyless equity vendors include today's in-progress bar mid-session; caching
    it would freeze a partial close as final (the deep review's M3). Conservative by ≤1h in summer DST —
    the 22:10 UTC equity clock still sees today's close either way."""
    out = list(bars)
    while out and now < datetime.combine(out[-1].ts.date(), _US_EQUITY_CLOSE_UTC, tzinfo=UTC):
        out.pop()
    return out


def _latest_expected_us_session(now: datetime) -> date:
    """The most recent US cash-session DATE whose close has passed — weekends skipped. Holidays are NOT
    modeled: on a holiday the expected bar is missing, so freshness fails and the provider refetches (a
    harmless no-op merge), never serves a frozen cache."""
    d = now.date()
    if now < datetime.combine(d, _US_EQUITY_CLOSE_UTC, tzinfo=UTC):
        d -= timedelta(days=1)
    while d.weekday() >= 5:  # Sat/Sun
        d -= timedelta(days=1)
    return d


def _equity_cache_is_fresh(cached: list[Bar], now: datetime) -> bool:
    """Fresh ⇔ the cache already holds the latest EXPECTED closed US session — then a fetch adds nothing.
    Anything older forces a refetch: the pre-fix behaviour served ANY existing cache forever, silently
    freezing equity marks (and rotation inputs) at whenever the cache file happened to be created."""
    return bool(cached) and cached[-1].ts.date() >= _latest_expected_us_session(now)


class StooqDailyBarsProvider:
    """Free daily equity bars via Stooq CSV (no key). Known limit: Stooq lists only CURRENTLY-traded
    symbols — it is SURVIVORSHIP-BIASED (delisted names are absent). Declared, not hidden: this proves
    signal *presence* cross-asset, not deployable capacity. Norgate replaces it at the live phase.
    Serves only CLOSED US sessions; a cache missing the latest expected session is refetched (never served
    forever), and offline it degrades to the cache."""

    survivorship_complete = False  # free bars have no delisted names — see class docstring

    def __init__(self, cache_dir: Path | str = ".cosmu/market_data/stooq", *, now_fn=None) -> None:  # noqa: ANN001
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._now_fn = now_fn or (lambda: datetime.now(tz=UTC))

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        now = self._now_fn()
        cached = self._read_cache(symbol)
        if len(cached) >= limit and _equity_cache_is_fresh(cached, now):
            return cached[-limit:]
        try:
            fetched = self._fetch_csv(symbol)
        except Exception:  # noqa: BLE001 — offline/blocked: degrade to the cache, never crash the caller
            return cached[-limit:]
        fetched = _drop_unclosed_us_daily(fetched, now)
        if not fetched:
            return cached[-limit:]
        merged = _merge_bars(cached, fetched)
        self._write_cache(symbol, merged)
        return merged[-limit:]

    def _fetch_csv(self, symbol: str) -> list[Bar]:
        # Stooq US tickers are suffixed ".us" (e.g. spy.us); pass-through if already qualified.
        s = symbol.lower() if "." in symbol else f"{symbol.lower()}.us"
        url = f"https://stooq.com/q/d/l/?{urllib.parse.urlencode({'s': s, 'i': 'd'})}"
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            text = resp.read().decode("utf-8")
        out: list[Bar] = []
        for line in text.splitlines()[1:]:  # skip CSV header
            cols = line.split(",")
            if len(cols) < 6 or cols[1] in ("", "null"):
                continue
            out.append(
                Bar(
                    ts=datetime.fromisoformat(cols[0]).replace(tzinfo=UTC),
                    open=Decimal(cols[1]), high=Decimal(cols[2]), low=Decimal(cols[3]),
                    close=Decimal(cols[4]), volume=Decimal(cols[5] or "0"),
                )
            )
        return out

    def _cache_path(self, symbol: str) -> Path:
        return self.cache_dir / f"{symbol.replace('/', '_')}_1d.json"

    def _read_cache(self, symbol: str) -> list[Bar]:
        path = self._cache_path(symbol)
        if not path.exists():
            return []
        return [_bar_from_json(r) for r in json.loads(path.read_text())]

    def _write_cache(self, symbol: str, bars: list[Bar]) -> None:
        _atomic_write_text(self._cache_path(symbol), json.dumps(_bars_to_rows(bars), separators=(",", ":")))


class KrakenSpotOHLCVProvider:
    """Free Kraken public OHLC (no key). Stdlib urllib + certifi SSL, disk-cached, separable parse fn.
    Kraken's REST returns at most ~720 bars per call; we cache and slice to the requested limit."""

    # Kraken takes the interval in MINUTES; map the common timeframe strings we use.
    _INTERVAL_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440, "1w": 10080}

    def __init__(
        self,
        cache_dir: Path | str = ".cosmu/market_data/kraken",
        *,
        now_fn=None,  # noqa: ANN001 — Callable[[], datetime]; injected by tests to pin the clock
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._now_fn = now_fn or (lambda: datetime.now(tz=UTC))

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        now = self._now_fn()
        cached = self._read_cache(symbol, timeframe)
        if len(cached) >= limit and _cache_is_fresh(cached, timeframe, now):
            return cached[-limit:]
        try:
            fetched = self._fetch_rest(symbol, timeframe)
        except Exception:  # noqa: BLE001 — offline/refused: a covering-but-stale cache still serves (degrade)
            fetched = []
        bars = _drop_unclosed(fetched, timeframe, now)
        if not bars:
            return cached[-limit:]  # network empty → never shrink; serve what we have
        return self._write_cache(symbol, timeframe, bars)[-limit:]

    def _fetch_rest(self, symbol: str, timeframe: str) -> list[Bar]:
        interval = self._INTERVAL_MINUTES.get(timeframe, 1440)
        pair = _kraken_pair(symbol)
        query = urllib.parse.urlencode({"pair": pair, "interval": interval})
        url = f"https://api.kraken.com/0/public/OHLC?{query}"
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return _bars_from_kraken(payload)

    def _cache_path(self, symbol: str, timeframe: str) -> Path:
        safe = f"{symbol}_{timeframe}".replace("/", "")
        return self.cache_dir / f"{safe}.json"

    def _read_cache(self, symbol: str, timeframe: str) -> list[Bar]:
        path = self._cache_path(symbol, timeframe)
        if not path.exists():
            return []
        return [_bar_from_json(r) for r in json.loads(path.read_text())]

    def _write_cache(self, symbol: str, timeframe: str, bars: list[Bar]) -> list[Bar]:
        """Append-merge into the cache (never shrinks; atomic write); returns the merged bars."""
        merged = _merge_bars(self._read_cache(symbol, timeframe), bars)
        _atomic_write_text(self._cache_path(symbol, timeframe), json.dumps(_bars_to_rows(merged), separators=(",", ":")))
        return merged


class BybitSpotOHLCVProvider:
    """Free Bybit v5 public spot kline (no key). Stdlib urllib + certifi SSL, disk-cached, separable parse fn.
    Bybit returns newest-first; the parse fn re-sorts ascending so the contract matches every other provider."""

    # Bybit v5 interval codes (minutes as strings, D/W/M for higher frames).
    _INTERVAL = {"1m": "1", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "4h": "240", "1d": "D", "1w": "W"}

    def __init__(
        self,
        cache_dir: Path | str = ".cosmu/market_data/bybit",
        *,
        now_fn=None,  # noqa: ANN001 — Callable[[], datetime]; injected by tests to pin the clock
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._now_fn = now_fn or (lambda: datetime.now(tz=UTC))

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        now = self._now_fn()
        cached = self._read_cache(symbol, timeframe)
        if len(cached) >= limit and _cache_is_fresh(cached, timeframe, now):
            return cached[-limit:]
        try:
            fetched = self._fetch_rest(symbol, timeframe, limit + 1)
        except Exception:  # noqa: BLE001 — offline/refused: a covering-but-stale cache still serves (degrade)
            fetched = []
        bars = _drop_unclosed(fetched, timeframe, now)
        if not bars:
            return cached[-limit:]  # network empty → never shrink; serve what we have
        return self._write_cache(symbol, timeframe, bars)[-limit:]

    def _fetch_rest(self, symbol: str, timeframe: str, limit: int) -> list[Bar]:
        interval = self._INTERVAL.get(timeframe, "D")
        query = urllib.parse.urlencode({"category": "spot", "symbol": symbol, "interval": interval, "limit": min(limit, 1000)})
        url = f"https://api.bybit.com/v5/market/kline?{query}"
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return _bars_from_bybit(payload)

    def _cache_path(self, symbol: str, timeframe: str) -> Path:
        safe = f"{symbol}_{timeframe}".replace("/", "")
        return self.cache_dir / f"{safe}.json"

    def _read_cache(self, symbol: str, timeframe: str) -> list[Bar]:
        path = self._cache_path(symbol, timeframe)
        if not path.exists():
            return []
        return [_bar_from_json(r) for r in json.loads(path.read_text())]

    def _write_cache(self, symbol: str, timeframe: str, bars: list[Bar]) -> list[Bar]:
        """Append-merge into the cache (never shrinks; atomic write); returns the merged bars."""
        merged = _merge_bars(self._read_cache(symbol, timeframe), bars)
        _atomic_write_text(self._cache_path(symbol, timeframe), json.dumps(_bars_to_rows(merged), separators=(",", ":")))
        return merged


class YahooDailyBarsProvider:
    """Free daily equity/ETF bars via the Yahoo Finance chart API (no key). Like Stooq it lists only
    CURRENTLY-traded symbols, so it is SURVIVORSHIP-BIASED (delisted names absent) — declared, not hidden:
    it proves cross-asset signal PRESENCE, not deployable capacity. Norgate replaces it at the live phase.
    Serves only CLOSED US sessions; a cache missing the latest expected session is refetched (never served
    forever), and offline it degrades to the cache."""

    survivorship_complete = False  # free bars have no delisted names — see class docstring

    def __init__(self, cache_dir: Path | str = ".cosmu/market_data/yahoo", *, now_fn=None) -> None:  # noqa: ANN001
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._now_fn = now_fn or (lambda: datetime.now(tz=UTC))

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        now = self._now_fn()
        cached = self._read_cache(symbol)
        if len(cached) >= limit and _equity_cache_is_fresh(cached, now):
            return cached[-limit:]
        try:
            fetched = self._fetch_chart(symbol)
        except Exception:  # noqa: BLE001 — offline/blocked: degrade to the cache, never crash the caller
            return cached[-limit:]
        fetched = _drop_unclosed_us_daily(fetched, now)
        if not fetched:
            return cached[-limit:]
        merged = _merge_bars(cached, fetched)
        self._write_cache(symbol, merged)
        return merged[-limit:]

    def _fetch_chart(self, symbol: str) -> list[Bar]:
        # Use an EXPLICIT epoch window (period1/period2), NOT range=max: Yahoo SILENTLY downgrades
        # range=max to MONTHLY bars (e.g. AAPL → ~168 month-start points) despite interval=1d, which
        # corrupts every "daily" backtest. A wide explicit window forces TRUE daily granularity. A real
        # browser User-Agent is also more reliable than a custom one.
        period2 = int(datetime.now(UTC).timestamp()) + 86_400  # now + 1d buffer
        query = urllib.parse.urlencode({"period1": 0, "period2": period2, "interval": "1d"})
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?{query}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return _bars_from_yahoo(payload)

    def _cache_path(self, symbol: str) -> Path:
        return self.cache_dir / f"{symbol.replace('/', '_')}_1d.json"

    def _read_cache(self, symbol: str) -> list[Bar]:
        path = self._cache_path(symbol)
        if not path.exists():
            return []
        bars = [_bar_from_json(r) for r in json.loads(path.read_text())]
        if bars and not _is_daily_spaced(bars):
            # poisoned cache: MONTHLY bars from the old `range=max` downgrade. Drop it so fetch_bars
            # re-fetches true daily history (the file is overwritten on the next successful fetch).
            return []
        return bars

    def _write_cache(self, symbol: str, bars: list[Bar]) -> None:
        _atomic_write_text(self._cache_path(symbol), json.dumps(_bars_to_rows(bars), separators=(",", ":")))


class EquityOHLCVProvider:
    """Read-only provider that serves the pre-populated `.cosmu/market_data/equities/` cache.
    Does NOT fetch live — the equity cache is maintained by research/equity_* backfill scripts.
    Implements the MarketDataProvider protocol so the finder can blend equity bars alongside crypto."""

    survivorship_complete = False  # Alpaca/Yahoo data has no delisted names — see StooqDailyBarsProvider

    def __init__(self, cache_dir: Path | str = ".cosmu/market_data/equities") -> None:
        self.cache_dir = Path(cache_dir)

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        path = self.cache_dir / f"{symbol}_{timeframe}.json"
        if not path.exists():
            return []
        bars = [_bar_from_json(r) for r in json.loads(path.read_text())]
        return bars[-limit:] if len(bars) > limit else bars

    def available_symbols(self, timeframe: str = "1d") -> list[str]:
        """Sorted list of all symbols that have a cached file for the given timeframe."""
        suffix = f"_{timeframe}.json"
        if not self.cache_dir.exists():
            return []
        return sorted(p.name[: -len(suffix)] for p in self.cache_dir.glob(f"*{suffix}") if p.is_file())


class HyperliquidOHLCVProvider:
    """Read-only provider serving the Hyperliquid perpetual cache at `.cosmu/market_data/hyperliquid/`.
    Cache is populated by `scripts/ingest_hyperliquid_bars.py` (public REST, no key). Does NOT
    fetch live — cache is the source of truth. Symbols are {COIN}USDC (e.g. BTCUSDC)."""

    survivorship_complete = False  # HL lists only currently-traded perpetuals

    def __init__(self, cache_dir: Path | str = ".cosmu/market_data/hyperliquid") -> None:
        self.cache_dir = Path(cache_dir)

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        path = self.cache_dir / f"{symbol}_{timeframe}.json"
        if not path.exists():
            return []
        bars = [_bar_from_json(r) for r in json.loads(path.read_text())]
        return bars[-limit:] if len(bars) > limit else bars

    def available_symbols(self, timeframe: str = "1d") -> list[str]:
        """Sorted list of symbols with a cached file for the given timeframe (e.g. 'BTCUSDC')."""
        suffix = f"_{timeframe}.json"
        if not self.cache_dir.exists():
            return []
        return sorted(p.name[: -len(suffix)] for p in self.cache_dir.glob(f"*{suffix}") if p.is_file())


def _is_daily_spaced(bars: list[Bar]) -> bool:
    """True DAILY bars have consecutive-trading-day gaps (1-4 calendar days incl. weekends/holidays);
    MONTHLY bars (from the old Yahoo `range=max` downgrade) have ~28-31 day gaps. Median-gap test —
    used to detect + invalidate poisoned daily caches."""
    if len(bars) < 5:
        return True
    gaps = sorted((bars[i].ts - bars[i - 1].ts).days for i in range(1, len(bars)))
    return gaps[len(gaps) // 2] <= 7


def _ccxt_symbol(symbol: str) -> str:
    if "/" in symbol:
        return symbol
    if symbol.endswith("USDT"):
        return f"{symbol[:-4]}/USDT"
    return symbol


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def _merge_bars(existing: list[Bar], fetched: list[Bar]) -> list[Bar]:
    """Union two bar lists deduped on ts, ascending. `fetched` wins on a ts collision: a genuinely closed bar
    is immutable so this is a no-op for it, but a row CACHED while its candle was still forming (the pre-fix
    22:10 cron snapshotting the in-progress daily candle) must be repaired by the exchange's final values, not
    frozen forever. Still a union — the never-shrink invariant holds: merging a short fetched page with a deep
    cache can only ADD or REPAIR bars, never remove one."""
    merged: dict[datetime, Bar] = {b.ts: b for b in existing}
    merged.update({b.ts: b for b in fetched})
    return sorted(merged.values(), key=lambda b: b.ts)


def _bars_to_rows(bars: list[Bar]) -> list[dict[str, int | str]]:
    """Serialize Bars to the on-disk cache row shape (ts in ms; OHLCV as strings to preserve Decimals)."""
    return [
        {"ts": int(b.ts.timestamp() * 1000), "open": str(b.open), "high": str(b.high),
         "low": str(b.low), "close": str(b.close), "volume": str(b.volume)}
        for b in bars
    ]


def _atomic_write_text(path: Path, text: str) -> None:
    """Write `text` to `path` atomically (unique temp file in the same dir + os.replace) so a concurrent
    reader never observes a half-written/truncated cache — the torn-write race that let parallel harness
    runs across worktrees corrupt the shared bar cache."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _bar_from_ccxt(row: list[float | int]) -> Bar:
    ts, open_, high, low, close, volume = row[:6]
    return Bar(
        ts=datetime.fromtimestamp(float(ts) / 1000, tz=UTC),
        open=Decimal(str(open_)),
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=Decimal(str(close)),
        volume=Decimal(str(volume)),
    )


def _bar_from_binance(row: list[str | int]) -> Bar:
    return Bar(
        ts=datetime.fromtimestamp(int(row[0]) / 1000, tz=UTC),
        open=Decimal(str(row[1])),
        high=Decimal(str(row[2])),
        low=Decimal(str(row[3])),
        close=Decimal(str(row[4])),
        volume=Decimal(str(row[5])),
    )


def _bar_from_json(row: dict[str, str | int]) -> Bar:
    return Bar(
        ts=datetime.fromtimestamp(int(row["ts"]) / 1000, tz=UTC),
        open=Decimal(str(row["open"])),
        high=Decimal(str(row["high"])),
        low=Decimal(str(row["low"])),
        close=Decimal(str(row["close"])),
        volume=Decimal(str(row["volume"])),
    )


def _kraken_pair(symbol: str) -> str:
    """Map our exchange symbol (BTCUSDT) to Kraken's pair convention (XBTUSD). USDT pairs map to USD
    spot since Kraken's deepest fiat books are USD; pass-through anything already Kraken-shaped."""
    s = symbol.upper()
    base, quote = (s[:-4], s[-4:]) if s.endswith("USDT") else (s[:-3], s[-3:]) if s.endswith("USD") else (s, "")
    base = "XBT" if base == "BTC" else base
    quote = "USD" if quote == "USDT" else (quote or "USD")
    return f"{base}{quote}"


def _bars_from_kraken(payload: dict) -> list[Bar]:
    """Kraken OHLC: {"error": [...], "result": {"<pair>": [[time, o, h, l, c, vwap, volume, count], ...]}}.
    The pair key under `result` varies (XXBTZUSD etc.), so we take the first non-"last" series."""
    result = payload.get("result", {})
    rows: list = []
    for key, value in result.items():
        if key == "last":
            continue
        rows = value
        break
    out: list[Bar] = []
    for row in rows:
        out.append(
            Bar(
                ts=datetime.fromtimestamp(int(row[0]), tz=UTC),
                open=Decimal(str(row[1])),
                high=Decimal(str(row[2])),
                low=Decimal(str(row[3])),
                close=Decimal(str(row[4])),
                volume=Decimal(str(row[6])),
            )
        )
    return sorted(out, key=lambda b: b.ts)


def _bars_from_bybit(payload: dict) -> list[Bar]:
    """Bybit v5 kline: {"result": {"list": [[startMs, open, high, low, close, volume, turnover], ...]}}.
    The list is NEWEST-first; re-sort ascending so the contract matches every other provider."""
    rows = payload.get("result", {}).get("list", [])
    out: list[Bar] = []
    for row in rows:
        out.append(
            Bar(
                ts=datetime.fromtimestamp(int(row[0]) / 1000, tz=UTC),
                open=Decimal(str(row[1])),
                high=Decimal(str(row[2])),
                low=Decimal(str(row[3])),
                close=Decimal(str(row[4])),
                volume=Decimal(str(row[5])),
            )
        )
    return sorted(out, key=lambda b: b.ts)


def _bars_from_yahoo(payload: dict) -> list[Bar]:
    """Yahoo chart API: result[0] has `timestamp` (epoch seconds) and parallel indicators.quote[0]
    OHLCV arrays. Yahoo emits None for gap days (holidays); those rows are skipped, not zero-filled."""
    results = payload.get("chart", {}).get("result") or []
    if not results:
        return []
    res = results[0]
    timestamps = res.get("timestamp") or []
    quote = (res.get("indicators", {}).get("quote") or [{}])[0]
    opens, highs, lows, closes, volumes = (
        quote.get("open") or [], quote.get("high") or [], quote.get("low") or [],
        quote.get("close") or [], quote.get("volume") or [],
    )
    out: list[Bar] = []
    for i, ts in enumerate(timestamps):
        o, h, lo, c = opens[i], highs[i], lows[i], closes[i]
        if None in (o, h, lo, c):  # Yahoo gap day — no bar, never zero-fill (that would fabricate price)
            continue
        out.append(
            Bar(
                ts=datetime.fromtimestamp(int(ts), tz=UTC),
                open=Decimal(str(o)),
                high=Decimal(str(h)),
                low=Decimal(str(lo)),
                close=Decimal(str(c)),
                volume=Decimal(str(volumes[i] if i < len(volumes) and volumes[i] is not None else 0)),
            )
        )
    return sorted(out, key=lambda b: b.ts)
