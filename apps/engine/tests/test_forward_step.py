# The FORWARD-TEST EXECUTOR (orchestrator/forward_step.py): a funded gate-lane track must be run by its OWN
# spec + fitted params on the latest real bars — exits on its stop / take / time-stop / signal-exit, re-entry
# when its entry signal fires — all through the ONE order path (fees + sim slippage + audit). Deploy-lane
# (documented rotation arms) are skipped: their arm modules own rotation. And the funder funds a survivor
# ONCE: a track the executor closed is never re-opened by the next funding tick (the executor owns re-entry).

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.data.market import Bar
from cosmu.knowledge.store import Store
from cosmu.master.portfolio import Portfolio
from cosmu.orchestrator.forward_step import step_tracks
from cosmu.orchestrator.loop import PricingRouter, fund_tracks_from_survivors
from cosmu.spine.venue import default_catalog

_BASE = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/fstep.sqlite3", openrouter_api_key=None))


class _PathBars:
    """Offline provider: a fixed close path per symbol (flat OHLC per bar) — deterministic, no network."""

    def __init__(self, closes_by_symbol: dict[str, list[float]]) -> None:
        self._by = closes_by_symbol

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        closes = self._by.get(symbol, [])
        bars = []
        for i, c in enumerate(closes):
            p = Decimal(str(c))
            bars.append(Bar(ts=_BASE + dt.timedelta(days=i), open=p, high=p, low=p, close=p, volume=Decimal("1000000")))
        return bars[-limit:]


def _router(closes: list[float]):
    provider = _PathBars({"BTCUSDT": closes})
    return PricingRouter(default_catalog(), crypto=provider, equity=provider), provider


def _persist_survivor(store: Store, *, params: dict, max_hold_days: int = 365, signal_exit_floor: float | None = None) -> str:
    """A gate-passed forward-test survivor with a REAL evaluable spec (ret_Nd momentum, fitted sl/tp), the exact
    rows the funder reads and the executor manages."""
    now = "2024-01-01T00:00:00Z"
    exits: dict = {"stop_loss": {"param": "sl"}, "take_profit": {"param": "tp"}, "signal_exits": []}
    if signal_exit_floor is not None:
        exits["signal_exits"] = [
            {"feature": {"name": "ret_Nd", "lookback": 3}, "op": "lt", "threshold": {"param": "exit_floor"}}
        ]
    strategy_id = store.insert("strategies", {"name": "FwdStep", "thesis": "t", "origin": "finder", "created_at": now})
    version_id = store.insert(
        "strategy_versions",
        {
            "strategy_id": strategy_id,
            "parent_id": None,
            "spec": {
                "name": "FwdStep",
                "rationale": "r",
                "lane": "gate",
                "universe": {"venues": ["binance"], "asset_classes": ["crypto"], "min_instruments": 1},
                "horizon": {"bar_size": "1d", "min_hold_days": 1, "max_hold_days": max_hold_days},
                "entry": [{"feature": {"name": "ret_Nd", "lookback": 3}, "op": "gt", "threshold": {"param": "mom"}}],
                "exit": exits,
                "risk": {"max_concurrent_positions": 1, "max_position_pct": 1.0, "conviction": 0.5},
                "param_space": {},
                "direction": 1,
            },
            "generated_code": "# test", "code_hash": "hash-fwdstep", "params": params,
            "mutation_operator": None, "mutation_rationale": None, "origin": "finder",
            "status": "forward_test", "created_at": now, "killed_at": None, "kill_reason": None,
        },
    )
    store.insert(
        "tracks",
        {"strategy_version_id": version_id, "starting_capital": "1000", "equity": "1000",
         "return_pct": "0", "updated_at": now},
    )
    store.insert(
        "backtests",
        {"strategy_version_id": version_id, "kind": "screen", "oos_return": "0.2", "sharpe": "1.5",
         "sortino": "1.5", "deflated_sharpe": "1.5", "max_dd": "0.1", "win_rate": "0.6", "num_trades": 30,
         "pbo": "0.0", "trials_counted": 1, "regime_label": "mixed", "folds_positive": 5,
         "passed_gates": 1, "holdout_passed": 1, "created_at": now},
    )
    return version_id


