# intent: the REAL-DATA panel loader for the deep astro study — genuine prices (Binance public klines + Yahoo
# daily equity bars) plus the genuine 13.6M-row prod `alt_data` table, PIT-joined onto each symbol's bar grid so
# astro can be tested AGAINST and ON TOP OF real signals (social/funding/macro/onchain). No fabrication anywhere:
# prices come from the live public APIs (with the engine's trusted equity provider), alt-data comes from prod
# Postgres READ-ONLY, and the as-of join NEVER lets a point published after a bar leak into that bar.
#
# PIT join: pure SQL pull of (ts, available_at, value) per (symbol, metric) ordered by available_at, then a
# one-pass merge identical in spirit to cosmu.data.backtest.align_asof — each bar takes the LATEST point whose
# available_at <= bar_ts. We do NOT reuse align_asof's list[Bar]/list[AltDataPoint] objects (we have raw rows and
# a DatetimeIndex), but the rule is byte-for-byte the same: a future revision can never reach a past bar.
#
# Connection: ONE psycopg2 connection, ONE cursor, batched per metric. The Supabase DATABASE_URL carries a
# '?pgbouncer=true' param libpq rejects — we strip non-libpq query params and force sslmode=require. READ-ONLY:
# the session is set to read-only and we issue only SELECTs; this module never writes a row.

from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pandas as pd

# Make the engine `cosmu` package importable when this file is run directly (the equity loader reuses it).
ENGINE_ROOT = Path(__file__).resolve().parents[3]
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

# ── prices: crypto (Binance public klines) ─────────────────────────────────────────────────────────

_BINANCE_KLINES = "https://api.binance.com/api/v3/klines"
_BINANCE_MAX = 1000  # the hard per-request row cap we paginate past

# timeframe → (binance interval string, milliseconds per bar)
_TF: dict[str, tuple[str, int]] = {
    "1d": ("1d", 86_400_000),
    "1h": ("1h", 3_600_000),
}


def _ssl_ctx() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _http_json(url: str, timeout: int = 30):  # noqa: ANN202
    req = urllib.request.Request(url, headers={"User-Agent": "cosmu-research/0.1"})
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load_crypto_bars(
    symbols: list[str], timeframe: str = "1d", days: int = 3650
) -> dict[str, pd.DataFrame]:
    """REAL Binance spot OHLCV via the public klines REST endpoint, PAGINATED past the 1000-row cap.

    Returns {symbol -> DataFrame} indexed by tz-naive UTC timestamp with float columns
    ['open','high','low','close','volume'], ascending, the in-progress final candle DROPPED. A symbol that
    fails to fetch gets an empty (honest) frame rather than fabricated bars."""
    if timeframe not in _TF:
        raise ValueError(f"timeframe must be one of {sorted(_TF)}, got {timeframe!r}")
    interval, ms_per_bar = _TF[timeframe]
    now_ms = int(datetime.now(tz=UTC).timestamp() * 1000)
    start_ms = now_ms - days * 86_400_000

    out: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        rows: list[list] = []
        cursor = start_ms
        try:
            while cursor < now_ms:
                q = urllib.parse.urlencode(
                    {
                        "symbol": sym,
                        "interval": interval,
                        "startTime": cursor,
                        "limit": _BINANCE_MAX,
                    }
                )
                batch = _http_json(f"{_BINANCE_KLINES}?{q}")
                if not batch:
                    break
                rows.extend(batch)
                last_open = batch[-1][0]
                nxt = last_open + ms_per_bar
                if nxt <= cursor:  # no forward progress — stop (defensive)
                    break
                cursor = nxt
                if len(batch) < _BINANCE_MAX:  # caught up to the live edge
                    break
        except Exception:  # noqa: BLE001 — blocked/offline is an honest empty, never fabricated
            out[sym] = _empty_bars()
            continue
        out[sym] = _binance_rows_to_frame(rows, now_ms, ms_per_bar)
    return out


