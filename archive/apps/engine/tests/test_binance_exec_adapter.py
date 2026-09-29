# Binance spot execution adapter: testnet-by-default key resolution, no-keys disabled (no network), idempotent
# submit on client_order_id, parse layer against a MOCK ccxt client, and secrets are never stored or returned.

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from cosmu.adapters.exec.binance import (
    BinanceSpotExecutionAdapter,
    resolve_mode,
    to_ccxt_symbol,
)
from cosmu.config.settings import LiveSettings, Settings
from cosmu.core.interfaces import Order, OrderId


def _settings(**kw) -> Settings:
    """Settings with ALL exchange keys explicitly cleared, so the active .env file can't leak keys into
    these key-resolution tests. Callers re-add only the keys the case is about."""
    base = dict(
        database_url="sqlite:///:memory:",
        binance_api_key=None,
        binance_api_secret=None,
        binance_testnet_api_key=None,
        binance_testnet_api_secret=None,
    )
    base.update(kw)
    return Settings(**base)


class MockCcxt:
    """A no-network stand-in for the ccxt binance client. Records calls; fakes idempotent order lookup."""

    def __init__(self) -> None:
        self.created: list[dict] = []
        self.cancelled: list[str] = []
        self.sandbox = False
        self._orders_by_coid: dict[str, dict] = {}

    def set_sandbox_mode(self, on: bool) -> None:
        self.sandbox = on

    def create_order(self, symbol, type, side, amount, price, params):  # noqa: A002
        coid = params["clientOrderId"]
        raw = {"id": f"venue-{len(self.created)+1}", "clientOrderId": coid, "symbol": symbol, "side": side, "amount": amount}
        self.created.append(raw)
        self._orders_by_coid[coid] = raw
        return raw

    def fetch_order(self, id, symbol=None, params=None):  # noqa: A002
        coid = (params or {}).get("clientOrderId", id)
        if coid in self._orders_by_coid:
            return self._orders_by_coid[coid]
        raise ValueError("order not found")

    def cancel_order(self, id, symbol=None, params=None):  # noqa: A002
        self.cancelled.append(id)
        return {"id": id}

    def fetch_balance(self, params=None):
        return {"total": {"BTC": "0.5", "USDT": "1000"}}

    def fetch_my_trades(self, symbol=None, since=None, limit=None, params=None):
        return [
            {"order": "venue-1", "symbol": "BTC/USDT", "side": "buy", "amount": "0.5", "price": "65000",
             "fee": {"cost": "0.03", "currency": "USDT"}, "takerOrMaker": "maker", "timestamp": 1_700_000_000_000}
        ]


def _order(coid="cosmu-abc") -> Order:
    return Order(instrument_id="BTCUSDT", side=1, qty=Decimal("0.01"), order_type="market", limit_price=None, client_order_id=coid, ts=datetime.now(tz=UTC))


def test_no_keys_constructs_disabled_no_network():
    settings = _settings(live=LiveSettings())
    adapter = BinanceSpotExecutionAdapter.from_settings(settings)
    assert adapter.mode == "disabled"
    assert adapter.active is False
    assert adapter.positions() == []  # disabled -> never touches network
    assert adapter.fills(datetime.now(tz=UTC)) == []


def test_disabled_submit_raises_so_caller_paper_simulates():
    adapter = BinanceSpotExecutionAdapter(client=None, mode="disabled")
    try:
        adapter.submit(_order())
        raise AssertionError("disabled adapter must refuse to submit")
    except RuntimeError:
        pass


def test_testnet_is_default_when_testnet_keys_present():
    settings = _settings(binance_testnet_api_key="tk", binance_testnet_api_secret="ts", binance_api_key="rk", binance_api_secret="rs", live=LiveSettings(mode="real"))
    # testnet keys present -> testnet wins even though real keys + mode=real are also set (never auto-real).
    assert resolve_mode(settings) == "testnet"


def test_real_only_with_real_keys_and_explicit_mode():
    no_mode = _settings(binance_api_key="rk", binance_api_secret="rs", live=LiveSettings(mode="testnet"))
    assert resolve_mode(no_mode) == "disabled"  # real keys but mode not "real" -> never trades real
    armed = _settings(binance_api_key="rk", binance_api_secret="rs", live=LiveSettings(mode="real"))
    assert resolve_mode(armed) == "live"


def test_submit_is_idempotent_on_client_order_id():
    mock = MockCcxt()
    adapter = BinanceSpotExecutionAdapter(client=mock, mode="testnet")
    oid1 = adapter.submit(_order("cosmu-dupe"))
    oid2 = adapter.submit(_order("cosmu-dupe"))  # replay -> must NOT create a second order
    assert isinstance(oid1, OrderId) and oid1.client_order_id == "cosmu-dupe"
    assert oid2.venue_order_id == oid1.venue_order_id
    assert len(mock.created) == 1


def test_parse_fills_and_positions_offline():
    mock = MockCcxt()
    adapter = BinanceSpotExecutionAdapter(client=mock, mode="testnet")
    fills = adapter.fills(datetime.now(tz=UTC))
    assert len(fills) == 1 and fills[0].is_maker and fills[0].side == 1
    positions = adapter.positions()
    assert any(p.instrument_id == "BTCUSDT" and p.qty == Decimal("0.5") for p in positions)


def test_secrets_never_stored_or_in_repr():
    settings = Settings(database_url="sqlite:///:memory:", binance_testnet_api_key="SECRET_KEY", binance_testnet_api_secret="SECRET_VAL")
    mock = MockCcxt()
    adapter = BinanceSpotExecutionAdapter(client=mock, mode="testnet")
    blob = repr(adapter) + repr(vars(adapter))
    assert "SECRET_KEY" not in blob and "SECRET_VAL" not in blob
    # the adapter holds no api_key/secret attributes at all
    assert not any("secret" in k.lower() or "key" in k.lower() for k in vars(adapter))


def test_symbol_unification():
    assert to_ccxt_symbol("BTCUSDT") == "BTC/USDT"
    assert to_ccxt_symbol("ETH/USDT") == "ETH/USDT"
