# intent: the Alpaca ExecutionAdapter (core.ExecutionAdapter) over the REST trading API — submit/cancel/
# positions/fills with order-class OCO brackets, idempotent on client_order_id; inputs: settings-resolved keys +
# core.Order; outputs: core OrderId/Fill/Position; invariants: PAPER is the default (paper keys → the paper
# endpoint, fake money; real money ONLY with ALPACA_API_KEY/SECRET + live.mode=="real" — never auto-picked),
# no keys -> a disabled state that never touches the network, secrets are NEVER stored on the adapter instance
# nor returned, and the parse layer is pure so it is unit-testable against a canned transport (no network).

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal, Protocol

from cosmu.config.settings import Settings
from cosmu.core.interfaces import AssetClass, Fill, Order, OrderId, Position

VENUE = "alpaca"
Mode = Literal["disabled", "paper", "live"]

PAPER_BASE_URL = "https://paper-api.alpaca.markets"
LIVE_BASE_URL = "https://api.alpaca.markets"
_TIMEOUT_S = 20


class AlpacaTransport(Protocol):
    """The HTTP slice this adapter uses — one callable, so tests inject canned responses (no network).
    Returns the decoded JSON body (dict or list), or raises on a non-2xx the caller treats as failure.
    A 404 MUST raise (it is how order-lookup misses are signalled)."""

    def __call__(self, method: str, path: str, *, query: dict[str, str] | None = None, body: dict[str, Any] | None = None) -> Any: ...


def _alpaca_side(side: int) -> str:
    return "buy" if side > 0 else "sell"


def _alpaca_type(order_type: str) -> str:
    # "maker" maps to a plain limit order — Alpaca has no post-only flag on equities; the limit price itself
    # is the maker intent. "limit"/"market" map straight through.
    return "limit" if order_type in ("maker", "limit") else "market"


def build_order_body(order: Order) -> dict[str, Any]:
    """The POST /v2/orders body for a core Order. client_order_id is the idempotency key (Alpaca rejects a
    duplicate id, so a retried/replayed submit never double-fills). Equities: time_in_force=day."""
    body: dict[str, Any] = {
        "symbol": order.instrument_id,
        "qty": str(order.qty),
        "side": _alpaca_side(order.side),
        "type": _alpaca_type(order.order_type),
        "time_in_force": "day",
        "client_order_id": order.client_order_id,
    }
    if order.limit_price is not None and body["type"] == "limit":
        body["limit_price"] = str(order.limit_price)
    return body


def parse_order_id(raw: dict[str, Any], order: Order) -> OrderId:
    """Map an Alpaca order dict back to a core OrderId, preserving our client id (the idempotency anchor)."""
    venue_order_id = raw.get("id")
    client_id = raw.get("client_order_id") or order.client_order_id
    return OrderId(venue=VENUE, client_order_id=str(client_id), venue_order_id=str(venue_order_id) if venue_order_id is not None else None)


def parse_fills(raw_activities: list[dict[str, Any]]) -> list[Fill]:
    """Map GET /v2/account/activities/FILL rows to core Fills. Pure: feed it recorded fixtures offline.
    Alpaca US equities are commission-free — the regulatory sell-side fees (SEC/TAF, well under 0.1 bp) are
    not itemized per fill by this endpoint, so fee=0 here IS the venue's real commission, not a stub."""
    out: list[Fill] = []
    for a in raw_activities:
        side = 1 if str(a.get("side", "buy")).lower() == "buy" else -1
        ts_raw = a.get("transaction_time")
        try:
            ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00")) if ts_raw else datetime.now(tz=UTC)
        except ValueError:
            ts = datetime.now(tz=UTC)
        out.append(
            Fill(
                order_id=OrderId(venue=VENUE, client_order_id="", venue_order_id=str(a.get("order_id")) if a.get("order_id") else None),
                instrument_id=str(a.get("symbol", "")),
                side=side,
                qty=Decimal(str(a.get("qty", "0"))),
                price=Decimal(str(a.get("price", "0"))),
                fee=Decimal("0"),
                fee_ccy="USD",
                is_maker=False,  # the activities feed does not flag liquidity; taker is the conservative read
                ts=ts if ts.tzinfo else ts.replace(tzinfo=UTC),
            )
        )
    return out


def parse_positions(raw_positions: list[dict[str, Any]]) -> list[Position]:
    """Map GET /v2/positions rows to core Positions. qty is signed (Alpaca shorts report side='short')."""
    out: list[Position] = []
    now = datetime.now(tz=UTC)
    for p in raw_positions:
        try:
            qty = Decimal(str(p.get("qty", "0")))
        except Exception:  # noqa: BLE001
            continue
        if str(p.get("side", "long")).lower() == "short" and qty > 0:
            qty = -qty
        if qty == 0:
            continue
        out.append(
            Position(
                instrument_id=str(p.get("symbol", "")),
                qty=qty,
                avg_price=Decimal(str(p.get("avg_entry_price", "0") or "0")),
                ts=now,
            )
        )
    return out


