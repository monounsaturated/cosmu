# Kraken spot execution adapter: disabled-by-default key resolution (NO testnet — Kraken spot has no public
# sandbox), no-keys disabled (no network), idempotent submit on client_order_id, parse layer against a MOCK ccxt
# client (XBT->BTC normalization, USDT->USD book), and secrets are never stored or returned.

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from cosmu.adapters.exec.kraken import (
    KrakenSpotExecutionAdapter,
    resolve_mode,
    to_ccxt_symbol,
)
from cosmu.config.settings import LiveSettings, Settings
from cosmu.core.interfaces import AssetClass, Order, OrderId


def _settings(**kw) -> Settings:
    """Settings with the Kraken keys explicitly cleared, so the active .env file can't leak keys into these
    key-resolution tests. Callers re-add only the keys the case is about."""
    base = dict(
        database_url="sqlite:///:memory:",
        kraken_api_key=None,
        kraken_api_secret=None,
    )
    base.update(kw)
    return Settings(_env_file=None, **base)


class MockCcxt:
    """A no-network stand-in for the ccxt kraken client. Records calls; fakes idempotent order lookup."""

    def __init__(self) -> None:
        self.created: list[dict] = []
        self.cancelled: list[str] = []
        self._orders_by_coid: dict[str, dict] = {}

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
        return {"total": {"XBT": "0.5", "ZUSD": "1000"}}

    def fetch_my_trades(self, symbol=None, since=None, limit=None, params=None):
        return [
            {"order": "venue-1", "symbol": "BTC/USD", "side": "buy", "amount": "0.5", "price": "65000",
             "fee": {"cost": "0.13", "currency": "USD"}, "takerOrMaker": "taker", "timestamp": 1_700_000_000_000}
        ]


def _order(coid="cosmu-abc") -> Order:
    return Order(instrument_id="BTCUSDT", side=1, qty=Decimal("0.01"), order_type="market", limit_price=None, client_order_id=coid, ts=datetime.now(tz=UTC))


def test_no_keys_constructs_disabled_no_network():
    adapter = KrakenSpotExecutionAdapter.from_settings(_settings(live=LiveSettings()))
    assert adapter.mode == "disabled"
    assert adapter.active is False
    assert adapter.positions() == []  # disabled -> never touches network
    assert adapter.fills(datetime.now(tz=UTC)) == []


def test_disabled_submit_raises_so_caller_paper_simulates():
    adapter = KrakenSpotExecutionAdapter(client=None, mode="disabled")
    try:
        adapter.submit(_order())
        raise AssertionError("disabled adapter must refuse to submit")
    except RuntimeError:
        pass


def test_real_keys_without_mode_real_stay_disabled():
    # Real keys present but mode != "real" -> never auto-trades real money (no Kraken spot testnet to fall to).
    s = _settings(kraken_api_key="rk", kraken_api_secret="rs", live=LiveSettings(mode="testnet"))
    assert resolve_mode(s) == "disabled"


def test_real_only_with_real_keys_and_explicit_mode():
    armed = _settings(kraken_api_key="rk", kraken_api_secret="rs", live=LiveSettings(mode="real"))
    assert resolve_mode(armed) == "live"
    half = _settings(kraken_api_key="rk", kraken_api_secret=None, live=LiveSettings(mode="real"))
    assert resolve_mode(half) == "disabled"  # one half of the key pair -> not armable


def test_adapter_identity():
    a = KrakenSpotExecutionAdapter(client=MockCcxt(), mode="live")
    assert a.venue == "kraken" and a.asset_class == AssetClass.CRYPTO and a.active is True


def test_submit_is_idempotent_on_client_order_id():
    mock = MockCcxt()
    adapter = KrakenSpotExecutionAdapter(client=mock, mode="live")
    oid1 = adapter.submit(_order("cosmu-dupe"))
    oid2 = adapter.submit(_order("cosmu-dupe"))  # replay -> must NOT create a second order
    assert isinstance(oid1, OrderId) and oid1.client_order_id == "cosmu-dupe"
    assert oid2.venue_order_id == oid1.venue_order_id
    assert len(mock.created) == 1


def test_cancel_uses_venue_order_id():
    mock = MockCcxt()
    adapter = KrakenSpotExecutionAdapter(client=mock, mode="live")
    adapter.cancel(OrderId(venue="kraken", client_order_id="c", venue_order_id="V-9"))
    assert mock.cancelled == ["V-9"]


def test_parse_fills_and_positions_offline():
    mock = MockCcxt()
    adapter = KrakenSpotExecutionAdapter(client=mock, mode="live")
    fills = adapter.fills(datetime.now(tz=UTC))
    assert len(fills) == 1 and fills[0].is_maker is False and fills[0].side == 1
    positions = adapter.positions()
    # XBT normalizes to BTC; USD-quoted; ZUSD cash is excluded.
    assert any(p.instrument_id == "BTCUSD" and p.qty == Decimal("0.5") for p in positions)
    assert not any(p.instrument_id.startswith("ZUSD") for p in positions)


def test_secrets_never_stored_or_in_repr():
    adapter = KrakenSpotExecutionAdapter(client=MockCcxt(), mode="live")
    blob = repr(adapter) + repr(vars(adapter))
    assert "SECRET" not in blob.upper().replace("ASSERT", "")
    # the adapter holds no api_key/secret attributes at all
    assert not any("secret" in k.lower() or "key" in k.lower() for k in vars(adapter))


def test_symbol_unification():
    assert to_ccxt_symbol("BTCUSDT") == "BTC/USD"  # USDT pair maps to Kraken's deeper USD book
    assert to_ccxt_symbol("BTCUSD") == "BTC/USD"
    assert to_ccxt_symbol("BTC/USD") == "BTC/USD"
    assert to_ccxt_symbol("XBT/USD") == "BTC/USD"  # Kraken's XBT normalizes back to BTC
