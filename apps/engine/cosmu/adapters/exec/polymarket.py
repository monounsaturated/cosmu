# intent: the Polymarket CLOB ExecutionAdapter (core.ExecutionAdapter) — submit/cancel/positions/fills,
# idempotent on client_order_id; inputs: settings-resolved signing creds + core.Order; outputs: core
# OrderId/Fill/Position; invariants: TESTNET (Amoy) is the default (real money ONLY with the mainnet signing
# key + live.mode=="real"), no keys -> a disabled state that never touches the chain/CLOB, the signing key is
# NEVER stored on the instance nor returned, CLOB orders are LIMIT-only and priced in (0,1) (a share is a
# probability), and the parse layer is pure so it is unit-testable against a MOCK CLOB client (no network).
#
# Polymarket is a binary-outcome prediction market: you buy/sell YES shares of a market token on a central
# limit order book settled in USDC on Polygon. There is NO per-trade maker/taker fee (the catalog's 0 bps is
# real); the binding cost is the order-book half-spread, which the sim lane already charges. Settlement is
# gasless for the operator (Polymarket's relayer pays Polygon gas against the funded proxy wallet), so there is
# no per-order gas line to model here. Signing uses py-clob-client (EIP-712 over the operator's Polygon key);
# it is imported lazily so the base install/tests never need it — absent lib OR absent keys -> disabled.

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal, Protocol

from cosmu.config.settings import Settings
from cosmu.core.interfaces import AssetClass, Fill, Order, OrderId, Position

VENUE = "polymarket"
Mode = Literal["disabled", "testnet", "live"]

# Polygon chain ids: mainnet (live) and Amoy testnet. The CLOB host differs by environment; testnet is opt-in
# and only reachable when POLYMARKET_TESTNET_PRIVATE_KEY is set (mirrors the Binance/Alpaca testnet-default).
MAINNET_CHAIN_ID = 137
TESTNET_CHAIN_ID = 80002
MAINNET_CLOB_HOST = "https://clob.polymarket.com"
TESTNET_CLOB_HOST = "https://clob-staging.polymarket.com"


class PolyClobClient(Protocol):
    """The slice of the Polymarket CLOB surface this adapter uses — lets tests inject a mock (no network/chain).
    A real implementation wraps py-clob-client (order signing + post) plus the Polymarket data-api reads for
    fills/positions. `find_order` MUST return None when the client_order_id is unknown (that is how the
    idempotency lookup signals "new order")."""

    def post_order(self, *, token_id: str, price: float, size: float, side: str, post_only: bool, client_order_id: str) -> dict[str, Any]: ...
    def cancel_order(self, order_id: str) -> dict[str, Any]: ...
    def find_order(self, client_order_id: str) -> dict[str, Any] | None: ...
    def get_trades(self, since_ms: int | None) -> list[dict[str, Any]]: ...
    def get_positions(self) -> list[dict[str, Any]]: ...


def _clob_side(side: int) -> str:
    return "BUY" if side > 0 else "SELL"


def parse_order_id(raw: dict[str, Any], order: Order) -> OrderId:
    """Map a CLOB post-order response back to a core OrderId, preserving our client id (the idempotency anchor).
    Polymarket returns the venue id under `orderID` (or `orderId`); a missing id leaves venue_order_id None."""
    venue_order_id = raw.get("orderID") or raw.get("orderId") or raw.get("id")
    client_id = raw.get("client_order_id") or order.client_order_id
    return OrderId(
        venue=VENUE,
        client_order_id=str(client_id),
        venue_order_id=str(venue_order_id) if venue_order_id is not None else None,
    )


def _parse_ts(raw: Any) -> datetime:
    """Polymarket stamps fills with a unix-seconds string (`match_time`) — fall back to an ISO string, else now."""
    if raw is None:
        return datetime.now(tz=UTC)
    try:
        return datetime.fromtimestamp(float(raw), tz=UTC)
    except (TypeError, ValueError):
        pass
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return ts if ts.tzinfo else ts.replace(tzinfo=UTC)
    except ValueError:
        return datetime.now(tz=UTC)


