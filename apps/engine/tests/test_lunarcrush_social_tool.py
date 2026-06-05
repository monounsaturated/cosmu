"""Focused tests for the LunarCrush social tools on the lab research bus.

Covers: offline-safe fixture shapes, symbol normalisation, key-gated live-path
mock, bad-response degradation, social_top ranking, and bus-registration invariants.
All tests are network-free — no LUNARCRUSH_API_KEY required.
"""

from __future__ import annotations

import cosmu.lab.tools.research_tools as rt
from cosmu.lab.tools.research_tools import _coin_of, _social, _social_top, research_tool_bus


# ---------------------------------------------------------------------------
# _coin_of helper
# ---------------------------------------------------------------------------

def test_coin_of_strips_usdt_suffix() -> None:
    assert _coin_of("BTCUSDT") == "BTC"
    assert _coin_of("ETHUSDT") == "ETH"
    assert _coin_of("SOLUSDT") == "SOL"
    assert _coin_of("LINKUSDT") == "LINK"
    # bare symbol (no USDT suffix) → uppercased
    assert _coin_of("btc") == "BTC"
    assert _coin_of("eth") == "ETH"


# ---------------------------------------------------------------------------
# _social: single-coin snapshot
# ---------------------------------------------------------------------------

def test_social_offline_known_btc() -> None:
    result = _social({"symbol": "BTCUSDT"})
    assert result["ok"]
    assert result["source"] == "offline"
    assert result["symbol"] == "BTCUSDT"
    metrics = result["metrics"]
    assert {"galaxy_score", "social_volume", "sentiment"} == metrics.keys()
    assert metrics["galaxy_score"] == 71.0
    assert metrics["social_volume"] == 42100.0
    assert metrics["sentiment"] == 0.44


def test_social_offline_known_eth() -> None:
    result = _social({"symbol": "ETHUSDT"})
    assert result["metrics"]["social_volume"] == 27800.0
    assert result["metrics"]["galaxy_score"] == 64.0


def test_social_offline_default_for_unknown_coin() -> None:
    result = _social({"symbol": "UNKNOWNUSDT"})
    assert result["ok"]
    assert result["source"] == "offline"
    assert "galaxy_score" in result["metrics"]
    assert result["metrics"]["galaxy_score"] == 62.0  # _default fixture


def test_social_no_key_no_symbol_is_offline_safe() -> None:
    result = _social({})
    assert result["ok"]
    assert result["source"] == "offline"


def test_social_deterministic_offline(monkeypatch: object) -> None:
    monkeypatch.setattr(rt, "_http_json", lambda *a, **kw: None)
    a = _social({"symbol": "BTCUSDT"})
    b = _social({"symbol": "BTCUSDT"})
    assert a == b


def test_social_live_path_maps_fields(monkeypatch: object) -> None:
    monkeypatch.setattr(rt, "_http_json", lambda *a, **kw: {
        "data": {"galaxy_score": 77.5, "social_volume_24h": 55000.0, "sentiment": 0.52}
    })
    result = _social({"symbol": "SOLUSDT", "_api_key": "fake-key"})
    assert result["source"] == "live"
    assert result["metrics"]["galaxy_score"] == 77.5
    assert result["metrics"]["social_volume"] == 55000.0
    assert result["metrics"]["sentiment"] == 0.52


def test_social_live_path_degrades_on_none_response(monkeypatch: object) -> None:
    monkeypatch.setattr(rt, "_http_json", lambda *a, **kw: None)
    result = _social({"symbol": "BTCUSDT", "_api_key": "fake-key"})
    assert result["source"] == "offline"


def test_social_live_path_degrades_on_missing_data_key(monkeypatch: object) -> None:
    monkeypatch.setattr(rt, "_http_json", lambda *a, **kw: {"error": "not found"})
    result = _social({"symbol": "BTCUSDT", "_api_key": "fake-key"})
    assert result["source"] == "offline"


# ---------------------------------------------------------------------------
# _social_top: cross-asset ranking
# ---------------------------------------------------------------------------

def test_social_top_offline_fixture_has_five_plus_coins() -> None:
    result = _social_top({"limit": 5})
    assert result["ok"]
    assert result["source"] == "offline"
    assert len(result["coins"]) == 5
    assert result["sort_by"] == "social_volume"


def test_social_top_offline_coin_schema() -> None:
    for coin in _social_top({"limit": 10})["coins"]:
        assert {"symbol", "galaxy_score", "social_volume", "sentiment"} == coin.keys()
        assert isinstance(coin["galaxy_score"], float)
        assert isinstance(coin["social_volume"], float)


def test_social_top_respects_limit() -> None:
    assert len(_social_top({"limit": 2})["coins"]) == 2
    assert len(_social_top({"limit": 1})["coins"]) == 1


def test_social_top_limit_clamps_at_50() -> None:
    assert len(_social_top({"limit": 100})["coins"]) <= 50


def test_social_top_no_key_is_offline_safe() -> None:
    result = _social_top({})
    assert result["ok"]
    assert result["source"] == "offline"


def test_social_top_live_path_normalises_symbols(monkeypatch: object) -> None:
    monkeypatch.setattr(rt, "_http_json", lambda *a, **kw: {
        "data": [
            {"symbol": "BTC", "galaxy_score": 72.0, "social_volume_24h": 50000.0, "sentiment": 0.45},
            {"symbol": "ETH", "galaxy_score": 65.0, "social_volume_24h": 30000.0, "sentiment": 0.40},
        ]
    })
    result = _social_top({"limit": 5, "_api_key": "fake-key"})
    assert result["source"] == "live"
    symbols = [c["symbol"] for c in result["coins"]]
    assert "BTCUSDT" in symbols
    assert "ETHUSDT" in symbols


def test_social_top_live_path_degrades_on_none_response(monkeypatch: object) -> None:
    monkeypatch.setattr(rt, "_http_json", lambda *a, **kw: None)
    result = _social_top({"limit": 5, "_api_key": "fake-key"})
    assert result["source"] == "offline"


# ---------------------------------------------------------------------------
# Bus registration invariants
# ---------------------------------------------------------------------------

def test_social_and_social_top_on_research_bus() -> None:
    bus = research_tool_bus()
    names = {t["name"] for t in bus.list_tools()}
    assert "social" in names
    assert "social_top" in names


def test_bus_social_callable_offline() -> None:
    bus = research_tool_bus()
    s = bus.call("social", {"symbol": "ETHUSDT"})
    assert s["ok"] and s["source"] == "offline"


def test_bus_social_top_callable_offline() -> None:
    bus = research_tool_bus()
    st = bus.call("social_top", {"limit": 3})
    assert st["ok"] and len(st["coins"]) == 3
