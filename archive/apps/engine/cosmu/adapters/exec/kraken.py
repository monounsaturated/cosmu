# intent: the Kraken spot ExecutionAdapter (core.ExecutionAdapter) via ccxt — submit/cancel/positions/fills,
# idempotent on client_order_id; inputs: settings-resolved keys + core.Order; outputs: core OrderId/Fill/Position;
# invariants: DISABLED is the default — real money ONLY with KRAKEN_API_KEY/SECRET + live.mode=="real". Kraken
# spot has NO public sandbox/testnet, so the modes are just disabled|live (unlike Binance's testnet default); no
# keys -> a disabled/paper state that never touches the network, secrets are NEVER stored on the instance nor
# returned, and the parse layer is pure so it is unit-testable against a MOCK ccxt client (no network).
#
# JURISDICTION: Kraken spot is US-legal (Payward Inc) and FR/EU-legal via Payward Europe Ltd (MiCA). ESMA
# restricts crypto DERIVATIVES for EU retail (that is the kraken_futures venue, which stays live_enabled=False),
# but SPOT trading is permitted. The operator validated adding Kraken; even so, the keys + live.mode interlock
# below means nothing arms real money without an explicit KRAKEN_API_KEY/SECRET + live.mode=="real" + the toggle.

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal, Protocol

from cosmu.config.settings import Settings
from cosmu.core.interfaces import AssetClass, Fill, Order, OrderId, Position


class CcxtClient(Protocol):
    """The slice of the ccxt exchange surface this adapter uses — lets tests inject a mock (no network)."""

    def create_order(self, symbol: str, type: str, side: str, amount: float, price: float | None, params: dict[str, Any]) -> dict[str, Any]: ...  # noqa: A002
    def cancel_order(self, id: str, symbol: str | None = None, params: dict[str, Any] | None = None) -> dict[str, Any]: ...  # noqa: A002
    def fetch_balance(self, params: dict[str, Any] | None = None) -> dict[str, Any]: ...
    def fetch_my_trades(self, symbol: str | None = None, since: int | None = None, limit: int | None = None, params: dict[str, Any] | None = None) -> list[dict[str, Any]]: ...
    def fetch_order(self, id: str, symbol: str | None = None, params: dict[str, Any] | None = None) -> dict[str, Any]: ...  # noqa: A002


VENUE = "kraken"
# Kraken spot has no public sandbox; there is no "testnet" mode (cf. Binance). Disabled until keys + mode=="real".
Mode = Literal["disabled", "live"]


def to_ccxt_symbol(symbol: str) -> str:
    """BTCUSDT/BTC/USD -> ccxt unified BTC/USD. Kraken's deepest spot books are USD, so a USDT pair maps to the
    USD book (mirrors market._kraken_pair); already-unified symbols pass through (XBT normalized back to BTC)."""
    if "/" in symbol:
        base, _, quote = symbol.partition("/")
        base = "BTC" if base.upper() == "XBT" else base
        return f"{base}/{quote}"
    s = symbol.upper()
    if s.endswith("USDT"):
        return f"{s[:-4]}/USD"
    if s.endswith("USD"):
        return f"{s[:-3]}/USD"
    return symbol


def _ccxt_side(side: int) -> str:
    return "buy" if side > 0 else "sell"


def _ccxt_type(order_type: str) -> str:
    # "maker" is post-only limit; "limit"/"market" map straight through.
    return "limit" if order_type in ("maker", "limit") else "market"


def build_create_params(order: Order) -> dict[str, Any]:
    """The ccxt create_order params for an Order. clientOrderId is the idempotency key (a retried/replayed
    submit is reconciled against it, never double-filled); post-only is set for maker orders."""
    params: dict[str, Any] = {"clientOrderId": order.client_order_id}
    if order.order_type == "maker":
        params["postOnly"] = True
    return params


def parse_order_id(raw: dict[str, Any], order: Order) -> OrderId:
    """Map a ccxt order dict back to a core OrderId, preserving our client id (the idempotency anchor)."""
    venue_order_id = raw.get("id")
    client_id = raw.get("clientOrderId") or order.client_order_id
    return OrderId(venue=VENUE, client_order_id=str(client_id), venue_order_id=str(venue_order_id) if venue_order_id is not None else None)


def parse_fills(raw_trades: list[dict[str, Any]]) -> list[Fill]:
    """Map ccxt trade dicts to core Fills. Pure: feed it recorded fixtures to test reconciliation offline."""
    out: list[Fill] = []
    for t in raw_trades:
        side = 1 if str(t.get("side", "buy")).lower() == "buy" else -1
        fee_info = t.get("fee") or {}
        ts_ms = t.get("timestamp")
        ts = datetime.fromtimestamp(float(ts_ms) / 1000, tz=UTC) if ts_ms else datetime.now(tz=UTC)
        out.append(
            Fill(
                order_id=OrderId(venue=VENUE, client_order_id=str(t.get("order", "") or ""), venue_order_id=str(t.get("order")) if t.get("order") else None),
                instrument_id=str(t.get("symbol", "")),
                side=side,
                qty=Decimal(str(t.get("amount", "0"))),
                price=Decimal(str(t.get("price", "0"))),
                fee=Decimal(str(fee_info.get("cost", "0") or "0")),
                fee_ccy=str(fee_info.get("currency", "") or ""),
                is_maker=bool(t.get("takerOrMaker") == "maker"),
                ts=ts,
            )
        )
    return out


