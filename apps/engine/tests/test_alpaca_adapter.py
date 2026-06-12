# Alpaca equities adapter (data + paper execution): paper-by-default key resolution, no-keys disabled
# (no network), idempotent submit on client_order_id, pure parse layers against canned JSON, the equity
# closed-bar guard + stale-cache refetch the keyless providers lack, and secrets never stored or returned.

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from cosmu.adapters.data.alpaca import AlpacaDailyBarsProvider, AlpacaDataAdapter, _parse_bars
from cosmu.adapters.exec.alpaca import (
    AlpacaExecutionAdapter,
    build_order_body,
    parse_fills,
    parse_positions,
    resolve_mode,
)
from cosmu.config.settings import LiveSettings, Settings
from cosmu.core.interfaces import Order

_NOW = dt.datetime(2024, 6, 3, 12, 0, tzinfo=dt.UTC)  # a Monday mid-session


def _settings(**kw) -> Settings:
    """Settings with ALL Alpaca keys explicitly cleared so the active .env can't leak into key-resolution
    tests. Callers re-add only the keys the case is about."""
    base = dict(
        database_url="sqlite:///:memory:",
        alpaca_api_key=None,
        alpaca_api_secret=None,
        alpaca_paper_api_key=None,
        alpaca_paper_api_secret=None,
    )
    base.update(kw)
    return Settings(**base)


# --------------------------------------------------------------------- the never-auto-live key interlock


def test_no_keys_is_disabled_and_never_touches_network():
    settings = _settings()
    assert resolve_mode(settings) == "disabled"
    adapter = AlpacaExecutionAdapter.from_settings(settings)
    assert adapter.active is False
    assert adapter.positions() == [] and adapter.fills(_NOW) == []


def test_paper_keys_resolve_paper_and_take_precedence_over_live():
    paper = _settings(alpaca_paper_api_key="pk", alpaca_paper_api_secret="ps")
    assert resolve_mode(paper) == "paper"
    both = _settings(alpaca_paper_api_key="pk", alpaca_paper_api_secret="ps",
                     alpaca_api_key="rk", alpaca_api_secret="rs", live=LiveSettings(mode="real"))
    assert resolve_mode(both) == "paper"  # paper always wins when present — never auto-pick real money


def test_live_keys_require_live_mode_real():
    no_mode = _settings(alpaca_api_key="rk", alpaca_api_secret="rs", live=LiveSettings(mode="testnet"))
    assert resolve_mode(no_mode) == "disabled"  # real keys but mode not "real" -> never trades real
    armed = _settings(alpaca_api_key="rk", alpaca_api_secret="rs", live=LiveSettings(mode="real"))
    assert resolve_mode(armed) == "live"


def test_secrets_never_stored_on_the_adapter_instance():
    settings = _settings(alpaca_paper_api_key="sk-PAPER-XYZ", alpaca_paper_api_secret="sk-SECRET-XYZ")
    adapter = AlpacaExecutionAdapter.from_settings(settings)
    blob = repr(vars(adapter))
    assert "sk-PAPER-XYZ" not in blob and "sk-SECRET-XYZ" not in blob


# --------------------------------------------------------------------------------- idempotent order path


