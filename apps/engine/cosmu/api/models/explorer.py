# intent: Strategy Explorer read-only contracts — per-version backtest snapshot for the
# operator's pick-and-compare UI; inputs: stored backtests/executions/spec; outputs: typed
# explorer responses; invariants: read-only, no new backtests triggered, never fabricated.

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ExplorerPoint(BaseModel):
    """A single (ts, gross_value, net_value) equity curve point."""

    ts: str
    gross: float
    net: float


class ExplorerTrade(BaseModel):
    """A single fill with an entry/exit marker type."""

    ts: str
    side: str   # "buy" | "sell"
    price: float
    qty: float
    fee: float


class ExplorerStats(BaseModel):
    """Glanceable stats panel — explicit, never fabricated.  Fields are None when data
    is not yet stored; the UI renders "not available" for None values."""

    thesis: str | None
    asset: str | None
    venue: str | None
    fee_assumed_bps: float | None
    data_span_days: int | None
    num_bars: int | None
    gross_return_pct: float | None
    net_return_pct: float | None
    cost_ratio: float | None       # total_fees / gross_profit (None if no gross profit)
    num_trades: int | None
    deflated_sharpe: float | None
    max_dd: float | None
    oos_holdout_pct: float | None
    gate_decision: str | None      # "PASS" | "FAIL" | None
    gate_reason: str | None        # the blocking reason, or None if PASS


class ExplorerVersion(BaseModel):
    """One strategy-version for the explorer selector."""

    version_id: str
    name: str
    status: str
    venue: str
    asset_class: str
    timeframe: str
    signal_family_label: str
    deflated_sharpe: float
    net_pct: float


class ExplorerListResponse(BaseModel):
    """All strategy-versions, lean, for the selector dropdowns."""

    versions: list[ExplorerVersion]
    venues: list[str]
    assets: list[str]


class ExplorerDetailResponse(BaseModel):
    """Full explorer data for one (version, venue, asset) combination.

    `equity_curve` is built from stored backtests + trades — NEVER re-run.
    If no data is available for a field, that field is None and the UI shows
    "not available" rather than a fabricated number.
    `available` flags whether any data at all was found for this version.
    """

    version_id: str
    name: str
    spec: dict[str, Any]
    available: bool
    equity_curve: list[ExplorerPoint]   # empty when no trades recorded
    trades: list[ExplorerTrade]          # empty when no fills
    stats: ExplorerStats