def parse_positions(balance: dict[str, Any]) -> list[Position]:
    """Spot has no derivative positions — synthesize holdings from non-zero asset balances. avg_price is left
    at 0 here (the venue does not return a cost basis for spot); master/portfolio.py carries the real basis.
    Kraken reports BTC as XBT; normalize so positions key off the same base symbol as the rest of the system."""
    out: list[Position] = []
    totals = balance.get("total", {}) if isinstance(balance, dict) else {}
    now = datetime.now(tz=UTC)
    for asset, amount in totals.items():
        try:
            qty = Decimal(str(amount))
        except Exception:  # noqa: BLE001
            continue
        if qty == 0 or asset in ("USD", "USDT", "ZUSD", "USDC"):
            continue
        base = "BTC" if asset in ("XBT", "XXBT") else asset
        out.append(Position(instrument_id=f"{base}USD", qty=qty, avg_price=Decimal("0"), ts=now))
    return out


def resolve_mode(settings: Settings) -> Mode:
    """The real-money interlock. Kraken spot has no public sandbox, so there is no testnet mode: real keys are
    honored ONLY when live.mode == 'real'. No keys (or mode != 'real') -> disabled (the paper-sim state)."""
    s = settings.live
    if s.mode == "real" and settings.kraken_api_key and settings.kraken_api_secret:
        return "live"
    return "disabled"


@dataclass(frozen=True)
class _Creds:
    """Held only inside the factory; never stored on the adapter instance (secrets stay out of __repr__)."""

    api_key: str
    api_secret: str


class KrakenSpotExecutionAdapter:
    """core.ExecutionAdapter for Kraken spot. Construct via .from_settings(...) (resolves keys + the live
    interlock) or inject a `client` directly (tests pass a mock — no network). With no client and no keys it is
    `disabled`: submit raises so a caller must paper-simulate instead. Secrets are never attributes, never
    logged, never returned."""

    venue = VENUE
    asset_class = AssetClass.CRYPTO

    def __init__(self, *, client: CcxtClient | None = None, mode: Mode = "disabled") -> None:
        self._client = client
        self.mode: Mode = mode

    @classmethod
    def from_settings(cls, settings: Settings) -> KrakenSpotExecutionAdapter:
        mode = resolve_mode(settings)
        if mode == "disabled":
            return cls(client=None, mode="disabled")  # no keys / not armed -> no network, paper state
        creds = _Creds(settings.kraken_api_key or "", settings.kraken_api_secret or "")
        client = cls._build_ccxt_client(creds)
        if client is None:
            return cls(client=None, mode="disabled")  # ccxt unavailable -> stay paper, never network
        return cls(client=client, mode=mode)

    @staticmethod
    def _build_ccxt_client(creds: _Creds) -> CcxtClient | None:
        try:
            import ccxt  # type: ignore[import-not-found]
        except ImportError:
            return None
        return ccxt.kraken({"apiKey": creds.api_key, "secret": creds.api_secret, "enableRateLimit": True})

    @property
    def active(self) -> bool:
        """True when a real client is wired (live). Disabled adapters must paper-simulate."""
        return self._client is not None and self.mode != "disabled"

    def submit(self, order: Order) -> OrderId:
        if not self.active:
            raise RuntimeError("kraken adapter disabled (no keys) — caller must paper-simulate")
        client = self._client
        assert client is not None
        symbol = to_ccxt_symbol(order.instrument_id)
        existing = self._find_existing(client, order.client_order_id, symbol)
        if existing is not None:  # idempotency: a re-submitted client_order_id is a no-op, never a double-fill
            return parse_order_id(existing, order)
        raw = client.create_order(
            symbol,
            _ccxt_type(order.order_type),
            _ccxt_side(order.side),
            float(order.qty),
            float(order.limit_price) if order.limit_price is not None else None,
            build_create_params(order),
        )
        return parse_order_id(raw, order)

    def _find_existing(self, client: CcxtClient, client_order_id: str, symbol: str) -> dict[str, Any] | None:
        try:
            existing = client.fetch_order(client_order_id, symbol, {"clientOrderId": client_order_id})
        except Exception:  # noqa: BLE001 - not-found is the common path; treat any lookup failure as "new order"
            return None
        return existing or None

    def cancel(self, order_id: OrderId) -> None:
        if not self.active:
            raise RuntimeError("kraken adapter disabled (no keys)")
        client = self._client
        assert client is not None
        ref = order_id.venue_order_id or order_id.client_order_id
        client.cancel_order(ref, None, {"clientOrderId": order_id.client_order_id})

    def positions(self) -> list[Position]:
        if not self.active:
            return []
        client = self._client
        assert client is not None
        return parse_positions(client.fetch_balance())

    def fills(self, since: datetime) -> list[Fill]:
        if not self.active:
            return []
        client = self._client
        assert client is not None
        since_ms = int(since.timestamp() * 1000)
        return parse_fills(client.fetch_my_trades(None, since_ms, None, None))
