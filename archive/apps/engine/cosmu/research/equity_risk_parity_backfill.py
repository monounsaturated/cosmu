# intent: backfill DAILY ADJUSTED-CLOSE (total-return) bars for the inverse-vol Risk-Parity sleeve {SPY, AGG, GLD}
# into a parallel `<SYM>_tr_daily.json` cache, so the strategy can estimate a TRUE 60-trading-day realized vol per
# asset (the monthly `*_tr.json` files only carry ~12 obs/yr — far too coarse for a 60d vol window). Adjusted close is
# split+dividend adjusted, so BOTH the vol estimate and the held-month return are on the same total-return basis.
#
# The keyless Yahoo v8 chart API silently downgrades `range=max` to MONTHLY granularity (confirmed: AGG range=max -> 274
# bars vs explicit period1/period2 -> 5708 bars). So we ALWAYS pass explicit period1/period2 to get daily bars, with a
# certifi SSL context (macOS system Python has no usable default CA store for urllib TLS).
#
# outputs: one `<SYM>_tr_daily.json` per symbol = [{ts(ms), close(adjusted)}], ascending, NO synthetic/zero-fill
# (Yahoo gap days are skipped). idempotent: re-run overwrites with the latest full history. moves no money.

from __future__ import annotations

import json
import ssl
import sys
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
import os

CACHE = Path(os.environ.get("COSMU_EQUITY_CACHE", "<repo>/.cosmu/market_data/equities"))
RISK_PARITY_SYMBOLS = ["SPY", "AGG", "GLD"]
# Start well before the youngest sleeve (GLD lists 2004-11) so the trailing-vol window is warm by the first rebalance.
PERIOD1 = int(datetime(2003, 1, 1, tzinfo=UTC).timestamp())


def _ssl_context() -> ssl.SSLContext:
    import certifi

    return ssl.create_default_context(cafile=certifi.where())


def fetch_daily_total_return(symbol: str) -> list[dict[str, object]]:
    """Full DAILY adjusted-close history for `symbol` from Yahoo v8 via explicit period1/period2 (range=max would
    downgrade to monthly). Returns [{ts(ms), close(adjusted)}] ascending; Yahoo gap days (None) are skipped."""
    period2 = int(datetime.now(tz=UTC).timestamp())
    query = urllib.parse.urlencode(
        {
            "period1": PERIOD1,
            "period2": period2,
            "interval": "1d",
            "events": "div,splits",
            "includeAdjustedClose": "true",
        }
    )
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?{query}"
    req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
    with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    result = payload["chart"]["result"][0]
    timestamps = result.get("timestamp") or []
    adj = result["indicators"]["adjclose"][0]["adjclose"]
    rows: list[dict[str, object]] = []
    for ts_s, a in zip(timestamps, adj, strict=True):
        if a is None:  # Yahoo gap day — no bar, never zero-fill
            continue
        rows.append({"ts": int(ts_s) * 1000, "close": str(a)})
    return rows


def backfill(symbols: list[str] | None = None) -> dict[str, int]:
    CACHE.mkdir(parents=True, exist_ok=True)
    out: dict[str, int] = {}
    for sym in symbols or RISK_PARITY_SYMBOLS:
        path = CACHE / f"{sym}_tr_daily.json"
        rows = fetch_daily_total_return(sym)
        path.write_text(json.dumps(rows, separators=(",", ":")))
        out[sym] = len(rows)
        a = datetime.fromtimestamp(rows[0]["ts"] / 1000, tz=UTC).date()
        b = datetime.fromtimestamp(rows[-1]["ts"] / 1000, tz=UTC).date()
        print(f"  {sym:<5} {len(rows):>6} daily adjusted-close bars  ({a} -> {b})")
    return out


def main(argv: list[str] | None = None) -> int:
    syms = argv if argv else RISK_PARITY_SYMBOLS
    print(f"Backfilling DAILY TOTAL-RETURN (adjusted-close) bars for: {', '.join(syms)}")
    backfill(syms)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
