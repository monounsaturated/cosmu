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


class CellCurvePoint(BaseModel):
    """A single (ts, net_value) point of a PER-CELL net-of-fee backtest equity curve."""

    ts: str
    net: float


class CellCurveResponse(BaseModel):
    """The PER-CELL (algo × symbol × venue) net-of-fee backtest equity curve — the cumulated per-bar net equity
    the cell's metrics score on, NEVER the pooled basket. Served from the curve persisted at screen time
    (backtest_symbols.equity_curve_json); when that is absent (a cell screened before the column shipped — the
    bulk of existing rows), it is RECOMPUTED on the fly from the version's spec/params over the cell's real bars
    and written back so the next request is cached. The strat sheet's Backtest tab requests this for the focused
    cell when there are no fills to draw a curve from. `available` is False (points empty) only when the cell
    truly has no curve — bars unavailable (offline), an unparseable spec, or a degenerate cell that never traded —
    an honest empty state, never a fabricated curve."""

    version_id: str
    symbol: str
    venue: str | None
    available: bool
    points: list[CellCurvePoint]


class CostBasisCell(BaseModel):
    """A strategy's net performance under ONE cost basis — either the friction-free baseline ("No fees") or a
    specific venue's REAL fee + market depth. This is what the fee-basis selector swaps between."""

    basis: str                 # "none" (no-fee baseline) | a venue id, e.g. "binance"
    label: str                 # display label, e.g. "No fees" / "Binance"
    venue_id: str | None       # None for the no-fee baseline; the venue id otherwise
    fee_bps: float             # per-side taker fee applied (0 for the no-fee basis)
    slippage_bps: float        # half-spread applied (the venue's market depth)
    impact_bps: float          # size-aware impact coefficient applied
    net_return_pct: float      # net return under this basis (%)
    cost_ratio: float          # fraction of the friction-free edge surviving this basis, 0..1
    num_trades: int
    holds: bool                # the edge stays net-positive under this basis


class CostBasisResponse(BaseModel):
    """Per-basis performance for the fee-basis selector (None / venue-1 / venue-2 / …), RECOMPUTED on demand
    from the spec + fitted params on real cached bars — a self-consistent cross-basis comparison (the relative
    ordering across bases is the point; absolute level may differ from the stored single-venue backtest).

    `available` is False (with `reason`) when the market can't be loaded (offline, or an asset class whose
    recompute isn't wired yet) — an honest "—", never a fabricated number. The "none" cell is the gross
    (friction-free) baseline; `gross_return_pct` mirrors it for convenience."""

    version_id: str
    name: str
    available: bool
    reason: str | None                 # why unavailable, when available is False
    gross_return_pct: float | None     # the friction-free baseline edge (%) — equals the "none" cell's net
    cells: list[CostBasisCell]
