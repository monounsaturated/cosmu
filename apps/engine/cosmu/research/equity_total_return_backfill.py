# intent: backfill ADJUSTED-CLOSE (total-return) daily bars for the ETFs the Dual-Momentum (GEM) strategy ranks —
# EFA (intl equity), AGG (US agg bonds), BIL (1-3m T-bills), and the SPY/TLT/GLD already on disk — into the equities
# cache. The existing equities cache (`*_1d.json`, raw `close`) is PRICE-return only; for bonds and dividend payers
# the dividend stream IS most of the total return, so a momentum rank on raw price is biased. This writes a PARALLEL
# `*_tr.json` cache keyed on adjusted close (Yahoo `adjclose` = split+dividend adjusted) so total-return modules read
# the right series WITHOUT mutating the price-return cache other research modules (reversal/BAB) depend on.
#
# inputs: keyless Yahoo v8 chart API (certifi SSL context — macOS needs the certifi CA bundle for urllib over TLS).
# outputs: one `<SYM>_tr.json` per symbol = [{ts(ms), close(adjusted)}], ascending, NO synthetic/zero-fill (Yahoo gap
# days are skipped). idempotent: re-run overwrites with the latest full history. propose/measure-only — moves no money.

from __future__ import annotations

import json
import ssl
import sys
import urllib.parse
import urllib.request
from pathlib import Path

CACHE = Path("/Users/device/cosmu/.cosmu/market_data/equities")

# The GEM universe + benchmarks. EFA/AGG/BIL are the ones missing from the price-return cache; SPY/TLT/GLD/QQQ are
# present as price-return but we ALSO want their total-return series so the whole backtest is apples-to-apples.
GEM_SYMBOLS = ["SPY", "EFA", "AGG", "BIL", "TLT", "GLD", "QQQ"]


def _ssl_context() -> ssl.SSLContext:
    """certifi CA bundle — macOS system Python has no usable default CA store for urllib TLS (confirmed today)."""
    import certifi

    return ssl.create_default_context(cafile=certifi.where())


def fetch_total_return(symbol: str) -> list[dict[str, object]]:
    """Full daily adjusted-close history for `symbol` from Yahoo v8. Returns [{ts(ms), close(adjusted)}] ascending.
    Yahoo emits None on holiday gaps; those rows are skipped (never zero-filled — that would fabricate a price)."""
    query = urllib.parse.urlencode(
        {"range": "max", "interval": "1d", "events": "div,splits", "includeAdjustedClose": "true"}
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
    for sym in symbols or GEM_SYMBOLS:
        rows = fetch_total_return(sym)
        path = CACHE / f"{sym}_tr.json"
        path.write_text(json.dumps(rows, separators=(",", ":")))
        out[sym] = len(rows)
        print(f"  {sym:<5} {len(rows):>6} adjusted-close bars  ({rows[0]['ts']} -> {rows[-1]['ts']})")
    return out


def main(argv: list[str] | None = None) -> int:
    syms = argv if argv else GEM_SYMBOLS
    print(f"Backfilling TOTAL-RETURN (adjusted-close) daily bars for: {', '.join(syms)}")
    backfill(syms)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
