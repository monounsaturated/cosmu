# The Polymarket CLOB ExecutionAdapter (cosmu/adapters/exec/polymarket.py): submit/cancel/positions/fills,
# idempotent on client_order_id, LIMIT-only orders priced in (0,1), TESTNET-default never-auto-live interlock,
# disabled (paper) without keys. Tested fully offline against a MOCK CLOB client — no chain, no network.

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import pytest

from cosmu.adapters.exec.polymarket import (
    PolymarketExecutionAdapter,
    parse_fills,
    parse_positions,
    resolve_mode,
)
from cosmu.config.settings import LiveSettings, Settings
from cosmu.core.interfaces import AssetClass, Order, OrderId


class _MockClob:
    """Records posts/cancels and serves canned trades/positions — the adapter's PolyClobClient seam."""

    def __init__(self, *, trades: list[dict] | None = None, positions: list[dict] | None = None) -> None:
        self.posted: list[dict[str, Any]] = []
        self.canceled: list[str] = []
        self._trades = trades or []
        self._positions = positions or []
        self._by_client_id: dict[str, dict] = {}

    def post_order(self, *, token_id, price, size, side, post_only, client_order_id) -> dict[str, Any]:
        out = {"orderID": f"V-{len(self.posted)}", "client_order_id": client_order_id,
               "token_id": token_id, "price": price, "size": size, "side": side, "post_only": post_only}
        self.posted.append(out)
        self._by_client_id[client_order_id] = out
        return out

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        self.canceled.append(order_id)
        return {"canceled": order_id}

    def find_order(self, client_order_id: str) -> dict[str, Any] | None:
        return self._by_client_id.get(client_order_id)

    def get_trades(self, since_ms):
        return self._trades

    def get_positions(self):
        return self._positions


def _order(**kw) -> Order:
    base = dict(
        instrument_id="PM-FED-CUT-2026", side=1, qty=Decimal("10"), order_type="limit",
        limit_price=Decimal("0.42"), client_order_id="coid-1", ts=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
    )
    base.update(kw)
    return Order(**base)  # type: ignore[arg-type]


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


# ---------- the real-money interlock (pure resolve_mode) ----------

def test_no_keys_is_disabled():
    assert resolve_mode(_settings()) == "disabled"
    adapter = PolymarketExecutionAdapter.from_settings(_settings())
    assert adapter.mode == "disabled" and adapter.active is False


def test_testnet_key_resolves_testnet_and_never_real():
    s = _settings(polymarket_testnet_private_key="0xtest", polymarket_private_key="0xreal",
                  live=LiveSettings(mode="real"))
    # Testnet key present → testnet, even with a real key AND mode=real (real money is never auto-picked).
    assert resolve_mode(s) == "testnet"


def test_real_key_honored_only_with_mode_real():
    assert resolve_mode(_settings(polymarket_private_key="0xreal")) == "disabled"  # default mode=testnet
    assert resolve_mode(_settings(polymarket_private_key="0xreal", live=LiveSettings(mode="real"))) == "live"


def test_adapter_identity():
    a = PolymarketExecutionAdapter(client=_MockClob(), mode="live")
    assert a.venue == "polymarket" and a.asset_class == AssetClass.PREDICTION and a.active is True


# ---------- disabled adapter never touches the network ----------

def test_disabled_adapter_paper_contract():
    a = PolymarketExecutionAdapter(client=None, mode="disabled")
    assert a.positions() == [] and a.fills(dt.datetime(2026, 1, 1, tzinfo=dt.UTC)) == []
    with pytest.raises(RuntimeError):
        a.submit(_order())
    with pytest.raises(RuntimeError):
        a.cancel(OrderId(venue="polymarket", client_order_id="x"))


# ---------- submit: validation, idempotency, order shaping ----------

def test_submit_posts_limit_order_and_returns_order_id():
    mock = _MockClob()
    a = PolymarketExecutionAdapter(client=mock, mode="live", token_resolver=lambda s: "TOKEN-YES")
    oid = a.submit(_order(side=1, qty=Decimal("25"), limit_price=Decimal("0.37"), order_type="maker"))
    assert len(mock.posted) == 1
    posted = mock.posted[0]
    assert posted["token_id"] == "TOKEN-YES" and posted["side"] == "BUY"
    assert posted["price"] == 0.37 and posted["size"] == 25.0 and posted["post_only"] is True
    assert oid.venue == "polymarket" and oid.client_order_id == "coid-1" and oid.venue_order_id == "V-0"


def test_submit_is_idempotent_on_client_order_id():
    mock = _MockClob()
    a = PolymarketExecutionAdapter(client=mock, mode="live", token_resolver=lambda s: "TOK")
    a.submit(_order(client_order_id="dup"))
    a.submit(_order(client_order_id="dup"))  # re-submit same id → no second post
    assert len(mock.posted) == 1


def test_submit_rejects_market_orders():
    a = PolymarketExecutionAdapter(client=_MockClob(), mode="live")
    with pytest.raises(ValueError, match="no market order"):
        a.submit(_order(order_type="market", limit_price=None))


def test_submit_rejects_price_outside_unit_interval():
    a = PolymarketExecutionAdapter(client=_MockClob(), mode="live")
    for bad in (Decimal("0"), Decimal("1"), Decimal("1.5"), Decimal("-0.1")):
        with pytest.raises(ValueError, match="probability"):
            a.submit(_order(limit_price=bad))


def test_submit_requires_limit_price():
    a = PolymarketExecutionAdapter(client=_MockClob(), mode="live")
    with pytest.raises(ValueError, match="limit_price"):
        a.submit(_order(order_type="limit", limit_price=None))