def _empty_bars() -> pd.DataFrame:
    idx = pd.DatetimeIndex([], name="ts")
    return pd.DataFrame(
        {c: pd.Series(dtype=float) for c in ("open", "high", "low", "close", "volume")}, index=idx
    )


def _binance_rows_to_frame(rows: list[list], now_ms: int, ms_per_bar: int) -> pd.DataFrame:
    if not rows:
        return _empty_bars()
    # Binance kline: [openTime, open, high, low, close, volume, closeTime, ...]. Dedup on openTime
    # (overlapping pages can repeat the boundary bar), keep the last seen.
    by_open: dict[int, list] = {}
    for r in rows:
        by_open[int(r[0])] = r
    recs = []
    for open_ms in sorted(by_open):
        # DROP the in-progress candle: its close time is still in the future.
        if open_ms + ms_per_bar > now_ms:
            continue
        r = by_open[open_ms]
        recs.append(
            {
                "ts": datetime.fromtimestamp(open_ms / 1000, tz=UTC).replace(tzinfo=None),
                "open": float(r[1]),
                "high": float(r[2]),
                "low": float(r[3]),
                "close": float(r[4]),
                "volume": float(r[5]),
            }
        )
    if not recs:
        return _empty_bars()
    df = pd.DataFrame.from_records(recs).set_index("ts")
    df.index.name = "ts"
    return df[["open", "high", "low", "close", "volume"]].astype(float)


# ── prices: equity / ETF (engine's trusted Yahoo provider; Stooq is PoW-blocked) ──────────────────────


def load_equity_bars(symbols: list[str], limit: int = 2600) -> dict[str, pd.DataFrame]:
    """REAL daily equity/ETF bars by REUSING the engine: cosmu.data.market.YahooDailyBarsProvider. Same
    DataFrame shape as load_crypto_bars (tz-naive UTC index, float OHLCV), daily. SURVIVORSHIP-BIASED (the free
    feed lists only currently-traded names) — declared by the provider, fine for signal-PRESENCE research."""
    from cosmu.data.market import YahooDailyBarsProvider

    provider = YahooDailyBarsProvider()
    out: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        try:
            bars = provider.fetch_bars(sym, "1d", limit=limit)
        except Exception:  # noqa: BLE001 — offline/blocked is an honest empty
            out[sym] = _empty_bars()
            continue
        if not bars:
            out[sym] = _empty_bars()
            continue
        recs = [
            {
                "ts": b.ts.astimezone(UTC).replace(tzinfo=None) if b.ts.tzinfo else b.ts,
                "open": float(b.open),
                "high": float(b.high),
                "low": float(b.low),
                "close": float(b.close),
                "volume": float(b.volume),
            }
            for b in bars
        ]
        df = pd.DataFrame.from_records(recs).set_index("ts").sort_index()
        df.index.name = "ts"
        out[sym] = df[["open", "high", "low", "close", "volume"]].astype(float)
    return out


# ── real alt-data from prod Postgres (READ-ONLY) ────────────────────────────────────────────────────

# The metrics with usable multi-year history in the prod alt_data table, grouped by family. Verified live
# against the prod table (provider/symbol/metric/ts coverage), not assumed:
#
#   social   (LunarCrush, PER-SYMBOL keyed by BASE asset e.g. 'BTC', 2020-01-01+):
#       galaxy_score, social_volume, social_sentiment, alt_rank, social_dominance, market_dominance,
#       contributors_active, posts_active, spam, volume_24h_usd, market_cap_usd
#   funding  (PER-SYMBOL keyed by FULL pair e.g. 'BTCUSDT'; providers binance 2023-09-12+ and okx_perp):
#       funding_rate
#   macro    (MARKET-wide; providers alternative.me/fred/stooq, 2022-06+):
#       fear_greed, vix_level, vix_term_slope, dxy, yield_curve_2s10s, credit_spread, fed_funds_rate,
#       gold_xau, silver_xag, wti_crude, spx_index, ndx_index, eurusd, usdjpy, macro_regime
#   onchain  (MARKET-wide; provider blockchain.com, history back to 2009):
#       btc_hashrate, btc_tx_count, btc_active_addresses
REAL_ALT_DEEP: list[str] = [
    # social (per-symbol, base-asset key)
    "galaxy_score",
    "social_volume",
    "social_sentiment",
    "alt_rank",
    "social_dominance",
    "market_dominance",
    "contributors_active",
    "posts_active",
    "spam",
    "volume_24h_usd",
    "market_cap_usd",
    # funding (per-symbol, full-pair key)
    "funding_rate",
    # macro (MARKET-wide)
    "fear_greed",
    "vix_level",
    "vix_term_slope",
    "dxy",
    "yield_curve_2s10s",
    "credit_spread",
    "fed_funds_rate",
    "gold_xau",
    "silver_xag",
    "wti_crude",
    "spx_index",
    "ndx_index",
    "eurusd",
    "usdjpy",
    "macro_regime",
    # onchain (MARKET-wide)
    "btc_hashrate",
    "btc_tx_count",
    "btc_active_addresses",
]

