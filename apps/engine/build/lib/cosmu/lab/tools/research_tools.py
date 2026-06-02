# intent: the PROPOSE-ONLY research tools the lab agent uses to GATHER CONTEXT before authoring a spec —
# web_search, news_read, social (LunarCrush), pine_fetch, rag_read. Each is a small, typed, READ-ONLY tool
# registered onto the existing lab ToolBus (registry.py): the bus rejects anything non-readonly or named
# like execution, so EXECUTION IS NEVER ON THE BUS. Every tool is LLM-OPTIONAL and offline-DETERMINISTIC:
# with no key it returns a bundled fixture result so the research pass runs fully in CI with no network.
# Secrets (LunarCrush / search keys) stay server-side; we read them from settings, never from the payload.

from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request
from typing import Any

from cosmu.lab.tools.registry import ToolBus, ToolDefinition
from cosmu.strategy.pine_samples import PINE_SAMPLES


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _http_json(url: str, headers: dict[str, str] | None = None, timeout: float = 15.0) -> dict | None:
    """Best-effort GET → JSON. Returns None on any failure so a tool degrades to its offline fixture
    rather than crashing the research pass (LLM/network-optional, never load-bearing)."""
    req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 — context-gathering is best-effort; degrade to fixture
        return None


# --- deterministic offline fixtures (the no-key path; identical shape to the live path) ---------------

_WEB_FIXTURES: dict[str, list[dict[str, str]]] = {
    "_default": [
        {"title": "Crypto momentum factor research", "snippet": "Medium-term return continuation persists net of costs at swing horizon.", "url": "https://example.org/momentum"},
        {"title": "Funding-rate carry and crowded leverage", "snippet": "Extreme perpetual funding precedes mean-reverting unwinds.", "url": "https://example.org/funding"},
    ],
}
_NEWS_FIXTURES: dict[str, list[dict[str, str]]] = {
    "_default": [
        {"headline": "Bitcoin surges as ETF inflows hit record", "ts": "2024-01-01T00:00:00Z", "url": "https://example.org/n1"},
        {"headline": "Exchange announces partnership and adoption push", "ts": "2024-01-02T00:00:00Z", "url": "https://example.org/n2"},
    ],
}
_SOCIAL_FIXTURES: dict[str, dict[str, float]] = {
    "_default": {"galaxy_score": 62.0, "social_volume": 18450.0, "sentiment": 0.31},
    "BTC": {"galaxy_score": 71.0, "social_volume": 42100.0, "sentiment": 0.44},
    "ETH": {"galaxy_score": 64.0, "social_volume": 27800.0, "sentiment": 0.38},
}
_RAG_FIXTURES: list[dict[str, str]] = [
    {"title": "Prior art: oversold mean reversion", "note": "Washed-out sentiment + statistically unusual selloff reverts at swing horizon.", "feature": "rsi"},
    {"title": "Prior art: cross-asset risk transfer", "note": "Prediction-market odds + macro regime price risk before any single asset.", "feature": "macro_regime"},
    {"title": "Prior art: OSINT air activity", "note": "Aircraft activity is a crude low-confidence macro proxy; must earn its place via OOS.", "feature": "osint_air_activity"},
]


def _coin_of(symbol: str) -> str:
    return symbol[:-4] if symbol.upper().endswith("USDT") else symbol.upper()


# --- handlers (each returns {"ok": True, "source": "live"|"offline", ...}) -----------------------------


def _web_search(payload: dict[str, Any]) -> dict[str, Any]:
    query = str(payload.get("query", "")).strip()
    api_key = payload.get("_api_key")  # injected server-side by the bus factory, never from the LLM
    if api_key and query:
        url = "https://api.tavily.com/search?" + urllib.parse.urlencode({"query": query})
        data = _http_json(url, headers={"Authorization": f"Bearer {api_key}"})
        if data and data.get("results"):
            results = [{"title": r.get("title", ""), "snippet": r.get("content", "")[:240], "url": r.get("url", "")} for r in data["results"][:8]]
            return {"ok": True, "source": "live", "query": query, "results": results}
    return {"ok": True, "source": "offline", "query": query, "results": _WEB_FIXTURES["_default"]}