def _fund(store: Store, *, entry_price: float = 30000.0) -> None:
    router, _ = _router([entry_price] * 30)
    funding = fund_tracks_from_survivors(store, router=router)
    assert funding.funded == 1


def _held_qty(store: Store, vid: str) -> Decimal:
    row = store.row("SELECT qty FROM positions WHERE strategy_version_id = ?", (vid,))
    return Decimal(str(row["qty"])) if row else Decimal("0")


def test_stop_loss_exit_closes_through_the_order_path(tmp_path):
    store = _store(tmp_path)
    vid = _persist_survivor(store, params={"mom": -1.0, "sl": 0.05, "tp": 0.50})
    _fund(store, entry_price=30000.0)
    assert _held_qty(store, vid) > 0

    # Price path drops 7% below the 30000 basis — beyond the fitted 5% stop.
    router, _ = _router([30000.0] * 25 + [27900.0])
    report = step_tracks(store, router=router)

    assert report.managed == 1 and report.closed == 1
    assert report.exits[0]["reason"] == "stop_loss"
    assert _held_qty(store, vid) == 0
    sell = store.row("SELECT price, fee, is_paper FROM executions WHERE side = 'sell' AND strategy_version_id = ?", (vid,))
    assert sell is not None and int(sell["is_paper"]) == 1
    # The close paid sim slippage: filled BELOW the 27900 mark (adverse side), with a real fee.
    assert Decimal(str(sell["price"])) < Decimal("27900")
    assert Decimal(str(sell["fee"])) > 0
    # Realized P&L is booked NET of costs — a ~7% drop on ~$1000 must show a real loss.
    pos = store.row("SELECT realized_pnl FROM positions WHERE strategy_version_id = ?", (vid,))
    assert Decimal(str(pos["realized_pnl"])) < Decimal("-50")
    assert store.row("SELECT id FROM events WHERE kind = 'forward_exit'") is not None


def test_take_profit_exit_fires(tmp_path):
    store = _store(tmp_path)
    vid = _persist_survivor(store, params={"mom": -1.0, "sl": 0.50, "tp": 0.10})
    _fund(store, entry_price=30000.0)

    router, _ = _router([30000.0] * 25 + [33500.0])  # +11.7% > the fitted 10% take
    report = step_tracks(store, router=router)

    assert report.closed == 1 and report.exits[0]["reason"] == "take_profit"
    assert _held_qty(store, vid) == 0
    pos = store.row("SELECT realized_pnl FROM positions WHERE strategy_version_id = ?", (vid,))
    assert Decimal(str(pos["realized_pnl"])) > Decimal("50")  # a real net-of-cost win


def test_signal_exit_fires_when_condition_true(tmp_path):
    store = _store(tmp_path)
    vid = _persist_survivor(
        store, params={"mom": -1.0, "sl": 0.50, "tp": 0.50, "exit_floor": 100.0}, signal_exit_floor=100.0
    )
    _fund(store, entry_price=30000.0)

    # Flat path — brackets can't fire; the signal exit (ret_Nd < 100, always true) must close it.
    router, _ = _router([30000.0] * 26)
    report = step_tracks(store, router=router)

    assert report.closed == 1 and report.exits[0]["reason"] == "signal_exit"
    assert _held_qty(store, vid) == 0


def test_time_stop_closes_after_max_hold_days(tmp_path):
    store = _store(tmp_path)
    vid = _persist_survivor(store, params={"mom": -1.0, "sl": 0.50, "tp": 0.50}, max_hold_days=10)
    _fund(store, entry_price=30000.0)

    router, _ = _router([30000.0] * 26)  # flat — only the clock can close it
    late = dt.datetime.now(tz=dt.UTC) + dt.timedelta(days=11)
    report = step_tracks(store, router=router, now=late)

    assert report.closed == 1 and report.exits[0]["reason"] == "time_stop"
    assert _held_qty(store, vid) == 0