def parse_fills(raw_trades: list[dict[str, Any]]) -> list[Fill]:
    """Map Polymarket trade rows to core Fills. Pure: feed it recorded fixtures to test reconciliation offline.
    CLOB trading is fee-free (`fee=0` here IS the venue's real commission, not a stub); fee_ccy is USDC. The
    instrument id is the human market symbol when present, else the CLOB asset/token id."""
    out: list[Fill] = []
    for t in raw_trades:
        side = 1 if str(t.get("side", "BUY")).upper() == "BUY" else -1
        oid = t.get("order_id") or t.get("taker_order_id") or t.get("orderID")
        instrument = t.get("symbol") or t.get("market") or t.get("asset_id") or t.get("asset") or ""
        out.append(
            Fill(
                order_id=OrderId(
                    venue=VENUE,
                    client_order_id=str(t.get("client_order_id", "") or ""),
                    venue_order_id=str(oid) if oid is not None else None,
                ),
                instrument_id=str(instrument),
                side=side,
                qty=Decimal(str(t.get("size", "0") or "0")),
                price=Decimal(str(t.get("price", "0") or "0")),
                fee=Decimal(str(t.get("fee", "0") or "0")),
                fee_ccy="USDC",
                is_maker=bool(t.get("is_maker") or str(t.get("liquidity", "")).upper() == "MAKER"),
                ts=_parse_ts(t.get("match_time") or t.get("timestamp")),
            )
        )
    return out


def parse_positions(raw_positions: list[dict[str, Any]]) -> list[Position]:
    """Map Polymarket data-api `/positions` rows to core Positions. A prediction position is YES shares
    (qty > 0) at an average entry probability (avg_price in [0,1]); a NO bet is held as the opposite token, so
    qty stays >= 0 like spot. Liquidation does not apply (no leverage) so liquidation_price stays None."""
    out: list[Position] = []
    now = datetime.now(tz=UTC)
    for p in raw_positions:
        try:
            qty = Decimal(str(p.get("size", "0") or "0"))
        except Exception:  # noqa: BLE001
            continue
        if qty == 0:
            continue
        instrument = p.get("symbol") or p.get("market") or p.get("asset") or ""
        avg_raw = p.get("avgPrice", p.get("avg_price", "0"))
        try:
            avg = Decimal(str(avg_raw or "0"))
        except Exception:  # noqa: BLE001
            avg = Decimal("0")
        out.append(Position(instrument_id=str(instrument), qty=qty, avg_price=avg, ts=now))
    return out


def resolve_mode(settings: Settings) -> Mode:
    """The real-money interlock, mirroring Binance/Alpaca exactly: testnet signing key -> testnet (default,
    Amoy fake funds). The mainnet key is honored ONLY when live.mode == 'real' AND no testnet key is present —
    real money is never auto-picked. No signing key -> disabled."""
    if settings.polymarket_testnet_private_key:
        return "testnet"
    if settings.live.mode == "real" and settings.polymarket_private_key:
        return "live"
    return "disabled"


@dataclass(frozen=True)
class _Creds:
    """Held only inside the factory; never stored on the adapter instance (the signing key stays out of __repr__)."""

    private_key: str
    api_key: str
    api_secret: str
    api_passphrase: str
    funder_address: str
    signature_type: int
    chain_id: int
    host: str


