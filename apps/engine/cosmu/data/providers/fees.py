from __future__ import annotations

from datetime import datetime
from typing import Any

from ._types import AltDataPoint
from .store import PgAltDataStore


def read_pit_fee(
    store: Any,  # AltDataStore | PgAltDataStore — must have read_asof; Store (DB) is handled below
    venue_id: str,
    symbol: str,
    metric: str,  # "venue_fees_maker" | "venue_fees_taker"
    as_of: datetime,
    *,
    fallback_bps: float | None = None,
) -> float | None:
    """Read the latest PIT fee (bps) for a venue × symbol as of `as_of`.

    The store key is ``(provider="venue_fees", symbol=<venue_id>:<symbol>, metric=<metric>)``.
    If no row exists and `fallback_bps` is given, returns that.  Otherwise None.

    Accepts AltDataStore, PgAltDataStore, or the core Store (which wraps PgAltDataStore internally).
    The core Store does not have `read_asof` directly — it is wrapped transparently here so callers
    can pass whichever store they hold.

    This is the single read seam for gate.py / costopt.py / execution.py so every
    fee read is point-in-time, with NO look-ahead.
    """
    # If the caller holds a core Store (has .rows but not .read_asof), wrap it as PgAltDataStore.
    alt_store = store
    if not hasattr(store, "read_asof"):
        try:
            alt_store = PgAltDataStore(store)
        except Exception:  # noqa: BLE001
            return fallback_bps
    store_symbol = f"{venue_id}:{symbol}"
    try:
        points = alt_store.read_asof("venue_fees", store_symbol, metric, as_of)
    except Exception:  # noqa: BLE001 — never crash the order path over a fee read
        return fallback_bps
    if points:
        return points[-1].value
    return fallback_bps


class VenueFeesProvider:
    """Point-in-time venue fee snapshots via ccxt `fetchTradingFees`.

    Fetches *this account's* maker/taker schedule (already reflecting VIP tier,
    token discounts, and promos) for each symbol on a venue.  Requires an
    authenticated ccxt exchange instance; falls back down a three-rung ladder:

        1. `exchange.fetchTradingFees()` — account-specific (preferred)
        2. `exchange.describe()['fees']` — published brochure rates
        3. Static catalog values in `fallback_fees` — offline / no-key safe

    Stores two metrics per venue × symbol via `fetch_series`:
        - ``venue_fees_maker``  maker fee in bps (negative = rebate)
        - ``venue_fees_taker``  taker fee in bps

    The `available_at` timestamp equals the fetch timestamp — fees are a live
    read, not a publication-lagged series.  KEY-GATED: an absent / disabled ccxt
    client returns [] so the system degrades honestly (never fabricates a fee read).
    Offline-testable via the injected `_fetcher` callable.
    """

    # Per-venue static fallback fees (bps) used when ccxt is unavailable.
    _STATIC_FALLBACK: dict[str, tuple[float, float]] = {
        "binance": (10.0, 10.0),
        "binanceusdm": (2.0, 4.0),
        "okx": (8.0, 10.0),
        "kraken": (16.0, 26.0),
        "krakenfutures": (2.0, 5.0),
        "coinbasepro": (40.0, 60.0),
        "coinbase": (40.0, 60.0),
    }

    def __init__(
        self,
        exchange_id: str,
        ccxt_exchange=None,  # a live authenticated ccxt exchange instance or None
        fallback_fees: dict[str, tuple[float, float]] | None = None,
        *,
        _fetcher=None,  # injectable: fn(exchange) -> dict mapping symbol -> {maker, taker}
    ) -> None:
        self.exchange_id = exchange_id.lower()
        self._exchange = ccxt_exchange
        self._fallback = fallback_fees or dict(self._STATIC_FALLBACK)
        self._fetcher = _fetcher

    # ------------------------------------------------------------------
    # Public AltDataProvider seam
    # ------------------------------------------------------------------

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        """Fetch one fee metric for one symbol.  `metric` is one of
        ``venue_fees_maker`` or ``venue_fees_taker``.  Returns a list with a
        single point stamped now (the snapshot is a current read, not a history).
        Returns [] when metric is unknown or fees cannot be fetched."""
        if metric not in ("venue_fees_maker", "venue_fees_taker"):
            return []
        kind = "maker" if metric == "venue_fees_maker" else "taker"
        bps = self._fee_bps(symbol, kind)
        if bps is None:
            return []
        from datetime import UTC
        now = datetime.now(tz=UTC)
        return [AltDataPoint(ts=now, available_at=now, value=bps)]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fee_bps(self, symbol: str, kind: str) -> float | None:
        """Return the fee in basis points for this symbol and kind (maker/taker),
        walking the fallback ladder.  Returns None only when no info at all."""
        # Rung 1: injected fetcher (used by tests and live authenticated path)
        if self._fetcher is not None:
            fees = self._fetcher(self._exchange)
            if fees and symbol in fees:
                return float(fees[symbol].get(kind, fees[symbol].get("taker", 0))) * 10000.0
            # injected fetcher present but symbol missing → try describe/static
        elif self._exchange is not None:
            fees = self._ccxt_fetch_fees()
            if fees and symbol in fees:
                entry = fees[symbol]
                return float(entry.get(kind, entry.get("taker", 0))) * 10000.0
            # symbol not in response → fall through

        # Rung 2: ccxt exchange.describe()['fees']
        if self._exchange is not None:
            bps = self._describe_fee(kind)
            if bps is not None:
                return bps

        # Rung 3: static catalog
        pair = self._fallback.get(self.exchange_id)
        if pair is not None:
            return pair[0] if kind == "maker" else pair[1]

        return None  # no info available — caller returns []

    def _ccxt_fetch_fees(self) -> dict | None:
        """Call ccxt `fetchTradingFees`; return None on any failure (rate-limit, auth error, etc.)."""
        try:
            result = self._exchange.fetchTradingFees()
            return result if isinstance(result, dict) else None
        except Exception:  # noqa: BLE001 — one dead source never aborts the pass
            return None

    def _describe_fee(self, kind: str) -> float | None:
        """Extract a fee (bps) from ccxt's `describe()['fees']`.  Returns None if absent."""
        try:
            desc = self._exchange.describe()
            fees = (desc.get("fees") or {}).get("trading") or {}
            rate = fees.get(f"{kind}Fee") or fees.get("taker" if kind == "taker" else "maker")
            if rate is not None:
                return float(rate) * 10000.0
        except Exception:  # noqa: BLE001
            pass
        return None
