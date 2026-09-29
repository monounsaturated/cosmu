# intent: keyless, point-in-time-honest client over Deribit's PUBLIC market-data API (no key, IP-rate-limited) —
# the $0 substrate for the options-inefficiency scanner. Wraps four public endpoints behind one small surface:
#   - get_index_price            → the underlying USD index (BTC/ETH/...) at poll time
#   - get_volatility_index_data  → DVOL (Deribit's 30d forward IV index — the crypto VIX), daily bars
#   - get_book_summary_by_currency (kind=option) → the WHOLE option chain in ONE call: per-instrument
#       top-of-book bid/ask price (in COIN), mark_iv, mark_price, open_interest, volume, underlying forward.
#       This is the cheap workhorse (one call covers ~870 BTC instruments incl. the long-tail strikes).
#   - get_order_book (per instrument) → full L2 (price,size) ladders + greeks + best bid/ask SIZES, for the
#       BOUNDED subset we actually want to fill-check (long-tail strikes — the sub-capacity lane).
# Same idioms as cosmu.data.providers.onchain.DeribitDvolProvider: stdlib urllib, certifi-backed _ssl_context,
# offline-injectable `_fetcher(url) -> dict`, one dead fetch degrades to {} (never aborts a poll). PIT: this
# client only READS; the capture timestamp is stamped by the caller (logger) at the instant of the poll.
# This module owns ONLY the HTTP transport + JSON-RPC envelope unwrap; parsing into typed quotes lives in chain.py.

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable

from cosmu.data.providers._types import _ssl_context

_BASE_URL = "https://www.deribit.com/api/v2"
# Deribit index names for the spot underlying (lower-case, `_usd` suffix). Options chains key off the currency.
_INDEX_NAME = {"BTC": "btc_usd", "ETH": "eth_usd", "SOL": "sol_usd", "XRP": "xrp_usd", "MATIC": "matic_usd"}


class DeribitClient:
    """Keyless reader over Deribit's public market-data API. No auth, no order placement — market data only.
    Offline-testable: inject `_fetcher(url) -> dict` to replay canned JSON without touching the network. Every
    method returns the unwrapped `result` payload; a transport/JSON failure degrades to {} or [] (a dead poll is
    a gap, never a fabricated quote) so one bad call never aborts a multi-instrument poll."""

    def __init__(
        self,
        base_url: str = _BASE_URL,
        *,
        timeout: float = 30.0,
        _fetcher: Callable[[str], dict] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._fetcher = _fetcher or self._http_get

    def _http_get(self, url: str) -> dict:
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        with urllib.request.urlopen(req, timeout=self.timeout, context=_ssl_context()) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _call(self, method: str, params: dict) -> object:
        """GET `public/<method>?<params>` and return the unwrapped `result`, or None on any failure."""
        url = f"{self.base_url}/public/{method}?{urllib.parse.urlencode(params)}"
        try:
            payload = self._fetcher(url)
        except Exception:  # noqa: BLE001 — any transport/parse failure degrades to a gap, never a fabricated quote
            return None
        if not isinstance(payload, dict):
            return None
        return payload.get("result")

    def index_price(self, currency: str) -> float | None:
        """The current underlying USD index for `currency` (e.g. BTC → btc_usd), or None if unavailable."""
        index_name = _INDEX_NAME.get(currency.upper())
        if index_name is None:
            return None
        res = self._call("get_index_price", {"index_name": index_name})
        if isinstance(res, dict):
            px = res.get("index_price")
            if isinstance(px, (int, float)) and px > 0:
                return float(px)
        return None

    def dvol(self, currency: str, *, start_ms: int, end_ms: int, resolution: int = 86400) -> list[list[float]]:
        """DVOL bars for `currency` as raw [ts_ms, open, high, low, close] rows (ascending). [] on failure."""
        res = self._call(
            "get_volatility_index_data",
            {
                "currency": currency.upper(),
                "start_timestamp": start_ms,
                "end_timestamp": end_ms,
                "resolution": str(resolution),
            },
        )
        if isinstance(res, dict):
            data = res.get("data")
            if isinstance(data, list):
                return [row for row in data if isinstance(row, (list, tuple))]
        return []

    def book_summary(self, currency: str) -> list[dict]:
        """The WHOLE option chain for `currency` in one call: a list of per-instrument summary dicts (top-of-book
        bid/ask price in COIN, mark_iv, mark_price, open_interest, volume, underlying_price/index). [] on failure.
        This is the cheap workhorse — one keyless call returns every listed strike incl. the long-tail."""
        res = self._call("get_book_summary_by_currency", {"currency": currency.upper(), "kind": "option"})
        if isinstance(res, list):
            return [row for row in res if isinstance(row, dict)]
        return []

    def order_book(self, instrument: str, *, depth: int = 5) -> dict:
        """Full L2 for one instrument: {bids, asks, greeks, best_bid_amount, best_ask_amount, mark_iv, ...}.
        `bids`/`asks` are ascending-priority [[price, size], ...] ladders (price in COIN, size in contracts).
        {} on failure — the caller treats a missing book as 'no enriched depth for this instrument'."""
        res = self._call("get_order_book", {"instrument_name": instrument, "depth": depth})
        return res if isinstance(res, dict) else {}
