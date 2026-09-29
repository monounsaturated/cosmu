# intent: the REAL Polymarket CLOB client wrapper over py-clob-client (EIP-712 order signing on Polygon) +
# the public Polymarket data-api for fills/positions — kept in its own module so the optional `py-clob-client`
# dependency is imported ONLY here. Absent lib -> this module fails to import -> PolymarketExecutionAdapter
# falls back to disabled/paper (the same honest-degradation path as the Binance missing-ccxt branch).
#
# inputs: signing creds resolved by the adapter's from_settings; outputs: a PolyClobClient-shaped object;
# invariants: the signing key lives only inside this closure-built client, never logged; network/chain calls
# happen ONLY through here so the adapter's parse layer stays pure and offline-testable against a mock.

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

# Imported at module top so a missing optional dependency raises ImportError on `from _polymarket_clob import
# build_clob_client`, which the adapter catches to stay disabled (never touches the chain without the lib).
from py_clob_client.client import ClobClient  # type: ignore[import-not-found]
from py_clob_client.clob_types import (  # type: ignore[import-not-found]
    ApiCreds,
    OrderArgs,
    OrderType,
)
from py_clob_client.order_builder.constants import BUY, SELL  # type: ignore[import-not-found]

_DATA_API = "https://data-api.polymarket.com"
_TIMEOUT_S = 20


def _data_api_get(path: str, query: dict[str, str]) -> list[dict[str, Any]]:
    """GET the public Polymarket data-api (user-keyed fills/positions). Returns [] on any failure — a read
    miss must never break reconciliation."""
    url = f"{_DATA_API}{path}?" + urllib.parse.urlencode(query)
    req = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})  # noqa: S310 — fixed https host
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:  # noqa: S310
            data = json.loads(resp.read().decode() or "[]")
    except Exception:  # noqa: BLE001 — offline/non-2xx: no data this read
        return []
    if isinstance(data, dict):
        data = data.get("data") or data.get("positions") or data.get("trades") or []
    return data if isinstance(data, list) else []


class _ClobClientWrapper:
    """Adapts py-clob-client + the data-api to the adapter's PolyClobClient protocol. Idempotency on
    client_order_id is held in a per-process cache populated on post_order (the CLOB has no native client-id
    index): it covers same-tick re-runs; across a restart the executions-ledger `_already_filled` guard remains
    the backstop for double-booking."""

    def __init__(self, *, client: ClobClient, funder_address: str) -> None:
        self._client = client
        self._funder = funder_address
        self._by_client_id: dict[str, dict[str, Any]] = {}

    def post_order(self, *, token_id: str, price: float, size: float, side: str, post_only: bool, client_order_id: str) -> dict[str, Any]:
        args = OrderArgs(price=price, size=size, side=BUY if side == "BUY" else SELL, token_id=token_id)
        signed = self._client.create_order(args)
        resp = self._client.post_order(signed, OrderType.GTC)
        out = dict(resp) if isinstance(resp, dict) else {"orderID": resp}
        out.setdefault("client_order_id", client_order_id)
        self._by_client_id[client_order_id] = out
        return out

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        return self._client.cancel(order_id)

    def find_order(self, client_order_id: str) -> dict[str, Any] | None:
        return self._by_client_id.get(client_order_id)

    def get_trades(self, since_ms: int | None) -> list[dict[str, Any]]:
        if not self._funder:
            return []
        trades = _data_api_get("/trades", {"user": self._funder})
        # The data-api carries no client_order_id (the CLOB has no native client-id index), yet reconcile_fills
        # matches on it. Annotate each trade from the venue-order-id -> client-order-id map built on post_order
        # (covers orders placed in THIS process; across a restart the executions-ledger guard is the backstop).
        # Also honor `since_ms` (the data-api ignores it) by filtering on the fill timestamp, mirroring the
        # Binance/Alpaca lookback so reconciliation doesn't re-scan all history.
        known = {
            str(r.get("orderID") or r.get("orderId") or r.get("id")): cid
            for cid, r in self._by_client_id.items()
        }
        out: list[dict[str, Any]] = []
        for t in trades:
            if since_ms is not None:
                raw_ts = t.get("match_time") or t.get("timestamp")
                try:
                    if raw_ts is not None and float(raw_ts) * 1000 < since_ms:
                        continue  # older than the lookback window
                except (TypeError, ValueError):
                    pass  # unparseable ts → keep it (reconcile matches by id, never double-books)
            cid = next(
                (known[str(t[k])] for k in ("order_id", "taker_order_id", "maker_order_id", "orderID")
                 if t.get(k) is not None and str(t[k]) in known),
                None,
            )
            out.append({**t, "client_order_id": cid} if cid is not None else t)
        return out

    def get_positions(self) -> list[dict[str, Any]]:
        if not self._funder:
            return []
        return _data_api_get("/positions", {"user": self._funder})


def build_clob_client(
    *,
    host: str,
    private_key: str,
    chain_id: int,
    api_key: str,
    api_secret: str,
    api_passphrase: str,
    funder_address: str,
    signature_type: int,
) -> _ClobClientWrapper:
    """Construct the signing CLOB client. Derives L2 API creds when not provided (py-clob-client's
    create_or_derive_api_creds). The funder address is the proxy wallet positions/fills are keyed to (defaults
    to the signer's own address when unset)."""
    client = ClobClient(
        host,
        key=private_key,
        chain_id=chain_id,
        signature_type=signature_type,
        funder=funder_address or None,
    )
    if api_key and api_secret and api_passphrase:
        client.set_api_creds(ApiCreds(api_key=api_key, api_secret=api_secret, api_passphrase=api_passphrase))
    else:
        client.set_api_creds(client.create_or_derive_api_creds())
    return _ClobClientWrapper(client=client, funder_address=funder_address or getattr(client, "get_address", lambda: "")())