class PolymarketExecutionAdapter:
    """core.ExecutionAdapter for the Polymarket CLOB. Construct via .from_settings(...) (resolves keys + the
    Amoy/mainnet endpoint) or inject a `client` directly (tests pass a mock — no network/chain). With no client
    and no keys it is `disabled`: submit raises so a caller must paper-simulate instead. The signing key is
    never an attribute, never logged, never returned.

    Orders are CLOB LIMIT orders (the venue has no market order); the price is the share probability and MUST be
    strictly inside (0, 1). `token_resolver` maps a core symbol (e.g. 'PM-FED-CUT-2026') to its CLOB token id;
    when it returns None the symbol is used verbatim (so a strategy may also address a market by raw token id)."""

    venue = VENUE
    asset_class = AssetClass.PREDICTION

    def __init__(
        self,
        *,
        client: PolyClobClient | None = None,
        mode: Mode = "disabled",
        token_resolver: Callable[[str], str | None] | None = None,
    ) -> None:
        self._client = client
        self.mode: Mode = mode
        self._token_resolver = token_resolver

    @classmethod
    def from_settings(cls, settings: Settings) -> PolymarketExecutionAdapter:
        mode = resolve_mode(settings)
        if mode == "disabled":
            return cls(client=None, mode="disabled")  # no keys -> no chain, paper state
        if mode == "testnet":
            creds = _Creds(
                private_key=settings.polymarket_testnet_private_key or "",
                api_key=settings.polymarket_testnet_api_key or "",
                api_secret=settings.polymarket_testnet_api_secret or "",
                api_passphrase=settings.polymarket_testnet_passphrase or "",
                funder_address=settings.polymarket_funder_address or "",
                signature_type=settings.polymarket_signature_type,
                chain_id=TESTNET_CHAIN_ID,
                host=TESTNET_CLOB_HOST,
            )
        else:
            creds = _Creds(
                private_key=settings.polymarket_private_key or "",
                api_key=settings.polymarket_api_key or "",
                api_secret=settings.polymarket_api_secret or "",
                api_passphrase=settings.polymarket_passphrase or "",
                funder_address=settings.polymarket_funder_address or "",
                signature_type=settings.polymarket_signature_type,
                chain_id=MAINNET_CHAIN_ID,
                host=MAINNET_CLOB_HOST,
            )
        # A PROXY signature type (1=email/magic, 2=browser proxy) trades from a proxy wallet that is NOT the
        # signer's EOA — positions/fills are keyed to that funder address. Without it the adapter would sign for
        # the wrong account and reconciliation (data-api ?user=) would read nothing. Refuse to arm rather than
        # trade the wrong wallet. signature_type 0 (EOA) funds from the signer itself, so no funder is required.
        if creds.signature_type != 0 and not creds.funder_address:
            return cls(client=None, mode="disabled")  # proxy signer with no funder -> disabled (never wrong-wallet)
        client = cls._build_clob_client(creds)
        if client is None:
            return cls(client=None, mode="disabled")  # py-clob-client unavailable -> stay paper, never network
        return cls(client=client, mode=mode, token_resolver=_gamma_token_resolver())

    @staticmethod
    def _build_clob_client(creds: _Creds) -> PolyClobClient | None:
        """Build the real CLOB client over py-clob-client. Returns None on ANY failure — the optional
        dependency missing, OR a malformed signing key / unreachable RPC at construction — so the adapter
        falls back to disabled/paper instead of crashing the resolve path (the same honest-degradation
        invariant as Binance's missing-ccxt branch; the money path must never raise here)."""
        try:
            from cosmu.adapters.exec._polymarket_clob import build_clob_client

            return build_clob_client(
                host=creds.host,
                private_key=creds.private_key,
                chain_id=creds.chain_id,
                api_key=creds.api_key,
                api_secret=creds.api_secret,
                api_passphrase=creds.api_passphrase,
                funder_address=creds.funder_address,
                signature_type=creds.signature_type,
            )
        except Exception:  # noqa: BLE001 — absent lib / bad key / offline RPC: stay paper, never crash
            return None

    @property
    def active(self) -> bool:
        """True when a real client is wired (testnet or live). Disabled adapters must paper-simulate."""
        return self._client is not None and self.mode != "disabled"

    @staticmethod
    def _looks_like_token(symbol: str) -> bool:
        """A CLOB token id is a long decimal (uint256) or 0x-hex string. A human market label (e.g.
        'PM-FED-CUT-2026') is NOT — submitting it verbatim as a token would hit an invalid/unintended market."""
        s = symbol.strip()
        return s.isdigit() or (s.lower().startswith("0x") and len(s) > 10)

    def _token_for(self, symbol: str) -> str:
        """Resolve a core symbol to its CLOB token id. Falls back to the symbol verbatim ONLY when it already
        looks like a raw token id; otherwise raises so the order is SKIPPED (audited) rather than placed against
        the wrong market — a resolver outage must never silently route real money to a garbage token."""
        if self._token_resolver is not None:
            resolved = self._token_resolver(symbol)
            if resolved:
                return resolved
        if self._looks_like_token(symbol):
            return symbol
        raise ValueError(f"could not resolve '{symbol}' to a CLOB token id — refusing to submit to an unknown market")

    def submit(self, order: Order) -> OrderId:
        if not self.active:
            raise RuntimeError("polymarket adapter disabled (no keys) — caller must paper-simulate")
        if order.order_type == "market":
            raise ValueError("polymarket CLOB has no market order — use 'limit' or 'maker'")
        if order.limit_price is None:
            raise ValueError("polymarket order requires a limit_price (the share probability)")
        price = float(order.limit_price)
        if not 0.0 < price < 1.0:
            raise ValueError(f"polymarket price must be a probability in (0, 1), got {price}")
        client = self._client
        assert client is not None
        existing = self._find_existing(client, order.client_order_id)
        if existing is not None:  # idempotency: a re-submitted client_order_id is a no-op, never a double-fill
            return parse_order_id(existing, order)
        raw = client.post_order(
            token_id=self._token_for(order.instrument_id),
            price=price,
            size=float(order.qty),
            side=_clob_side(order.side),
            post_only=order.order_type == "maker",
            client_order_id=order.client_order_id,
        )
        return parse_order_id(raw, order)

    @staticmethod
    def _find_existing(client: PolyClobClient, client_order_id: str) -> dict[str, Any] | None:
        try:
            return client.find_order(client_order_id) or None
        except Exception:  # noqa: BLE001 — not-found is the common path; treat any lookup failure as "new order"
            return None

    def cancel(self, order_id: OrderId) -> None:
        if not self.active:
            raise RuntimeError("polymarket adapter disabled (no keys)")
        client = self._client
        assert client is not None
        ref = order_id.venue_order_id or order_id.client_order_id
        client.cancel_order(ref)

    def positions(self) -> list[Position]:
        if not self.active:
            return []
        client = self._client
        assert client is not None
        return parse_positions(client.get_positions())

    def fills(self, since: datetime) -> list[Fill]:
        if not self.active:
            return []
        client = self._client
        assert client is not None
        since_ms = int(since.timestamp() * 1000)
        return parse_fills(client.get_trades(since_ms))


def _gamma_token_resolver() -> Callable[[str], str | None]:
    """A best-effort symbol -> CLOB token-id resolver backed by the public Gamma API, reusing the SAME
    discovery the data lane uses (cosmu.data.sources.polymarket). Gamma is the single canonical market catalog
    for both mainnet and testnet trading, so no host is threaded through. Cached per process. Returns None on
    any failure so submit() falls back to treating the symbol as a raw token id (never raises here)."""
    cache: dict[str, str | None] = {}

    def _resolve(symbol: str) -> str | None:
        if symbol in cache:
            return cache[symbol]
        token: str | None = None
        try:
            from cosmu.data.sources.polymarket import resolve_clob_token

            token = resolve_clob_token(symbol)
        except Exception:  # noqa: BLE001 — resolution is best-effort; the caller falls back to the raw symbol
            token = None
        cache[symbol] = token
        return token

    return _resolve
