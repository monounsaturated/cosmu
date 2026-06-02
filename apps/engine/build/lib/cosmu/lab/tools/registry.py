# intent: register read/research/propose-only tools for the lab agent; inputs: typed tool definitions; outputs: discoverable registry; invariants: execution and live venue access never appear on the bus.

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    intent: str
    readonly: bool
    handler: Callable[[dict[str, Any]], dict[str, Any]]


class ToolBus:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        if not tool.readonly:
            raise ValueError("tool bus accepts read/research/propose-only tools")
        if "execute" in tool.name or "order" in tool.name:
            raise ValueError("execution tools are forbidden on the lab bus")
        self._tools[tool.name] = tool

    def call(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tools[name].handler(payload)

    def list_tools(self) -> list[dict[str, str]]:
        return [{"name": tool.name, "intent": tool.intent} for tool in self._tools.values()]


def default_tool_bus() -> ToolBus:
    bus = ToolBus()
    bus.register(
        ToolDefinition(
            name="market_data_read",
            intent="Read point-in-time market data availability and feature metadata.",
            readonly=True,
            handler=lambda payload: {"ok": True, "symbol": payload.get("symbol"), "bars_catalog": "ParquetDataCatalog"},
        )
    )
    bus.register(
        ToolDefinition(
            name="backtest_research",
            intent="Request a deterministic research backtest proposal; execution remains in the master.",
            readonly=True,
            handler=lambda payload: {"ok": True, "proposal": payload, "note": "submit to master queue"},
        )
    )
    bus.register(
        ToolDefinition(
            name="rag_read",
            intent="Read relevant prior art and structured notes.",
            readonly=True,
            handler=lambda payload: {"ok": True, "query": payload.get("query"), "matches": []},
        )
    )
    return bus

