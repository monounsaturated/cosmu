#!/usr/bin/env python3
"""
Polymarket lead-lag audit.
Queries alt_data for pm_implied_prob / pm_prob_velocity / pm_book_depth,
fetches Binance daily closes for BTCUSDT + ETHUSDT, then computes
Pearson cross-correlations at lags 1-7 days.

No manufacturing: exits if data is thin.
"""

from __future__ import annotations

import os
import sys
import json
import ssl
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, UTC
from pathlib import Path

import psycopg2
import psycopg2.extras


# ── DB ────────────────────────────────────────────────────────────────────────

def get_db_url() -> str:
    for src in [".env.local", ".env"]:
        p = Path(src)
        if p.exists():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line.startswith("DATABASE_URL="):
                    url = line.split("=", 1)[1].split("#")[0].strip()
                    # psycopg2 rejects ?pgbouncer=true — strip it
                    if "?" in url:
                        base, qs = url.split("?", 1)
                        kept = "&".join(p for p in qs.split("&") if not p.startswith("pgbouncer"))
                        url = f"{base}?{kept}" if kept else base
                    return url
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        sys.exit("ERROR: DATABASE_URL not found in .env.local or environment")
    return url


def query_alt_data(db_url: str) -> dict:
    """Return coverage summary + all rows for each polymarket metric."""
    conn = psycopg2.connect(db_url)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # ── coverage summary ────────────────────────────────────────────────────
    cur.execute("""
        SELECT provider, symbol, metric,
               COUNT(*) AS rows,
               MIN(ts)  AS first_ts,
               MAX(ts)  AS last_ts
        FROM alt_data
        WHERE provider = 'polymarket'
        GROUP BY provider, symbol, metric
        ORDER BY metric
    """)
    coverage = cur.fetchall()

    # ── raw series ──────────────────────────────────────────────────────────
    cur.execute("""
        SELECT metric, ts, value
        FROM alt_data
        WHERE provider = 'polymarket'
        ORDER BY metric, ts
    """)
    rows = cur.fetchall()
    conn.close()

    by_metric: dict[str, dict[str, float]] = {}
    for row in rows:
        m = row["metric"]
        d = row["ts"][:10]          # keep YYYY-MM-DD only
        by_metric.setdefault(m, {})[d] = float(row["value"])

    return {"coverage": [dict(r) for r in coverage], "series": by_metric}


# ── Binance daily closes ──────────────────────────────────────────────────────

def fetch_binance_daily(symbol: str, start: str, end: str) -> dict[str, float]:
    """
    Fetch daily OHLCV from Binance REST klines endpoint.
    Returns {date_str: close_price}.
    """
    base = "https://api.binance.com/api/v3/klines"
    start_ms = int(datetime.fromisoformat(start).replace(tzinfo=UTC).timestamp() * 1000)
    end_ms   = int((datetime.fromisoformat(end) + timedelta(days=1)).replace(tzinfo=UTC).timestamp() * 1000)
    ctx = ssl.create_default_context()

    results: dict[str, float] = {}
    since = start_ms
    while since < end_ms:
        params = urllib.parse.urlencode({
            "symbol": symbol,
            "interval": "1d",
            "startTime": since,
            "endTime": end_ms,
            "limit": 1000,
        })
        req = urllib.request.Request(f"{base}?{params}", headers={"User-Agent": "cosmu/2"})
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            data = json.loads(resp.read())
        if not data:
            break
        for row in data:
            d = datetime.fromtimestamp(row[0] / 1000, tz=UTC).strftime("%Y-%m-%d")
            results[d] = float(row[4])     # close
        since = data[-1][0] + 86_400_000   # next day
    return results


# ── lead-lag correlation ──────────────────────────────────────────────────────

def pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 20:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx  = (sum((x - mx) ** 2 for x in xs)) ** 0.5
    dy  = (sum((y - my) ** 2 for y in ys)) ** 0.5
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def compute_lead_lag(
    signal: dict[str, float],       # predictor (pm_prob_velocity)
    price:  dict[str, float],        # USDT close
    lags: range,
) -> dict[int, dict]:
    """
    For each lag k in lags: align signal[t] with price[t+k].
    Returns {lag: {n, corr, signal_dates}}.
    """
    all_dates = sorted(set(signal) & set(price))
    results = {}
    for lag in lags:
        pairs = []
        for d in all_dates:
            future = (datetime.fromisoformat(d) + timedelta(days=lag)).strftime("%Y-%m-%d")
            if future in price:
                sig_val = signal[d]
                # use log-return of price
                prev = (datetime.fromisoformat(future) - timedelta(days=1)).strftime("%Y-%m-%d")
                if prev in price and price[prev] > 0:
                    ret = (price[future] - price[prev]) / price[prev]
                    pairs.append((sig_val, ret))
        if pairs:
            xs, ys = zip(*pairs)
            r = pearson(list(xs), list(ys))
        else:
            r = None
        results[lag] = {"n": len(pairs), "corr": r}
    return results


# ── gap analysis ──────────────────────────────────────────────────────────────

