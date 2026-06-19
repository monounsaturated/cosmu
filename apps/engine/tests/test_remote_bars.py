# The REMOTE-BARS lane: a Binance-reachable HTTP engine (Railway EU /market/bars) serves OHLCV so a geo-blocked
# compute account (Modal US) fetches bars at runtime — no bundled cache, modular/account-swappable deploys. The
# endpoint's _bars_to_rows output must round-trip through RemoteBarsProvider (_bar_from_json) byte-faithfully, the
# factory must be env-gated (BYTE-IDENTICAL to before when COSMU_BARS_URL is unset), and the provider must degrade
# to [] offline (never fabricate).

from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

import cosmu.data.market as market
from cosmu.data.market import (
    Bar,
    BinanceSpotOHLCVProvider,
    RemoteBarsProvider,
    _bars_to_rows,
    default_crypto_reference,
)


@pytest.fixture(autouse=True)
def _clear_remote_memo():
    """RemoteBarsProvider memoizes per (base_url, symbol, tf, limit) PROCESS-WIDE (the cohort efficiency win). Clear
    it around each test so a prior test's memoized fetch can't satisfy the next (e.g. the offline test must see a
    real fetch attempt, not a cached hit) — production memoization is exactly the intended behaviour."""
    market._REMOTE_BARS_MEMO.clear()
    yield
    market._REMOTE_BARS_MEMO.clear()


def _bars(n: int) -> list[Bar]:
    base = datetime(2024, 1, 1, tzinfo=UTC)
    return [
        Bar(ts=base.replace(day=i + 1), open=Decimal("100.5"), high=Decimal("101"), low=Decimal("99"),
            close=Decimal(str(100 + i)), volume=Decimal("12.3"))
        for i in range(n)
    ]


def test_factory_is_env_gated(monkeypatch):
    monkeypatch.delenv("COSMU_BARS_URL", raising=False)
    assert isinstance(default_crypto_reference(), BinanceSpotOHLCVProvider)  # unset → byte-identical default
    monkeypatch.setenv("COSMU_BARS_URL", "https://cosmu.up.railway.app")
    prov = default_crypto_reference()
    assert isinstance(prov, RemoteBarsProvider)
    assert prov.base_url == "https://cosmu.up.railway.app"  # trailing slash stripped is also fine


def test_remote_provider_round_trips_endpoint_rows(monkeypatch):
    """The endpoint serializes via _bars_to_rows; RemoteBarsProvider parses via _bar_from_json — same Decimals back."""
    src = _bars(5)
    payload = json.dumps({"symbol": "BTCUSDT", "timeframe": "1d", "bars": _bars_to_rows(src)}).encode()

    captured = {}

    def fake_urlopen(req, timeout=None, context=None):  # noqa: ANN001, ARG001
        captured["url"] = req.full_url
        captured["x-api-key"] = req.headers.get("X-api-key")
        return io.BytesIO(payload)

    monkeypatch.setattr(market.urllib.request, "urlopen", fake_urlopen)
    prov = RemoteBarsProvider("https://eu.example/", api_key="secret-xyz")
    out = prov.fetch_bars("BTCUSDT", "1d", limit=10)

    assert [b.close for b in out] == [b.close for b in src]  # exact Decimals preserved
    assert "symbol=BTCUSDT" in captured["url"] and "/market/bars?" in captured["url"]
    assert captured["x-api-key"] == "secret-xyz"  # shared-secret header sent


def test_remote_provider_offline_returns_empty(monkeypatch):
    def boom(req, timeout=None, context=None):  # noqa: ANN001, ARG001
        raise OSError("refused")

    monkeypatch.setattr(market.urllib.request, "urlopen", boom)
    assert RemoteBarsProvider("https://eu.example").fetch_bars("BTCUSDT", "1d", limit=10) == []  # degrade, never fabricate


def test_market_bars_endpoint_shape(monkeypatch):
    from fastapi.testclient import TestClient

    import cosmu.api.app as app_mod
    import cosmu.api.routers.market as market_router

    class _Stub:
        def fetch_bars(self, symbol, timeframe, *, limit):  # noqa: ANN001, ARG002
            return _bars(3)

    monkeypatch.setattr(market_router, "BinanceSpotOHLCVProvider", lambda: _Stub())
    client = TestClient(app_mod.app)
    r = client.get("/market/bars", params={"symbol": "BTCUSDT", "timeframe": "1d", "limit": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["symbol"] == "BTCUSDT" and len(body["bars"]) == 3
    assert set(body["bars"][0]) == {"ts", "open", "high", "low", "close", "volume"}
    assert isinstance(body["bars"][0]["close"], str)  # OHLCV as strings → exact Decimals on the client