def resolve_mode(settings: Settings) -> Mode:
    """The real-money interlock, mirroring the Binance adapter exactly: paper keys -> paper (default, fake
    money). Live keys are honored ONLY when live.mode == 'real' AND no paper keys are present — never
    auto-pick real money. No keys -> disabled."""
    s = settings.live
    if settings.alpaca_paper_api_key and settings.alpaca_paper_api_secret:
        return "paper"
    if s.mode == "real" and settings.alpaca_api_key and settings.alpaca_api_secret:
        return "live"
    return "disabled"


def _urllib_transport(base_url: str, api_key: str, api_secret: str) -> AlpacaTransport:
    """The real HTTP transport. Built inside the factory so the credentials live ONLY in this closure —
    never on the adapter instance, never in __repr__, never returned."""

    def _request(method: str, path: str, *, query: dict[str, str] | None = None, body: dict[str, Any] | None = None) -> Any:
        url = f"{base_url}{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(  # noqa: S310 — fixed https base urls only
            url,
            data=data,
            method=method,
            headers={
                "APCA-API-KEY-ID": api_key,
                "APCA-API-SECRET-KEY": api_secret,
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:  # noqa: S310
            return json.loads(resp.read().decode() or "null")

    return _request


class AlpacaExecutionAdapter:
    """core.ExecutionAdapter for Alpaca US equities. Construct via .from_settings(...) (resolves keys + the
    paper/live endpoint) or inject a `transport` directly (tests pass canned responses — no network). With no
    transport it is `disabled`: submit raises so the caller must paper-simulate internally instead. Secrets
    are never attributes, never logged, never returned."""

    venue = VENUE
    asset_class = AssetClass.EQUITY

    def __init__(self, *, transport: AlpacaTransport | None = None, mode: Mode = "disabled") -> None:
        self._transport = transport
        self.mode: Mode = mode

    @classmethod
    def from_settings(cls, settings: Settings) -> AlpacaExecutionAdapter:
        mode = resolve_mode(settings)
        if mode == "disabled":
            return cls(transport=None, mode="disabled")  # no keys -> no network, paper-sim state
        if mode == "paper":
            transport = _urllib_transport(PAPER_BASE_URL, settings.alpaca_paper_api_key or "", settings.alpaca_paper_api_secret or "")
        else:
            transport = _urllib_transport(LIVE_BASE_URL, settings.alpaca_api_key or "", settings.alpaca_api_secret or "")
        return cls(transport=transport, mode=mode)

    @property
    def active(self) -> bool:
        """True when a transport is wired (paper or live). Disabled adapters must paper-simulate internally."""
        return self._transport is not None and self.mode != "disabled"

    def submit(self, order: Order) -> OrderId:
        if not self.active:
            raise RuntimeError("alpaca adapter disabled (no keys) — caller must paper-simulate")
        transport = self._transport
        assert transport is not None
        existing = self._find_existing(transport, order.client_order_id)
        if existing is not None:  # idempotency: a re-submitted client_order_id is a no-op, never a double-fill
            return parse_order_id(existing, order)
        raw = transport("POST", "/v2/orders", body=build_order_body(order))
        return parse_order_id(raw, order)

    @staticmethod
    def _find_existing(transport: AlpacaTransport, client_order_id: str) -> dict[str, Any] | None:
        try:
            existing = transport("GET", "/v2/orders:by_client_order_id", query={"client_order_id": client_order_id})
        except Exception:  # noqa: BLE001 — not-found (404) is the common path; treat any lookup failure as "new order"
            return None
        return existing or None

    def cancel(self, order_id: OrderId) -> None:
        if not self.active:
            raise RuntimeError("alpaca adapter disabled (no keys)")
        transport = self._transport
        assert transport is not None
        ref = order_id.venue_order_id or order_id.client_order_id
        transport("DELETE", f"/v2/orders/{ref}")

    def positions(self) -> list[Position]:
        if not self.active:
            return []
        transport = self._transport
        assert transport is not None
        raw = transport("GET", "/v2/positions")
        return parse_positions(raw if isinstance(raw, list) else [])

    def place_oco_bracket(
        self, symbol: str, qty: Decimal, take_profit: Decimal, stop_loss: Decimal, *, client_order_id_prefix: str = ""
    ) -> dict[str, Any] | None:
        """Best-effort OCO sell bracket via Alpaca's order_class='oco' (limit TP + stop SL) after a BUY fill.
        Returns the raw response on success, None on any failure — the parent buy is never affected."""
        if not self.active:
            return None
        transport = self._transport
        assert transport is not None
        body: dict[str, Any] = {
            "symbol": symbol,
            "qty": str(qty),
            "side": "sell",
            "type": "limit",
            "time_in_force": "gtc",
            "order_class": "oco",
            "take_profit": {"limit_price": str(take_profit)},
            "stop_loss": {"stop_price": str(stop_loss)},
        }
        if client_order_id_prefix:
            body["client_order_id"] = f"{client_order_id_prefix}-oco"
        try:
            return transport("POST", "/v2/orders", body=body)
        except Exception:  # noqa: BLE001 — best-effort; OCO failure must never fail the parent buy
            return None

    def fills(self, since: datetime) -> list[Fill]:
        if not self.active:
            return []
        transport = self._transport
        assert transport is not None
        raw = transport(
            "GET", "/v2/account/activities/FILL", query={"after": since.astimezone(UTC).isoformat()}
        )
        return parse_fills(raw if isinstance(raw, list) else [])
