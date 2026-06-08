# intent: aggregate Overview read-out; inputs: none; outputs: OverviewResponse; invariants: pure read-out, no pooled wallet.

from __future__ import annotations

from fastapi import APIRouter

from cosmu.api._shared import settings, store
from cosmu.api.models import CostSlice, OverviewResponse, Point

router = APIRouter()


@router.get("/overview", response_model=OverviewResponse)
def overview() -> OverviewResponse:
    """The aggregate read-out for the Overview surface — the Σ of all standalone forward-test tracks. A pure
    read-out: there is NO pooled wallet and no cross-track allocation (each survivor proves on its own track).

    All four reads share ONE autocommit Postgres connection (store.reading()) — without this each store.row()
    opens + closes a separate psycopg2 connection (~1s RTT × 5 ≈ 5–7s, over the 5s frontend budget)."""
    with store.reading():
        snapshots = store.rows("SELECT ts, equity, pnl FROM portfolio_snapshots WHERE scope = 'aggregate' ORDER BY ts ASC LIMIT 120")
        curve = [Point(ts=row["ts"], value=float(row["equity"])) for row in snapshots]
        pnl_net = float(snapshots[-1]["pnl"]) if snapshots else 0.0
        # equity: read the latest aggregate snapshot directly (same connection) rather than constructing a
        # Portfolio object that would open a second connection for the same query.
        equity_row = store.row("SELECT equity FROM portfolio_snapshots WHERE scope = 'aggregate' ORDER BY ts DESC LIMIT 1")
        equity = float(equity_row["equity"]) if equity_row else float(settings.sim_bankroll)
        cost_rows = store.rows("SELECT category, SUM(CAST(amount AS REAL)) AS amount FROM costs GROUP BY category")
        costs = [CostSlice(category=r["category"], amount=float(r["amount"] or 0)) for r in cost_rows]
        live_row = store.row("SELECT enabled FROM live_toggle WHERE id = 'global'")
    return OverviewResponse(
        equity_curve=curve,
        pnl_net=pnl_net,
        costs=costs,
        live_enabled=bool(live_row and live_row["enabled"]),
        opex_vs_alpha=round(sum(c.amount for c in costs) / equity, 6) if equity else 0.0,
    )
