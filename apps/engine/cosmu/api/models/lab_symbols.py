# intent: the per-symbol Lab contract — one row per (strategy × symbol × venue) backtest cell, the granular truth
# the pooled leaderboard averages away. The verdict is the HONEST cross-symbol label (robust/fragile/thin/negative)
# so the UI can sort by outlier WITHOUT celebrating a lone best-of-N winner. Visibility only; never a funding signal.

from __future__ import annotations

from pydantic import BaseModel


class LabSymbolRow(BaseModel):
    strategy_version_id: str
    strategy_name: str
    strategy_id: str              # the ALGO id (parent of every version) — the key the comparison table groups on
    kind: str                     # 'quant' | 'llm' — the strategy MODEL that produced this cell
    status: str                   # the version's lifecycle status (screened/paper/live/killed/…) — advisory context
    symbol: str
    venue_id: str | None          # the fee axis (the same edge costs differently per venue)
    return_pct: float             # standalone validation TOTAL return over the OOS window on THIS symbol+venue (NEVER pooled)
    return_pct_annualized: float | None = None  # CAGR of return_pct over oos_window_days — the cross-combo comparable
    #                                             (windows differ); NULL when the window is unknown. Fraction (0.034=+3.4%/yr).
    return_pct_annualized_lo: float | None = None  # CONSERVATIVE lower-bound on return_pct_annualized — the honest
    #                                                "≥ x%/yr" confidence floor (Sharpe-SE shrinkage; see _shared.
    #                                                annualized_return_lo). Always ≤ the point CAGR for a positive cell;
    #                                                NULL when too thin/window unknown to estimate. Display-only, never a gate.
    oos_window_days: float | None = None  # the OOS window (days) return_pct covers — THIS cell's OWN validation
    #                                        window (annualizer denominator), falling back to the parent backtest's
    #                                        shared window only for legacy cells; NULL = legacy/unknown
    thin: bool = False            # this cell booked FEWER than the gate's min_trades on its own data — statistically
    #                               too thin to judge honestly. Computed engine-side against the REAL gate floor
    #                               (settings.gates.min_trades), surfaced so the UI can mute/flag the cell. Never a gate.
    sharpe: float
    max_drawdown: float
    trades: int
    verdict: str | None           # robust | fragile | thin | negative — the honest cross-symbol label (NULL = legacy)
    pooled_return_pct: float | None  # ADVISORY ONLY: the parent backtest's pooled OOS return (the number the old
    #                                  leaderboard headlined). Surfaced dim/secondary so the granular cell stays the
    #                                  truth — never averaged into a verdict, never a funding signal. NULL = legacy.
    created_at: str


class LabSymbolsResponse(BaseModel):
    rows: list[LabSymbolRow]
    symbols: list[str]            # the distinct symbols present — drives the filter chips
    venues: list[str]             # the distinct venues present — drives the filter chips
    min_trades: int               # the REAL gate trade floor (settings.gates.min_trades) a cell must clear to be
    #                               judged honestly — surfaced so the web flags `thin` cells against the live
    #                               constant instead of hardcoding 30. Mirrors LabSymbolRow.thin.


class TripletCardResponse(BaseModel):
    """The 'fiche triplet' — ONE (algo × asset × venue) backtest cell, focused. `cell` is the granular truth for the
    clicked (version, symbol, venue); None when no cell exists for that exact triplet (honest empty, never fabricated).
    `strategy_id` is the algo the comparison table groups on so the web can fetch the sibling grid + drive the
    asset/venue selector. Pure read; the pooled number rides on the cell as advisory only — never a funding signal."""

    strategy_id: str
    strategy_version_id: str
    strategy_name: str
    cell: LabSymbolRow | None
