# intent: aggregate Overview read-out; inputs: none; outputs: OverviewResponse; invariants: pure read-out, no pooled wallet.

from __future__ import annotations

from fastapi import APIRouter

from cosmu.adapters.exec.binance import resolve_mode
from cosmu.api._shared import _portfolio, settings, store
from cosmu.api.models import CostSlice, OverviewResponse, PortfolioSummaryResponse, Point

router = APIRouter()


@router.get("/overview", response_model=OverviewResponse)
def overview() -> OverviewResponse:
    """The aggregate read-out for the Overview surface — the Σ of all standalone paper tracks. A pure
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


@router.get("/portfolio/summary", response_model=PortfolioSummaryResponse)
def portfolio_summary() -> PortfolioSummaryResponse:
    """The live-vs-sim money split for the v18 Live dashboard + ribbon. A pure additive read-out: it writes
    nothing, touches no schema, and never sizes/routes an order (the deterministic risk gauntlet stays the sole
    enforcer). HONESTY: the live figures are reconstructed ONLY from positions whose `venue != 'sim'`; when none
    are routed live every `live_*` money figure is None so the UI renders "—", never SIM capital labelled live.
    `live_free` is BUDGET HEADROOM (global_cap − invested), NOT exchange cash; `live_equity` is None until a
    live portfolio snapshot exists (none does yet). One connection for all reads (remote-Postgres latency)."""
    with store.reading():
        equity_row = store.row("SELECT equity, pnl FROM portfolio_snapshots WHERE scope = 'aggregate' ORDER BY ts DESC LIMIT 1")
        sim_equity = float(equity_row["equity"]) if equity_row else float(settings.sim_bankroll)
        sim_pnl_net = float(equity_row["pnl"]) if equity_row else 0.0
        live_row = store.row("SELECT enabled FROM live_toggle WHERE id = 'global'")
        caps_row = store.row("SELECT max_notional FROM live_caps WHERE id = 'global'")
        live_global_cap = float(caps_row["max_notional"]) if caps_row else float(settings.live.global_live_cap)
        # The honest live discriminator: a position routed live carries a real venue id, never 'sim'.
        live_positions = [p for p in _portfolio().positions() if p.venue != "sim"]

    mode = resolve_mode(settings)
    live_mode = mode if mode in ("testnet", "live") else "sim"
    armed = bool(live_row and live_row["enabled"]) and mode != "disabled"
    has_live = bool(live_positions)
    if has_live:
        live_invested = round(sum(abs(float(p.qty)) * float(p.avg_price) for p in live_positions), 2)
        live_unrealized = round(sum(float(p.unrealized_pnl(p.avg_price)) for p in live_positions), 2)  # mark==basis → honest 0 without a fresh tick
        live_realized = round(sum(float(p.realized_pnl) for p in live_positions), 2)
        live_pnl_net = round(live_unrealized + live_realized, 2)
        live_free = round(live_global_cap - live_invested, 2)  # budget headroom, NOT exchange cash
    else:
        live_invested = live_unrealized = live_realized = live_pnl_net = live_free = None
    return PortfolioSummaryResponse(
        has_live=has_live,
        live_armed=armed,
        live_mode=live_mode,
        sim_equity=sim_equity,
        sim_pnl_net=sim_pnl_net,
        live_equity=None,  # no live portfolio snapshot is persisted yet — honest None, never the SIM equity
        live_invested=live_invested,
        live_free=live_free,
        live_pnl_net=live_pnl_net,
        live_unrealized=live_unrealized,
        live_realized=live_realized,
        live_global_cap=live_global_cap,
        positions_count_live=len(live_positions),
    )