def _news_read(payload: dict[str, Any]) -> dict[str, Any]:
    symbol = str(payload.get("symbol", "BTCUSDT"))
    limit = int(payload.get("limit", 8))
    # Live path reuses the free, no-key GDELT provider (point-in-time headlines); offline → fixture.
    if not payload.get("offline", False):
        from cosmu.data.altdata import GdeltNewsProvider

        try:
            items = GdeltNewsProvider().fetch_news(symbol, limit=limit)
            if items:
                return {"ok": True, "source": "live", "symbol": symbol, "headlines": [{"headline": i.headline, "ts": i.ts.isoformat(), "available_at": i.available_at.isoformat()} for i in items]}
        except Exception:  # noqa: BLE001 — best-effort; degrade to fixture
            pass
    return {"ok": True, "source": "offline", "symbol": symbol, "headlines": _NEWS_FIXTURES["_default"][:limit]}


def _social(payload: dict[str, Any]) -> dict[str, Any]:
    symbol = str(payload.get("symbol", "BTCUSDT"))
    coin = _coin_of(symbol)
    api_key = payload.get("_api_key")  # LunarCrush key, server-side only
    if api_key:
        url = f"https://lunarcrush.com/api4/public/coins/{coin}/v1"
        data = _http_json(url, headers={"Authorization": f"Bearer {api_key}"})
        if data and data.get("data"):
            d = data["data"]
            metrics = {"galaxy_score": float(d.get("galaxy_score", 0.0)), "social_volume": float(d.get("social_volume_24h", 0.0)), "sentiment": float(d.get("sentiment", 0.0))}
            return {"ok": True, "source": "live", "symbol": symbol, "metrics": metrics}
    return {"ok": True, "source": "offline", "symbol": symbol, "metrics": _SOCIAL_FIXTURES.get(coin, _SOCIAL_FIXTURES["_default"])}


def _pine_fetch(payload: dict[str, Any]) -> dict[str, Any]:
    """Fetch a community Pine script by name from the bundled sample library (the offline/no-key corpus the
    pine translator already exercises). A live scraper is intentionally NOT on the bus — that would be an
    unbounded network/execution surface; the lab reads from the curated corpus and proposes a translation."""
    name = payload.get("name")
    if name and name in PINE_SAMPLES:
        return {"ok": True, "source": "offline", "name": name, "pine": PINE_SAMPLES[name]}
    return {"ok": True, "source": "offline", "names": sorted(PINE_SAMPLES), "note": "pass {'name': <one of names>} to fetch a script"}


def _rag_read(payload: dict[str, Any]) -> dict[str, Any]:
    query = str(payload.get("query", "")).lower()
    matches = [m for m in _RAG_FIXTURES if not query or query in (m["title"] + " " + m["note"] + " " + m["feature"]).lower()]
    return {"ok": True, "source": "offline", "query": query, "matches": matches or _RAG_FIXTURES}


def register_research_tools(bus: ToolBus, *, lunarcrush_key: str | None = None, web_search_key: str | None = None) -> ToolBus:
    """Extend an existing lab ToolBus with the propose-only research tools. Keys are bound server-side here
    (closed over), so the LLM payload can never carry a secret. Returns the same bus for chaining."""

    def _bind(handler, key):  # noqa: ANN001 — inject the server-side key into the payload, transparently
        def wrapped(payload: dict[str, Any]) -> dict[str, Any]:
            return handler({**payload, "_api_key": key} if key else payload)

        return wrapped

    bus.register(ToolDefinition(name="web_search", intent="Search the web for strategy ideas / prior art (read-only context).", readonly=True, handler=_bind(_web_search, web_search_key)))
    bus.register(ToolDefinition(name="news_read", intent="Read point-in-time news headlines for a symbol (read-only context).", readonly=True, handler=_news_read))
    bus.register(ToolDefinition(name="social", intent="Read LunarCrush social metrics (galaxy score, social volume, sentiment).", readonly=True, handler=_bind(_social, lunarcrush_key)))
    bus.register(ToolDefinition(name="pine_fetch", intent="Fetch a community Pine script from the curated corpus to translate (read-only).", readonly=True, handler=_pine_fetch))
    bus.register(ToolDefinition(name="rag_read", intent="Read relevant prior art and structured research notes (read-only).", readonly=True, handler=_rag_read))
    return bus


def research_tool_bus(*, lunarcrush_key: str | None = None, web_search_key: str | None = None) -> ToolBus:
    """The default lab bus (market_data_read / backtest_research / rag_read) PLUS the research tools.
    Built so any agent can discover + call them. Execution can never be registered (the bus rejects it)."""
    from cosmu.lab.tools.registry import default_tool_bus

    bus = default_tool_bus()
    # default_tool_bus already registers a stub rag_read; the richer fixture-backed one replaces it.
    bus._tools.pop("rag_read", None)  # noqa: SLF001 — same package, intentional replace of the stub
    return register_research_tools(bus, lunarcrush_key=lunarcrush_key, web_search_key=web_search_key)
