# ASSET → TAPE resolution + routing (cosmu/authority/assets.py) — what makes STOCK / ETF / COMMODITY calls resolve
# instead of "no_data" (the V1 gap: only crypto was mapped). Pins:
#   * resolve_asset maps crypto / equity / commodity / index-alias / bare-ticker, and returns None for junk;
#   * crypto wins over the bare-ticker fallback (BTC never routes to a stock);
#   * build_tape ROUTES each asset to the right injected provider and keys the tape by the ORIGINAL asset string;
#   * an unmapped asset is OMITTED, and a provider that RAISES degrades to empty (offline-safe, never crashes);
#   * the crypto_symbol_override pins a symbol through the crypto provider.
# All offline — providers are fakes, no network.

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cosmu.authority.assets import build_tape, resolve_asset
from cosmu.authority.models import PricePoint

T0 = datetime(2024, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class _FakeBar:
    ts: datetime
    close: float


def _bars(n: int) -> list[_FakeBar]:
    return [_FakeBar(ts=T0 + timedelta(days=i), close=100.0 + i) for i in range(n)]


class _FakeProvider:
    """Records the symbols it was asked for and serves bars from a fixed table (empty for an unknown symbol)."""

    def __init__(self, table: dict[str, list[_FakeBar]] | None = None) -> None:
        self.table = table or {}
        self.calls: list[str] = []

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[_FakeBar]:
        self.calls.append(symbol)
        return self.table.get(symbol, [])


class _RaisingProvider:
    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list:
        raise RuntimeError("offline")


# --------------------------------------------------------------------------- resolve_asset


def test_resolve_maps_each_asset_class():
    btc = resolve_asset("BTC")
    assert btc is not None and btc.asset_class == "crypto" and btc.symbol == "BTCUSDT"
    aapl = resolve_asset("AAPL")
    assert aapl is not None and aapl.asset_class == "equity" and aapl.symbol == "AAPL"
    gold = resolve_asset("GOLD")
    assert gold is not None and gold.asset_class == "commodity" and gold.symbol == "GLD"  # ETF proxy
    spx = resolve_asset("SPX")
    assert spx is not None and spx.asset_class == "equity" and spx.symbol == "SPY"  # index alias


def test_resolve_normalizes_and_crypto_wins_over_ticker_fallback():
    assert resolve_asset("$tsla").symbol == "TSLA"  # type: ignore[union-attr]  — $ stripped, upper-cased, equity
    assert resolve_asset("eth").asset_class == "crypto"  # type: ignore[union-attr]  — crypto map beats ticker shape


def test_resolve_returns_none_for_junk():
    assert resolve_asset("this is not a ticker") is None
    assert resolve_asset("") is None
    assert resolve_asset("TOOLONGSYM") is None


# --------------------------------------------------------------------------- build_tape routing


def test_build_tape_routes_by_class_and_keys_by_original_asset():
    crypto = _FakeProvider({"BTCUSDT": _bars(5)})
    equity = _FakeProvider({"AAPL": _bars(5), "GLD": _bars(5)})
    tape = build_tape(["BTC", "AAPL", "GOLD", "NONSENSEXYZ"], crypto_provider=crypto, equity_provider=equity)

    assert set(tape) == {"BTC", "AAPL", "GOLD"}            # the junk asset is omitted (no_data)
    assert crypto.calls == ["BTCUSDT"]                     # crypto routed to the crypto provider
    assert sorted(equity.calls) == ["AAPL", "GLD"]         # equity + commodity-proxy routed to equity provider
    assert all(isinstance(p, PricePoint) for p in tape["GOLD"])  # bars adapted to PricePoints
    assert tape["GOLD"][0].price == 100.0                  # close → price


def test_build_tape_is_offline_safe_when_providers_raise():
    tape = build_tape(["BTC", "AAPL"], crypto_provider=_RaisingProvider(), equity_provider=_RaisingProvider())
    assert tape == {}  # every asset degrades to no_data; nothing raises


def test_crypto_symbol_override_routes_through_crypto_provider():
    crypto = _FakeProvider({"FOO": _bars(3)})
    equity = _FakeProvider({})
    tape = build_tape(["XYZ"], crypto_provider=crypto, equity_provider=equity, crypto_symbol_override={"xyz": "FOO"})
    assert "XYZ" in tape and crypto.calls == ["FOO"] and equity.calls == []