# Which of the above are stored under symbol='MARKET' (broadcast to every requested symbol). The remainder are
# per-symbol: social → base-asset key, funding_rate → full-pair key.
MARKET_WIDE_METRICS: set[str] = {
    "fear_greed",
    "vix_level",
    "vix_term_slope",
    "dxy",
    "yield_curve_2s10s",
    "credit_spread",
    "fed_funds_rate",
    "gold_xau",
    "silver_xag",
    "wti_crude",
    "spx_index",
    "ndx_index",
    "eurusd",
    "usdjpy",
    "macro_regime",
    "btc_hashrate",
    "btc_tx_count",
    "btc_active_addresses",
}

# funding_rate is the only per-symbol metric keyed by the FULL pair (BTCUSDT); the LunarCrush social metrics
# are keyed by the BASE asset (BTC). Used to decide the candidate key list for a per-symbol metric.
_FULL_PAIR_METRICS: set[str] = {"funding_rate"}


def _dsn_from_env() -> str:
    """Build a libpq-clean DSN from DATABASE_URL: strip the Supabase-only '?pgbouncer'/'connection_limit'
    params psycopg2 rejects, and force sslmode=require."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set — `set -a; . <repo>/.env.local; set +a` first"
        )
    p = urlsplit(url)
    q = [(k, v) for k, v in parse_qsl(p.query) if k.lower() not in ("pgbouncer", "connection_limit")]
    if not any(k == "sslmode" for k, _ in q):
        q.append(("sslmode", "require"))
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(q), p.fragment))


def _base_asset(symbol: str) -> str:
    """The LunarCrush base-asset key for a pair: strip a trailing USDT/USDC/USD quote ('BTCUSDT' -> 'BTC').
    A non-pair symbol (already a base) is returned unchanged."""
    s = symbol.upper()
    for quote in ("USDT", "USDC", "USD"):
        if s.endswith(quote) and len(s) > len(quote):
            return s[: -len(quote)]
    return s


def _candidate_keys(symbol: str, metric: str) -> list[str]:
    """The alt_data `symbol` keys to try for a (symbol, metric), in priority order. MARKET-wide metrics use
    'MARKET'. Full-pair metrics (funding) try the exact pair first. Everything else (social) tries the exact
    symbol then the base asset — robust whether the caller passes 'BTC' or 'BTCUSDT'."""
    if metric in MARKET_WIDE_METRICS:
        return ["MARKET"]
    if metric in _FULL_PAIR_METRICS:
        keys = [symbol.upper()]
        base = _base_asset(symbol)
        if base != symbol.upper():
            keys.append(base)  # tolerate a base-keyed pair if the venue stored it that way
        return keys
    # social: per-symbol by base asset
    keys = []
    if symbol.upper() not in keys:
        keys.append(symbol.upper())
    base = _base_asset(symbol)
    if base not in keys:
        keys.append(base)
    return keys


def _parse_ts(text: str) -> datetime:
    """Parse an ISO-8601 alt_data ts/available_at (text column, e.g. '2024-01-02T00:00:00+00:00') into a
    tz-naive UTC datetime so it compares directly against the tz-naive bar index."""
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt


def _fetch_metric_by_key(cur, keys: list[str], metric: str, since: str) -> dict[str, list[tuple[datetime, float]]]:
    """ONE batched query per metric: pull (symbol, available_at, value) for ALL candidate `keys` at once via
    symbol = ANY(%s), bounded by ts >= `since`. Returns {key: sorted [(available_at, value)]}. Batching collapses
    what was 100+ transatlantic round-trips into ~1 per metric; the date bound caps the row count. Provider is
    left free so a multi-provider metric (e.g. funding binance+okx) is unioned across the same key."""
    cur.execute(
        """
        SELECT symbol, available_at, value
        FROM alt_data
        WHERE symbol = ANY(%s) AND metric = %s AND ts >= %s
        ORDER BY symbol, available_at ASC
        """,
        (list(keys), metric, since),
    )
    by_key: dict[str, list[tuple[datetime, float]]] = {}
    for sym, avail_txt, val in cur.fetchall():
        if val is None:
            continue
        by_key.setdefault(sym, []).append((_parse_ts(avail_txt), float(val)))
    for pts in by_key.values():
        pts.sort(key=lambda t: t[0])
    return by_key


def _asof_join(points: list[tuple[datetime, float]], index: pd.DatetimeIndex) -> pd.Series:
    """Point-in-time as-of join: each bar ts gets the LATEST point whose available_at <= ts. Identical rule to
    cosmu.data.backtest.align_asof — a point published after the bar is NEVER used (no look-ahead). Bars before
    the first available point are NaN (exactly as if the data did not exist yet). One forward pass, O(n+m)."""
    s = pd.Series(index=index, dtype=float)
    if not points or len(index) == 0:
        return s
    ordered = sorted(index)  # the index may already be sorted; be defensive
    vals = {}
    i = 0
    current: float | None = None
    n = len(points)
    for ts in ordered:
        ts_py = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
        while i < n and points[i][0] <= ts_py:
            current = points[i][1]
            i += 1
        if current is not None:
            vals[ts] = current
    if vals:
        s.loc[list(vals.keys())] = list(vals.values())
    return s


def load_real_alt_panel(
    symbols: list[str],
    metrics: list[str],
    bar_index_by_symbol: dict[str, pd.DatetimeIndex],
) -> dict[str, pd.DataFrame]:
    """PIT-join the REAL prod alt_data onto each symbol's bar grid.

    For each symbol, returns a DataFrame indexed by that symbol's bar index with one column per metric. The
    value at bar ts is the latest alt point with available_at <= ts (NO look-ahead). Market-wide metrics
    ('MARKET' key) broadcast to every symbol; per-symbol metrics are keyed by the appropriate symbol form
    (social → base asset, funding → full pair). READ-ONLY: a read-only session issuing only SELECTs.

    ONE batched query per metric (symbol = ANY(...)), bounded by ts >= earliest bar date, with a statement
    timeout + keepalives so a stalled pooler can never hang. The assembled panel is CACHED to local parquet so
    the heavy run and re-runs never re-hit the slow EU DB."""
    import hashlib
    import pickle

    import psycopg2

    # local cache key — symbols + metrics + each symbol's [min..max] date span
    span = {s: (str(ix.min()), str(ix.max()), len(ix)) for s, ix in bar_index_by_symbol.items() if len(ix)}
    key = hashlib.md5(repr((sorted(symbols), sorted(metrics), sorted(span.items()))).encode()).hexdigest()[:16]
    cache = Path("/tmp/cosmu_astro_cache/altpanel") / f"{key}.pkl"
    if cache.exists():
        try:
            return pickle.loads(cache.read_bytes())
        except Exception:  # noqa: BLE001
            pass

    since = min((str(ix.min())[:10] for ix in bar_index_by_symbol.values() if len(ix)), default="2009-01-01")
    # union of candidate keys across all symbols → resolve which key actually has rows after the batched fetch
    all_keys: set[str] = {"MARKET"}
    for s in symbols:
        all_keys.update(_candidate_keys(s, "social_volume"))  # exact + base-asset forms
    conn = psycopg2.connect(
        _dsn_from_env(), connect_timeout=20, options="-c statement_timeout=120000",
        keepalives=1, keepalives_idle=20, keepalives_interval=10, keepalives_count=5,
    )
    out: dict[str, pd.DataFrame] = {s: pd.DataFrame(index=bar_index_by_symbol.get(s, pd.DatetimeIndex([], name="ts")))
                                   for s in symbols}
    try:
        conn.set_session(readonly=True)
        cur = conn.cursor()
        for metric in metrics:
            keys = ["MARKET"] if metric in MARKET_WIDE_METRICS else sorted(all_keys)
            by_key = _fetch_metric_by_key(cur, keys, metric, since)
            for s in symbols:
                index = bar_index_by_symbol.get(s, pd.DatetimeIndex([], name="ts"))
                if metric in MARKET_WIDE_METRICS:
                    points = by_key.get("MARKET", [])
                else:
                    points = next((by_key[k] for k in _candidate_keys(s, metric) if by_key.get(k)), [])
                out[s][metric] = _asof_join(points, index)
        cur.close()
    finally:
        conn.close()
    for s in symbols:
        out[s].index.name = "ts"
    cache.parent.mkdir(parents=True, exist_ok=True)
    try:
        cache.write_bytes(pickle.dumps(out))
    except Exception:  # noqa: BLE001
        pass
    return out


# ── self-test ─────────────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 88)
    print("real_panel self-test — REAL Binance bars + REAL prod alt_data PIT join")
    print("=" * 88)

    # 1) crypto bars
    sym_list = ["BTCUSDT", "ETHUSDT"]
    bars = load_crypto_bars(sym_list, timeframe="1d", days=3650)
    bar_index_by_symbol: dict[str, pd.DatetimeIndex] = {}
    for s in sym_list:
        df = bars[s]
        bar_index_by_symbol[s] = df.index
        if len(df):
            print(
                f"\n{s}: {len(df)} daily bars  {df.index.min().date()} .. {df.index.max().date()}"
                f"  last_close={df['close'].iloc[-1]:.2f}"
            )
        else:
            print(f"\n{s}: EMPTY (honest — fetch blocked/offline)")

    # 2) PIT alt panel — one metric per family
    metrics = ["galaxy_score", "funding_rate", "fear_greed", "vix_level", "btc_hashrate"]
    print(f"\nloading real alt panel for {sym_list} · metrics={metrics}")
    panel = load_real_alt_panel(sym_list, metrics, bar_index_by_symbol)

    for s in sym_list:
        df = panel[s]
        print(f"\n--- {s} alt panel: {df.shape[0]} rows × {df.shape[1]} metrics ---")
        n = len(df) if len(df) else 1
        for m in metrics:
            col = df[m]
            cov = 100.0 * col.notna().sum() / n
            nun = int(col.dropna().nunique())
            if col.notna().any():
                lo, hi = float(col.min()), float(col.max())
                print(
                    f"  {m:18s} coverage={cov:6.1f}%  distinct={nun:>5}  "
                    f"range=[{lo:.4g}, {hi:.4g}]  {'CONSTANT!' if nun <= 1 else ''}"
                )
            else:
                print(f"  {m:18s} coverage={cov:6.1f}%  (all-NaN over this bar range)")
        # a sample joined row near the end where every family should be populated
        non_null = df.dropna(how="all")
        if len(non_null):
            full = non_null.dropna()
            sample = (full.iloc[-1] if len(full) else non_null.iloc[-1])
            print(f"  sample joined row @ {sample.name.date()}:")
            for m in metrics:
                print(f"      {m:18s} = {sample.get(m)}")

    print("\n" + "=" * 88)
    print("DataFrame schema (per symbol):")
    print("  index : tz-naive UTC DatetimeIndex (the symbol's bar grid)")
    print(f"  columns: {metrics}  (float, PIT as-of: latest available_at <= bar ts)")
    print("self-test DONE")