def find_gaps(series: dict[str, float]) -> list[str]:
    """Return date strings where a daily series has a gap (missing day)."""
    dates = sorted(series)
    gaps = []
    for i in range(1, len(dates)):
        prev = datetime.fromisoformat(dates[i - 1])
        curr = datetime.fromisoformat(dates[i])
        delta = (curr - prev).days
        if delta > 1:
            for d in range(1, delta):
                gaps.append((prev + timedelta(days=d)).strftime("%Y-%m-%d"))
    return gaps


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    db_url = get_db_url()
    print("Connecting to DB …")
    result = query_alt_data(db_url)
    coverage = result["coverage"]
    series   = result["series"]

    # ── 1. Coverage report ──────────────────────────────────────────────────
    print("\n═══════════════════════════════════════")
    print(" POLYMARKET alt_data coverage")
    print("═══════════════════════════════════════")
    if not coverage:
        print("NO ROWS FOUND for provider='polymarket'")
        return

    for c in coverage:
        metric = c["metric"]
        first  = c["first_ts"][:10]
        last   = c["last_ts"][:10]
        n_days = (datetime.fromisoformat(last) - datetime.fromisoformat(first)).days + 1
        gaps   = find_gaps(series.get(metric, {}))
        print(f"\n  metric : {metric}")
        print(f"  rows   : {c['rows']}")
        print(f"  span   : {first}  →  {last}  ({n_days} calendar days)")
        print(f"  gaps   : {len(gaps)}" + (f" {gaps[:5]}" if gaps else " (none)"))

    # ── 2. Determine analysis window ────────────────────────────────────────
    vel = series.get("pm_prob_velocity", {})
    if not vel:
        print("\nFAIL: pm_prob_velocity not present in DB — cannot run lead-lag.")
        return

    first_date = sorted(vel)[0]
    last_date  = sorted(vel)[-1]
    n_vel = len(vel)

    MIN_ROWS = 60   # need 60+ paired observations for meaningful correlation
    if n_vel < MIN_ROWS:
        print(f"\nDATA TOO THIN — {n_vel} rows of pm_prob_velocity. Need ≥{MIN_ROWS}.")
        print("Recommendation: backfill to 180+ days before running lead-lag.")
        return

    # ── 3. Fetch Binance price data ──────────────────────────────────────────
    symbols = ["BTCUSDT", "ETHUSDT"]
    print(f"\nFetching Binance daily closes for {symbols} from {first_date} …")
    prices: dict[str, dict[str, float]] = {}
    for sym in symbols:
        try:
            prices[sym] = fetch_binance_daily(sym, first_date, last_date)
            print(f"  {sym}: {len(prices[sym])} days")
        except Exception as e:
            print(f"  {sym}: FETCH FAILED — {e}")

    # ── 4. Lead-lag correlations ─────────────────────────────────────────────
    print("\n═══════════════════════════════════════")
    print(" LEAD-LAG CORRELATIONS  (pm_prob_velocity → price return)")
    print("═══════════════════════════════════════")
    print(" Positive corr: rising prediction-market momentum predicts positive price return")
    print()

    LAGS = range(1, 8)
    all_results: dict[str, dict[int, dict]] = {}

    for sym, price_series in prices.items():
        if not price_series:
            continue
        lag_results = compute_lead_lag(vel, price_series, LAGS)
        all_results[sym] = lag_results
        print(f"  {sym}")
        print(f"  {'lag':>5}  {'n':>6}  {'corr':>8}  {'signal'}")
        print(f"  {'─'*5}  {'─'*6}  {'─'*8}  {'─'*20}")
        for lag, v in lag_results.items():
            r = v["corr"]
            n = v["n"]
            if r is None:
                sig = "insufficient data"
            elif abs(r) < 0.05:
                sig = "noise"
            elif abs(r) < 0.12:
                sig = "weak"
            elif abs(r) < 0.20:
                sig = "moderate"
            else:
                sig = "STRONG"
            r_str = f"{r:+.4f}" if r is not None else "  n/a"
            print(f"  {lag:>5}d  {n:>6}  {r_str}  {sig}")
        print()

    # ── 5. Verdict ────────────────────────────────────────────────────────────
    print("═══════════════════════════════════════")
    print(" VERDICT")
    print("═══════════════════════════════════════")

    best: list[tuple[float, str, int]] = []
    for sym, lag_map in all_results.items():
        for lag, v in lag_map.items():
            r = v["corr"]
            n = v["n"]
            if r is not None and n >= MIN_ROWS:
                best.append((abs(r), sym, lag, r, n))  # type: ignore[arg-type]

    if not best:
        print("NO SIGNAL — all lags have insufficient data.")
        return

    best_sorted = sorted(best, reverse=True)
    top_abs, top_sym, top_lag, top_r, top_n = best_sorted[0]  # type: ignore[misc]

    SIGNAL_THRESHOLD = 0.12
    if top_abs < SIGNAL_THRESHOLD:
        print(f"WEAK / NO SIGNAL — best |r| = {top_abs:.4f} ({top_sym}, lag={top_lag}d, n={top_n})")
        print("Threshold for strategy authorship: |r| ≥ 0.12")
        print("Next step: extend data coverage or add cross-asset breakdown.")
    else:
        print(f"SIGNAL FOUND — best corr r={top_r:+.4f} ({top_sym}, lag={top_lag}d, n={top_n})")
        print(f"Authoring StrategySpec … (see output above)")
        print()
        # Print StrategySpec snippet
        direction = "gt" if top_r > 0 else "lt"
        print(f"""
Recommended StrategySpec (to be authored via /create-strategy):

  name    : polymarket_momentum_lead
  thesis  : Prediction-market aggregate momentum (pm_prob_velocity) leads {top_sym}
            daily returns by ~{top_lag} day(s).  When macro Polymarket odds shift
            upward rapidly, crypto tends to follow.
  universe: [{top_sym[:6]}]       (spot only)
  signal  : pm_prob_velocity  →  lag {top_lag}d  →  r={top_r:+.4f}  n={top_n}

  entry   : pm_prob_velocity {direction} 0.005   (velocity > +0.5pp per day)
  exit    : hold {top_lag}d OR stop-loss -3%
  risk    : position_size=0.04 of equity  (4% per trade)

  gate requirements:
    - OOS Sharpe ≥ 0.6
    - ≥ 30 trades
    - deflated_sharpe ≥ 0.4
""")


if __name__ == "__main__":
    main()
