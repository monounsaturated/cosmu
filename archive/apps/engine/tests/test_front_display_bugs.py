# Two FRONT-DISPLAY bugs from the 2026-06-26 coherence audit (docs/reports/front-data-audit-2026-06-26.md).
# Neither moves money or changes the Gate — they only fix what the front SHOWS.
#
#  BUG 1 — the /overview hero equity curve was pinned to the OLDEST 120 aggregate snapshots
#          (`ORDER BY ts ASC LIMIT 120`), so it froze on the first ~5 days forever. The fix returns the
#          MOST-RECENT 120 in chronological order, so the curve (and pnl_net/equity, read off the last point)
#          advances with fresh snapshots.
#  BUG 2 — the documented TAA rebalance arms wrote only `positions` (via apply_fill), never an `executions`
#          row, so the trade-count + blotter froze at the 06-14 backfill even after a real rotation. The fix
#          has apply_fill(record_execution=True) append ONE idempotent paper execution per real rebalance fill
#          (advances on a genuine rebalance, no double-count on a re-run, money path untouched).

from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.master.portfolio import Portfolio


def _store(tmp_path, name: str) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3", openrouter_api_key=None))


# --- BUG 1: /overview hero curve returns the MOST-RECENT window, not the oldest ---------------------


def _seed_aggregate_snapshots(store: Store, n: int) -> None:
    """Write `n` aggregate snapshots, pnl = index (0..n-1) so the newest snapshot has the largest pnl. Timestamps
    are real ISO-8601 strings minutes apart so lexical and chronological order agree (the column is stored text)."""
    base = datetime(2026, 4, 1, tzinfo=UTC)
    for i in range(n):
        ts = (base + timedelta(minutes=i)).isoformat()
        store.insert("portfolio_snapshots", {
            "scope": "aggregate", "ref_id": "global", "ts": ts,
            "equity": str(100000 + i), "cash": "0", "positions_value": "0",
            "pnl": str(i), "drawdown": "0",
        })


def test_overview_curve_returns_most_recent_window_not_oldest(tmp_path, monkeypatch):
    # 200 aggregate snapshots: the OLD bug returned days 0..119 (curve frozen, last pnl=119); the fix returns
    # the most recent 120 (days 80..199), chronological, so the LAST point is the freshest (pnl=199).
    store = _store(tmp_path, "ov")
    _seed_aggregate_snapshots(store, 200)

    overview_mod = importlib.import_module("cosmu.api.routers.overview")
    monkeypatch.setattr(overview_mod, "store", store)

    resp = overview_mod.overview()
    curve = resp.equity_curve

    assert len(curve) == 120, "hero curve is the most-recent 120-point window"
    # chronological order (oldest→newest) for the chart: ts strictly increasing
    ts_list = [p.ts for p in curve]
    assert ts_list == sorted(ts_list)
    # the LAST point is the FRESHEST snapshot (pnl=199), NOT the stale day-119 the old ASC LIMIT pinned to.
    # value = allocated (0 here, no funded tracks) + pnl.
    assert curve[-1].value == 199.0
    assert curve[0].value == 80.0  # window starts at day 80, not day 0
    assert resp.pnl_net == 199.0  # pnl_net reads the latest point, no longer the stale 120th-oldest


def test_overview_curve_handles_fewer_than_120_snapshots(tmp_path, monkeypatch):
    # Fewer than the window: still chronological, last point freshest, no crash.
    store = _store(tmp_path, "ov_small")
    _seed_aggregate_snapshots(store, 5)
    overview_mod = importlib.import_module("cosmu.api.routers.overview")
    monkeypatch.setattr(overview_mod, "store", store)

    curve = overview_mod.overview().equity_curve
    assert [p.value for p in curve] == [0.0, 1.0, 2.0, 3.0, 4.0]  # oldest→newest, all 5


# --- BUG 2: a real rebalance fill writes ONE idempotent paper execution -----------------------------


def test_apply_fill_default_does_not_write_executions(tmp_path):
    # DEFAULT (record_execution omitted) writes NOTHING to executions — the backtest/replay path must never
    # pollute the live ledger. Money path (positions) is booked as before.
    store = _store(tmp_path, "ex_default")
    pf = Portfolio(store, bankroll=Decimal("100000"))
    pf.apply_fill(instrument_id="spy-ibkr", symbol="SPY", venue="ibkr", side=1,
                  qty=Decimal("2.5"), price=Decimal("400"), fee=Decimal("0.2"), strategy_version_id="v1")
    assert store.row("SELECT 1 FROM executions LIMIT 1") is None  # no ledger row
    assert pf.position("spy-ibkr", "ibkr", strategy_version_id="v1").qty == Decimal("2.5")  # position still booked


