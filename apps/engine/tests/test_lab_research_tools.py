"""The propose-only research tool bus: each tool returns offline-deterministically with NO key, and
EXECUTION can never be registered on the bus."""

from __future__ import annotations

import pytest

from cosmu.lab.tools.registry import ToolDefinition, default_tool_bus
from cosmu.lab.tools.research_tools import research_tool_bus


def test_research_tools_return_offline_deterministically_no_key():
    bus = research_tool_bus()  # no keys passed → fully offline
    names = {t["name"] for t in bus.list_tools()}
    assert {"web_search", "news_read", "social", "pine_fetch", "rag_read"} <= names

    ws = bus.call("web_search", {"query": "crypto momentum"})
    assert ws["ok"] and ws["source"] == "offline" and ws["results"]

    nr = bus.call("news_read", {"symbol": "BTCUSDT", "offline": True, "limit": 2})
    assert nr["source"] == "offline" and nr["headlines"]

    soc = bus.call("social", {"symbol": "BTCUSDT"})
    assert soc["source"] == "offline" and "galaxy_score" in soc["metrics"]

    pf = bus.call("pine_fetch", {})
    assert pf["ok"] and pf["names"]

    rag = bus.call("rag_read", {"query": "osint"})
    assert rag["ok"] and any("osint" in m["feature"] for m in rag["matches"])

    # determinism: same call → identical result, no LLM/network
    assert bus.call("social", {"symbol": "BTCUSDT"}) == soc


def test_execution_is_never_on_the_bus():
    bus = research_tool_bus()
    # the bus rejects an execution-named or non-readonly tool
    with pytest.raises(ValueError):
        bus.register(ToolDefinition(name="execute_order", intent="x", readonly=True, handler=lambda p: {}))
    with pytest.raises(ValueError):
        bus.register(ToolDefinition(name="place_order", intent="x", readonly=True, handler=lambda p: {}))
    with pytest.raises(ValueError):
        bus.register(ToolDefinition(name="risky", intent="x", readonly=False, handler=lambda p: {}))
    # and no execution/order tool is present after construction
    names = {t["name"] for t in bus.list_tools()}
    assert not any("execute" in n or "order" in n for n in names)


def test_research_bus_replaces_stub_rag_with_fixture_backed():
    base = default_tool_bus()
    base_rag = base.call("rag_read", {"query": "x"})
    assert base_rag["matches"] == []  # the stub returns nothing
    rich = research_tool_bus().call("rag_read", {"query": "prior art"})
    assert rich["matches"]  # the research bus replaced it with the fixture-backed reader


def test_social_serves_from_store_when_fresh(tmp_path):
    """_social returns source='store' and skips the API when a <25h read is in the AltDataStore."""
    from datetime import UTC, datetime, timedelta

    from cosmu.data.altdata import AltDataPoint, AltDataStore
    from cosmu.lab.tools.research_tools import _social

    store = AltDataStore(tmp_path / "alt")
    now = datetime.now(UTC)
    fresh = now - timedelta(hours=1)
    store.append("lunarcrush", "BTC", "galaxy_score", [AltDataPoint(ts=fresh, available_at=fresh, value=71.0)])
    store.append("lunarcrush", "BTC", "social_volume", [AltDataPoint(ts=fresh, available_at=fresh, value=42100.0)])
    store.append("lunarcrush", "BTC", "social_sentiment", [AltDataPoint(ts=fresh, available_at=fresh, value=0.44)])

    result = _social({"symbol": "BTCUSDT", "_api_key": "key", "_store": store})

    assert result["source"] == "store"
    assert result["metrics"]["galaxy_score"] == 71.0
    assert result["metrics"]["social_volume"] == 42100.0


def test_social_falls_through_to_api_when_store_stale(tmp_path):
    """_social bypasses a >25h stale store entry and falls through to offline fixture (no live key here)."""
    from datetime import UTC, datetime, timedelta

    from cosmu.data.altdata import AltDataPoint, AltDataStore
    from cosmu.lab.tools.research_tools import _social

    store = AltDataStore(tmp_path / "alt")
    stale = datetime.now(UTC) - timedelta(hours=30)
    store.append("lunarcrush", "BTC", "galaxy_score", [AltDataPoint(ts=stale, available_at=stale, value=50.0)])

    result = _social({"symbol": "BTCUSDT", "_store": store})  # no api_key → offline path

    assert result["source"] == "offline"  # stale store → not served; no key → offline fixture
