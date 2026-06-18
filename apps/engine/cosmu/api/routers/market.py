# intent: serve closed-candle OHLCV from a Binance-REACHABLE region (the always-on Railway EU engine) so a
# geo-blocked compute account (Modal US, where a live Binance fetch returns nothing) can pull bars at RUNTIME
# instead of bundling a per-deploy local cache. This is what keeps the Modal fleet modular + account-swappable:
# point COSMU_BARS_URL at this engine and any account deploys cacheless. Read-only; sits behind the SAME x-api-key
# gate as every route (cosmu/api/app.py). Returns the on-disk cache row shape (_bars_to_rows ⇄ _bar_from_json),
# so RemoteBarsProvider round-trips it byte-faithfully.

from __future__ import annotations

from fastapi import APIRouter

from cosmu.data.market import BinanceSpotOHLCVProvider, _bars_to_rows

router = APIRouter()

_MAX_LIMIT = 1500  # one Binance page; the screen never needs more daily history than this


@router.get("/market/bars")
def market_bars(symbol: str, timeframe: str = "1d", limit: int = 1000) -> dict[str, object]:
    """Closed-candle OHLCV for a Binance spot symbol, fetched in a Binance-reachable region. `bars` is a list of
    {ts(ms), open, high, low, close, volume} (OHLCV as strings → exact Decimals). Empty `bars` on any failure
    (offline / unknown symbol) — never a synthetic fill."""
    n = max(1, min(int(limit), _MAX_LIMIT))
    bars = BinanceSpotOHLCVProvider().fetch_bars(symbol, timeframe, limit=n)
    return {"symbol": symbol, "timeframe": timeframe, "bars": _bars_to_rows(bars)}