def test_rebalance_fill_writes_one_paper_execution(tmp_path):
    store = _store(tmp_path, "ex_one")
    pf = Portfolio(store, bankroll=Decimal("100000"))
    pf.apply_fill(instrument_id="spy-ibkr", symbol="SPY", venue="ibkr", side=1,
                  qty=Decimal("2.5"), price=Decimal("400"), fee=Decimal("0.2"),
                  strategy_version_id="v1", record_execution=True)

    rows = store.rows("SELECT side, qty, is_paper, instrument_id, venue_id FROM executions")
    assert len(rows) == 1
    r = rows[0]
    assert r["side"] == "buy" and Decimal(str(r["qty"])) == Decimal("2.5")
    assert int(r["is_paper"]) == 1  # paper-only by default
    assert r["instrument_id"] == "spy-ibkr" and r["venue_id"] == "ibkr"
    # the FK parent run exists and is a paper run
    run = store.row("SELECT mode FROM runs WHERE id = (SELECT run_id FROM executions LIMIT 1)")
    assert run is not None and run["mode"] == "paper"


def test_rebalance_execution_is_idempotent_no_double_count(tmp_path):
    # Re-running the SAME tick (same leg, qty, price, day) must NOT add a second row — the trade-count can't
    # inflate just because the 4-hourly cron re-touches a still-held leg.
    store = _store(tmp_path, "ex_idem")
    pf = Portfolio(store, bankroll=Decimal("100000"))
    for _ in range(3):
        pf.apply_fill(instrument_id="spy-ibkr", symbol="SPY", venue="ibkr", side=1,
                      qty=Decimal("2.5"), price=Decimal("400"), fee=Decimal("0.2"),
                      strategy_version_id="v1", record_execution=True)
    assert store.row("SELECT COUNT(*) AS n FROM executions")["n"] == 1


def test_genuine_rebalance_advances_the_count(tmp_path):
    # A REAL rotation (sell the old leg, buy a NEW leg at a new qty/price) writes DISTINCT execution rows — the
    # trade-count ADVANCES, which is the whole point of the fix.
    store = _store(tmp_path, "ex_advance")
    pf = Portfolio(store, bankroll=Decimal("100000"))
    pf.apply_fill(instrument_id="spy-ibkr", symbol="SPY", venue="ibkr", side=1, qty=Decimal("2.5"),
                  price=Decimal("400"), fee=Decimal("0.2"), strategy_version_id="v1", record_execution=True)
    # rotation: sell SPY, buy AGG
    pf.apply_fill(instrument_id="spy-ibkr", symbol="SPY", venue="ibkr", side=-1, qty=Decimal("2.5"),
                  price=Decimal("420"), fee=Decimal("0.2"), strategy_version_id="v1", record_execution=True)
    pf.apply_fill(instrument_id="agg-ibkr", symbol="AGG", venue="ibkr", side=1, qty=Decimal("9"),
                  price=Decimal("110"), fee=Decimal("0.2"), strategy_version_id="v1", record_execution=True)

    sides = [r["side"] for r in store.rows("SELECT side FROM executions ORDER BY ts")]
    assert sides.count("buy") == 2 and sides.count("sell") == 1  # 3 distinct trades

    # the new fills make the version read as "has paper fills" (the front's Paper gate)
    from cosmu.orchestrator.loop import _has_paper_fills
    assert _has_paper_fills(store, "v1") is True


def test_ledger_write_never_breaks_the_money_path(tmp_path):
    # Even if the executions write were to fail, the position MUST still be booked (best-effort, isolated).
    # Here a missing strategy_version_id is fine; assert the position is correct regardless of ledger state.
    store = _store(tmp_path, "ex_safe")
    pf = Portfolio(store, bankroll=Decimal("100000"))
    view = pf.apply_fill(instrument_id="x-ibkr", symbol="X", venue="ibkr", side=1, qty=Decimal("1"),
                         price=Decimal("10"), fee=Decimal("0"), strategy_version_id=None,
                         record_execution=True)
    assert view.qty == Decimal("1")  # money path booked no matter what the ledger did