class _Transport:
    """Canned no-network transport: records calls; fakes the by_client_order_id idempotency lookup."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self._orders: dict[str, dict] = {}

    def __call__(self, method, path, *, query=None, body=None):
        self.calls.append((method, path))
        if path == "/v2/orders:by_client_order_id":
            coid = (query or {}).get("client_order_id", "")
            if coid in self._orders:
                return self._orders[coid]
            raise ValueError("404 order not found")
        if method == "POST" and path == "/v2/orders":
            raw = {"id": f"venue-{len(self._orders) + 1}", "client_order_id": (body or {}).get("client_order_id")}
            self._orders[str(raw["client_order_id"])] = raw
            return raw
        if path == "/v2/positions":
            return [{"symbol": "SPY", "qty": "3", "side": "long", "avg_entry_price": "500.10"},
                    {"symbol": "TLT", "qty": "2", "side": "short", "avg_entry_price": "90.00"}]
        if path.startswith("/v2/account/activities"):
            return [{"order_id": "venue-1", "symbol": "SPY", "side": "buy", "qty": "3", "price": "500.10",
                     "transaction_time": "2024-06-03T14:30:00Z"}]
        return {}


def _order(coid="cosmu-eq-1") -> Order:
    return Order(instrument_id="SPY", side=1, qty=Decimal("3"), order_type="market",
                 limit_price=None, client_order_id=coid, ts=_NOW)


def test_submit_is_idempotent_on_client_order_id():
    transport = _Transport()
    adapter = AlpacaExecutionAdapter(transport=transport, mode="paper")
    first = adapter.submit(_order())
    second = adapter.submit(_order())  # replay: must return the SAME venue order, never a second POST
    assert first.venue_order_id == second.venue_order_id == "venue-1"
    assert sum(1 for m, p in transport.calls if m == "POST" and p == "/v2/orders") == 1


def test_order_body_maps_types_and_limit_price():
    market = build_order_body(_order())
    assert market["type"] == "market" and "limit_price" not in market and market["time_in_force"] == "day"
    limit = build_order_body(Order(instrument_id="SPY", side=-1, qty=Decimal("1"), order_type="maker",
                                   limit_price=Decimal("501.25"), client_order_id="x", ts=_NOW))
    assert limit["type"] == "limit" and limit["limit_price"] == "501.25" and limit["side"] == "sell"


def test_parse_layers_are_pure_and_signed():
    fills = parse_fills([{"order_id": "v1", "symbol": "SPY", "side": "sell", "qty": "2", "price": "499.5",
                          "transaction_time": "2024-06-03T15:00:00Z"}])
    assert fills[0].side == -1 and fills[0].qty == Decimal("2") and fills[0].ts.tzinfo is not None
    positions = parse_positions([{"symbol": "TLT", "qty": "2", "side": "short", "avg_entry_price": "90"}])
    assert positions[0].qty == Decimal("-2")  # the signed-qty short convention


# ------------------------------------------------------------------------- bars: closed, adjusted, cached


_PAYLOAD = {
    "bars": [
        {"t": "2024-05-30T04:00:00Z", "o": 500.0, "h": 505.0, "l": 498.0, "c": 504.0, "v": 1000},
        {"t": "2024-05-31T04:00:00Z", "o": 504.0, "h": 506.0, "l": 501.0, "c": 502.5, "v": 1100},
        {"t": "2024-06-03T04:00:00Z", "o": 503.0, "h": 507.0, "l": 502.0, "c": 506.0, "v": 900},  # in progress
    ]
}


def test_bars_drop_the_in_progress_daily_bar(tmp_path):
    """The deep review's equity gap: keyless providers serve today's partial bar and freeze their cache. The
    Alpaca lane must drop the unclosed bar — mid-session, today's daily bar never reaches the cache."""
    provider = AlpacaDailyBarsProvider(tmp_path / "bars", fetcher=lambda s, n: _PAYLOAD, now_fn=lambda: _NOW)
    bars = provider.fetch_bars("SPY", "1d", limit=10)
    assert [b.ts.date().isoformat() for b in bars] == ["2024-05-30", "2024-05-31"]
    assert bars[-1].close == Decimal("502.5")


def test_bars_cache_serves_offline_but_refetches_when_stale(tmp_path):
    calls = {"n": 0}

    def _fetch(symbol, limit):
        calls["n"] += 1
        return _PAYLOAD

    # Mid-week, intra-session: the newest CLOSED bar (05-30) is still the latest closed candle, so a covering
    # cache is FRESH and served from disk — no second network call.
    midweek = dt.datetime(2024, 5, 31, 12, 0, tzinfo=dt.UTC)
    provider = AlpacaDailyBarsProvider(tmp_path / "bars", fetcher=_fetch, now_fn=lambda: midweek)
    provider.fetch_bars("SPY", "1d", limit=1)
    provider.fetch_bars("SPY", "1d", limit=1)
    assert calls["n"] == 1
    # Days later the cache is STALE for a daily series — it must refetch, never serve a frozen cache forever
    # (the keyless Yahoo/Stooq behaviour the deep review flagged).
    stale_provider = AlpacaDailyBarsProvider(tmp_path / "bars", fetcher=_fetch, now_fn=lambda: _NOW)
    bars = stale_provider.fetch_bars("SPY", "1d", limit=2)
    assert calls["n"] == 2
    assert [b.ts.date().isoformat() for b in bars] == ["2024-05-30", "2024-05-31"]


def test_provider_and_adapter_are_key_gated():
    assert AlpacaDailyBarsProvider.from_settings(_settings()) is None  # no keys → callers keep Yahoo/Stooq
    adapter = AlpacaDataAdapter.from_settings(_settings())
    assert adapter.universe(_NOW) == []
    assert adapter.bars("spy-alpaca", _NOW - dt.timedelta(days=10), _NOW, "1d") == []


def test_parse_bars_is_pure_utc_and_sorted():
    bars = _parse_bars({"bars": [
        {"t": "2024-05-31T04:00:00Z", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 10},
        {"t": "2024-05-30T04:00:00Z", "o": 1, "h": 2, "l": 0.5, "c": 1.2, "v": 10},
        {"t": "bad", "o": 1, "h": 2, "l": 0.5, "c": 1.2, "v": 10},  # malformed row skipped, never fabricated
    ]})
    assert len(bars) == 2
    assert bars[0].ts < bars[1].ts and bars[0].ts.tzinfo is not None
