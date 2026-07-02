# intent: aggregate Overview read-out; inputs: none; outputs: OverviewResponse; invariants: pure read-out, no pooled wallet.

from __future__ import annotations

from fastapi import APIRouter

from cosmu.adapters.exec.binance import resolve_mode
from cosmu.api._shared import _portfolio, honest_track_equity_series, settings, store
from cosmu.api.models import CostSlice, OverviewResponse, Point, PortfolioSummaryResponse
from cosmu.knowledge.lifecycle_status import FORWARD_STATUSES, sql_in_list

router = APIRouter()


def _honest_aggregate_curve(allocated: float, limit: int = 120) -> list[tuple[str, float]]:
    """The honest aggregate paper-equity series for the Overview hero + the ribbon — the two readers of the
    `scope='aggregate'` snapshots. Each point is rebuilt as `allocated + pnl` (NO pooled wallet; the stored
    `equity` column is a bankroll artifact we ignore), then a FUNDER seed-collapse tick — where already-held
    cells re-marked to cost basis drop the aggregate `pnl` to ~0 so `value ≈ allocated`, the seed baseline —
    is carried to the last real mark by `honest_track_equity_series` (seed = allocated). This is the SAME rule
    the strategy sheet + leaderboard already apply; /overview was the third, un-fixed reader (the raw series
    drew a sawtooth that snapped back to the allocated floor). Robust path if a cohort ever accrues realized
    P&L at collapse points (so `value != allocated` to the cent): sum the per-track honest series aligned by
    `ts` (each track detects its own $1k seed) — see `strategies.py::_forward_track_series`."""
    rows = list(reversed(store.rows(
        f"SELECT ts, pnl FROM portfolio_snapshots WHERE scope = 'aggregate' ORDER BY ts DESC LIMIT {int(limit)}"
    )))
    raw = [{"ts": r["ts"], "equity": allocated + float(r["pnl"])} for r in rows]
    return honest_track_equity_series(raw, allocated)


@router.get("/overview", response_model=OverviewResponse)
def overview() -> OverviewResponse:
    """The aggregate read-out for the Overview surface — the Σ of all standalone paper tracks. A pure
    read-out: there is NO pooled wallet and no cross-track allocation (each survivor proves on its own track).

    All four reads share ONE autocommit Postgres connection (store.reading()) — without this each store.row()
    opens + closes a separate psycopg2 connection (~1s RTT × 5 ≈ 5–7s, over the 5s frontend budget)."""
    with store.reading():
        # NO POOLED WALLET (locked invariant): the honest Paper equity is the Σ of per-strategy ALLOCATED capital
        # (each track funds itself with sim_track_capital, ~$1k), NOT the $100k sim_bankroll. The stored aggregate
        # snapshot's `equity` column = bankroll + P&L (a pooled-wallet artifact), so we IGNORE it and rebuild the
        # read-out as `allocated + the snapshot's bankroll-independent pnl`. The hero then shows the real allocated
        # book (e.g. ~$9k across 9 tracks) and its P&L, never the bankroll. Killed tracks drop out of `allocated`
        # (status != paper) but their realized P&L stays in `pnl` — losses are remembered, capital isn't double-counted.
        alloc_row = store.row(
            "SELECT COALESCE(SUM(CAST(t.starting_capital AS REAL)), 0) AS allocated "
            "FROM tracks t JOIN strategy_versions sv ON sv.id = t.strategy_version_id "
            f"WHERE sv.status IN {sql_in_list(FORWARD_STATUSES)}"
        )
        allocated = float(alloc_row["allocated"]) if alloc_row and alloc_row["allocated"] is not None else 0.0
        # HONEST hero curve (the sawtooth fix): funder seed-collapse ticks are carried to the last real mark, and
        # the headline (`pnl_net`/`equity`) is derived from the last HONEST point — not the raw last snapshot,
        # which could itself be a funder tick that flickers the headline to the collapsed value. Oldest→newest.
        honest = _honest_aggregate_curve(allocated)
        curve = [Point(ts=ts, value=val) for ts, val in honest]
        pnl_net = (honest[-1][1] - allocated) if honest else 0.0
        equity = allocated + pnl_net  # honest book = allocated capital + P&L; never the bankroll
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
        # sim_equity = Σ per-strategy ALLOCATED capital + P&L (NO pooled wallet; never the sim_bankroll). Mirrors
        # the /overview read-out so the ribbon and the Paper hero agree on the real allocated book, not $100k.
        # sim_pnl_net comes from the HONEST aggregate series (last real mark), NOT the raw latest snapshot — a
        # funder seed-collapse tick as the newest row would otherwise flicker the ribbon's SIM P&L to ~0.
        alloc_row = store.row(
            "SELECT COALESCE(SUM(CAST(t.starting_capital AS REAL)), 0) AS allocated "
            "FROM tracks t JOIN strategy_versions sv ON sv.id = t.strategy_version_id "
            f"WHERE sv.status IN {sql_in_list(FORWARD_STATUSES)}"
        )
        allocated = float(alloc_row["allocated"]) if alloc_row and alloc_row["allocated"] is not None else 0.0
        honest = _honest_aggregate_curve(allocated)
        sim_pnl_net = (honest[-1][1] - allocated) if honest else 0.0
        sim_equity = allocated + sim_pnl_net
        live_row = store.row("SELECT enabled FROM live_toggle WHERE id = 'global'")
        caps_row = store.row("SELECT max_notional FROM live_caps WHERE id = 'global'")
        live_global_cap = float(caps_row["max_notional"]) if caps_row else float(settings.live.global_live_cap)
        # The honest live discriminator: a position is LIVE MONEY only when its owning Version is in the
        # 'live' lifecycle stage. Venue alone is NOT sufficient — paper/sim tracks book under their INTENDED
        # venue (the equity TAA cohort books under 'ibkr' so the spec carries where it WILL trade once
        # promoted), yet those legs are simulated until status flips to 'live'. Filtering on `venue != 'sim'`
        # alone counted the 33 paper ETF legs as live; AND-ing the lifecycle status (currently 0 live) is truth.
        live_sv_ids = {r["id"] for r in store.rows("SELECT id FROM strategy_versions WHERE status = 'live'")}
        live_positions = [
            p for p in _portfolio().positions() if p.venue != "sim" and p.strategy_version_id in live_sv_ids
        ]

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