def test_holds_when_no_exit_rule_fires(tmp_path):
    store = _store(tmp_path)
    vid = _persist_survivor(store, params={"mom": -1.0, "sl": 0.50, "tp": 0.50})
    _fund(store, entry_price=30000.0)

    router, _ = _router([30000.0] * 25 + [30300.0])  # +1%: inside every bracket, no signal exit
    report = step_tracks(store, router=router)

    assert report.managed == 1 and report.closed == 0
    assert _held_qty(store, vid) > 0
    assert store.row("SELECT id FROM executions WHERE side = 'sell'") is None


def test_flat_track_reenters_on_its_own_entry_signal(tmp_path):
    store = _store(tmp_path)
    vid = _persist_survivor(store, params={"mom": -1.0, "sl": 0.50, "tp": 0.10})
    _fund(store, entry_price=30000.0)
    router, _ = _router([30000.0] * 25 + [33500.0])
    assert step_tracks(store, router=router).closed == 1  # take-profit closes it

    # Next tick: flat track + entry signal true (ret_Nd > -1 always) → re-enters through the order path.
    router2, _ = _router([33500.0] * 26)
    report = step_tracks(store, router=router2)

    assert report.opened == 1
    assert _held_qty(store, vid) > 0
    buys = store.rows("SELECT id FROM executions WHERE side = 'buy' AND strategy_version_id = ?", (vid,))
    assert len(buys) == 2  # the original funding + the executor's re-entry
    assert store.row("SELECT id FROM events WHERE kind = 'forward_entry'") is not None


def test_flat_track_stays_flat_when_entry_signal_false(tmp_path):
    store = _store(tmp_path)
    vid = _persist_survivor(store, params={"mom": 100.0, "sl": 0.50, "tp": 0.10})  # entry needs ret > 100 (never)
    _fund(store, entry_price=30000.0)
    router, _ = _router([30000.0] * 25 + [33500.0])
    assert step_tracks(store, router=router).closed == 1

    report = step_tracks(store, router=router)

    assert report.opened == 0
    assert _held_qty(store, vid) == 0


def test_funder_never_reopens_an_executor_closed_track(tmp_path):
    """REGRESSION: funding is ONCE per survivor. After the executor closes a track by its own rules, the next
    funding tick must NOT overwrite that verdict with a fresh static long — the executor owns re-entry."""
    store = _store(tmp_path)
    vid = _persist_survivor(store, params={"mom": 100.0, "sl": 0.50, "tp": 0.10})
    _fund(store, entry_price=30000.0)
    router, _ = _router([30000.0] * 25 + [33500.0])
    assert step_tracks(store, router=router).closed == 1
    assert _held_qty(store, vid) == 0

    refund_router, _ = _router([33500.0] * 30)
    funding = fund_tracks_from_survivors(store, router=refund_router)

    assert funding.funded == 0
    assert _held_qty(store, vid) == 0


def test_deploy_lane_tracks_are_skipped(tmp_path):
    """A documented rotation arm (lane='deploy', e.g. GEM) is managed by its arm module — the executor must
    not impose gate-lane mechanics (its monthly rotation would look like a time-stop violation)."""
    store = _store(tmp_path)
    now = "2024-01-01T00:00:00Z"
    strategy_id = store.insert("strategies", {"name": "GEMish", "thesis": "t", "origin": "documented", "created_at": now})
    vid = store.insert(
        "strategy_versions",
        {
            "strategy_id": strategy_id, "parent_id": None,
            "spec": {
                "name": "GEMish", "rationale": "r", "lane": "deploy",
                "universe": {"venues": ["ibkr"], "asset_classes": ["equity"], "min_instruments": 1},
                "horizon": {"bar_size": "1d", "min_hold_days": 21, "max_hold_days": 31},
                "entry": [{"feature": {"name": "xsec_momentum_rank"}, "op": "gte", "threshold": {"param": "rank_top"}}],
                "exit": {"stop_loss": {"param": "sl"}, "take_profit": {"param": "tp"}, "signal_exits": []},
                "risk": {"max_concurrent_positions": 1, "max_position_pct": 1.0, "conviction": 0.5},
                "param_space": {}, "direction": 1,
            },
            "generated_code": "#", "code_hash": "hash-gemish", "params": {},
            "mutation_operator": None, "mutation_rationale": None, "origin": "documented",
            "status": "forward_test", "created_at": now, "killed_at": None, "kill_reason": None,
        },
    )
    pf = Portfolio(store, bankroll=Decimal("100000"))
    pf.apply_fill(instrument_id="spy-ibkr", symbol="SPY", venue="sim", side=1, qty=Decimal("2"),
                  price=Decimal("400"), fee=Decimal("0.5"), strategy_version_id=vid)

    router, _ = _router([400.0] * 40)
    report = step_tracks(store, router=router)

    assert report.skipped_deploy == 1 and report.managed == 0
    assert _held_qty(store, vid) == Decimal("2")  # untouched