def test_token_resolver_falls_back_only_to_a_real_token_id():
    """A resolver miss falls back to the symbol verbatim ONLY when it already looks like a CLOB token id
    (numeric or 0x-hex) — never a human label, which would route the order to the wrong/invalid market."""
    mock = _MockClob()
    a = PolymarketExecutionAdapter(client=mock, mode="live", token_resolver=lambda s: None)
    a.submit(_order(instrument_id="71321045679252212594626385532706912750332728571942532289631379312455583992563"))
    assert mock.posted[0]["token_id"].startswith("713210")  # numeric token id → used verbatim
    a.submit(_order(instrument_id="0xRAWTOKEN0123456789", client_order_id="c2"))
    assert mock.posted[1]["token_id"] == "0xRAWTOKEN0123456789"  # 0x-hex token → used verbatim


def test_submit_refuses_unresolvable_human_label():
    """A resolver outage on a human market label MUST refuse (raise → audited skip), never submit the label as
    a garbage token that could match an unintended market with real money."""
    a = PolymarketExecutionAdapter(client=_MockClob(), mode="live", token_resolver=lambda s: None)
    with pytest.raises(ValueError, match="could not resolve"):
        a.submit(_order(instrument_id="PM-FED-CUT-2026"))


def test_proxy_signature_type_requires_funder():
    """A proxy signature type (1/2) trades a proxy wallet that is NOT the signer — without its funder address
    the adapter must stay disabled rather than sign for the wrong account."""
    s = _settings(polymarket_testnet_private_key="0xt", polymarket_signature_type=2)  # no funder
    assert PolymarketExecutionAdapter.from_settings(s).active is False


def test_sell_side_maps_to_clob_sell():
    mock = _MockClob()
    a = PolymarketExecutionAdapter(client=mock, mode="live", token_resolver=lambda s: "TOK")
    a.submit(_order(side=-1))
    assert mock.posted[0]["side"] == "SELL"


# ---------- cancel / positions / fills ----------

def test_cancel_uses_venue_order_id():
    mock = _MockClob()
    a = PolymarketExecutionAdapter(client=mock, mode="live")
    a.cancel(OrderId(venue="polymarket", client_order_id="c", venue_order_id="V-9"))
    assert mock.canceled == ["V-9"]


def test_fills_parsed_with_zero_fee_in_usdc():
    trades = [
        {"order_id": "V-1", "symbol": "PM-FED-CUT-2026", "side": "BUY", "size": "10", "price": "0.40",
         "fee": "0", "is_maker": True, "match_time": "1768000000"},
        {"taker_order_id": "V-2", "asset_id": "TOKEN", "side": "SELL", "size": "5", "price": "0.55",
         "match_time": "1768000600"},
    ]
    fills = parse_fills(trades)
    assert len(fills) == 2
    assert fills[0].side == 1 and fills[0].qty == Decimal("10") and fills[0].price == Decimal("0.40")
    assert fills[0].fee == Decimal("0") and fills[0].fee_ccy == "USDC" and fills[0].is_maker is True
    assert fills[1].side == -1 and fills[1].is_maker is False
    assert fills[0].ts.tzinfo is not None


def test_positions_parsed_signed_with_avg_price():
    rows = [
        {"symbol": "PM-FED-CUT-2026", "size": "30", "avgPrice": "0.41"},
        {"market": "PM-ZERO", "size": "0", "avgPrice": "0.5"},  # flat → dropped
    ]
    positions = parse_positions(rows)
    assert len(positions) == 1
    assert positions[0].instrument_id == "PM-FED-CUT-2026"
    assert positions[0].qty == Decimal("30") and positions[0].avg_price == Decimal("0.41")
    assert positions[0].liquidation_price is None  # prediction markets have no leverage/liquidation


def test_fills_uses_get_trades_via_active_client():
    mock = _MockClob(trades=[{"order_id": "V", "symbol": "PM", "side": "BUY", "size": "1", "price": "0.5"}])
    a = PolymarketExecutionAdapter(client=mock, mode="testnet")
    out = a.fills(dt.datetime(2026, 1, 1, tzinfo=dt.UTC))
    assert len(out) == 1 and out[0].fee_ccy == "USDC"


def test_clob_wrapper_annotates_client_id_and_filters_since(monkeypatch):
    """The real wrapper backfills client_order_id onto data-api trades (which lack it) from the post-order
    cache so reconcile_fills can match them, and honors the since_ms lookback (the data-api ignores it)."""
    pytest.importorskip("py_clob_client")  # the wrapper imports the optional lib at module top
    import cosmu.adapters.exec._polymarket_clob as clob

    canned = [
        {"taker_order_id": "VEN-9", "side": "BUY", "size": "10", "price": "0.40", "match_time": "1768000000"},
        {"order_id": "OLD", "side": "SELL", "size": "5", "price": "0.60", "match_time": "1700000000"},  # too old
    ]
    monkeypatch.setattr(clob, "_data_api_get", lambda path, query: [dict(t) for t in canned])
    w = clob._ClobClientWrapper(client=object(), funder_address="0xfunder")
    w._by_client_id["coid-1"] = {"orderID": "VEN-9"}  # an order placed this process

    out = w.get_trades(since_ms=1_750_000_000_000)  # after the OLD trade, before VEN-9
    assert len(out) == 1  # the stale trade is filtered out
    assert out[0]["client_order_id"] == "coid-1"  # backfilled so reconcile_fills can match it
