# intent: the per-symbol Lab contract — one row per (strategy × symbol × venue) backtest cell, the granular truth
# the pooled leaderboard averages away. The verdict is the HONEST cross-symbol label (robust/fragile/thin/negative)
# so the UI can sort by outlier WITHOUT celebrating a lone best-of-N winner. Visibility only; never a funding signal.

from __future__ import annotations

from pydantic import BaseModel


class LabSymbolRow(BaseModel):
    strategy_version_id: str
    strategy_name: str
    kind: str                     # 'quant' | 'llm' — the strategy MODEL that produced this cell
    status: str                   # the version's lifecycle status (screened/paper/live/killed/…) — advisory context
    symbol: str
    venue_id: str | None          # the fee axis (the same edge costs differently per venue)
    return_pct: float             # standalone validation return on THIS symbol (not a pooled mean)
    sharpe: float
    max_drawdown: float
    trades: int
    verdict: str | None           # robust | fragile | thin | negative — the honest cross-symbol label (NULL = legacy)
    created_at: str


class LabSymbolsResponse(BaseModel):
    rows: list[LabSymbolRow]
    symbols: list[str]            # the distinct symbols present — drives the filter chips
    venues: list[str]             # the distinct venues present — drives the filter chips