def test_closed_track_keeps_realized_pnl_in_equity_and_trajectory(tmp_path):
    """REGRESSION (latent until exits existed): mark_to_market read realized P&L off OPEN positions only, so
    the moment the executor closed a position its realized loss VANISHED from aggregate equity and the track's
    trajectory froze at the pre-close mark. A closed trade's P&L must stay booked: aggregate equity = bankroll
    + realized, the track snapshot = starting_capital + realized, and tracks.return_pct shows the honest loss."""
    from cosmu.orchestrator.loop import mark_tracks

    store = _store(tmp_path)
    vid = _persist_survivor(store, params={"mom": 100.0, "sl": 0.05, "tp": 0.50})  # entry never re-fires
    _fund(store, entry_price=30000.0)
    router, _ = _router([30000.0] * 25 + [27900.0])  # -7% → beyond the fitted 5% stop
    assert step_tracks(store, router=router).closed == 1

    snap = mark_tracks(store, router=router)

    realized = Decimal(str(store.row(
        "SELECT realized_pnl FROM positions WHERE strategy_version_id = ?", (vid,))["realized_pnl"]))
    assert realized < Decimal("-50")
    assert abs(float(snap["equity"]) - (float(store.settings.sim_bankroll) + float(realized))) < 0.05
    tsnap = store.row(
        "SELECT equity FROM portfolio_snapshots WHERE scope='track' AND ref_id=? ORDER BY ts DESC LIMIT 1", (vid,))
    assert abs(float(tsnap["equity"]) - (1000.0 + float(realized))) < 0.05
    tr = store.row("SELECT return_pct FROM tracks WHERE strategy_version_id = ?", (vid,))
    assert float(tr["return_pct"]) < 0


def test_killed_version_position_is_liquidated(tmp_path):
    """A version killed AFTER funding (FDR demotion, graveyard) must not keep a marching position — the
    executor liquidates it at the next mark instead of letting a dead strategy accrue P&L forever."""
    store = _store(tmp_path)
    vid = _persist_survivor(store, params={"mom": -1.0, "sl": 0.50, "tp": 0.50})
    _fund(store, entry_price=30000.0)
    store.rows("UPDATE strategy_versions SET status='killed', kill_reason='fdr' WHERE id = ?", (vid,))

    router, _ = _router([30000.0] * 26)
    report = step_tracks(store, router=router)

    assert report.closed == 1 and report.exits[0]["reason"] == "version_killed"
    assert _held_qty(store, vid) == 0
    # And it never re-enters: the version is dead, not flat-and-waiting.
    assert step_tracks(store, router=router).opened == 0


def test_drift_defund_closes_the_held_position_and_blocks_reentry(tmp_path, monkeypatch):
    """master/drift's verdict has teeth now: a defunded HELD track closes this tick (reason drift_defund),
    and a defunded FLAT track is not re-entered by its own signal."""
    from types import SimpleNamespace

    import cosmu.orchestrator.forward_step as fs

    store = _store(tmp_path)
    vid = _persist_survivor(store, params={"mom": -1.0, "sl": 0.50, "tp": 0.50})  # entry always true
    _fund(store, entry_price=30000.0)
    monkeypatch.setattr(
        fs, "monitor_drift", lambda s, ids: [SimpleNamespace(ref_id=v, defund=True) for v in ids]
    )

    router, _ = _router([30000.0] * 26)
    report = step_tracks(store, router=router)

    assert report.closed == 1 and report.exits[0]["reason"] == "drift_defund"
    assert _held_qty(store, vid) == 0
    # Entry signal is always-true (mom=-1), but the defund verdict blocks re-entry.
    assert step_tracks(store, router=router).opened == 0
    assert _held_qty(store, vid) == 0
