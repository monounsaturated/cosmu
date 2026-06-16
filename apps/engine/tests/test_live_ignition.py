# LIVE IGNITION (orchestrator/paper_step.py): a status='live' track on an ARMED venue routes its orders
# through that venue's real ExecutionAdapter (live book), while everything else stays SIM. Safe by default:
# with the live toggle off / no keys, a 'live' track still paper-trades in SIM — no real order is possible.
# Tested offline with a fake active adapter (no chain/network).

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import cosmu.orchestrator.paper_step as ps
from cosmu.config.settings import Settings
from cosmu.core.interfaces import AssetClass, OrderId
from cosmu.data.market import Bar
from cosmu.knowledge.store import Store
from cosmu.orchestrator.loop import PricingRouter, fund_tracks_from_survivors, mark_tracks
from cosmu.orchestrator.paper_step import step_tracks
from cosmu.spine.venue import default_catalog

_BASE = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)


def _store(tmp_path) -> Store:
    # _env_file=None → hermetic: the "without keys" adapter test must not inherit the dev box's real venue
    # keys from .env.local (else _resolve_live_adapters resolves a live adapter and the empty-dict assert fails).
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/ignite.sqlite3", openrouter_api_key=None, _env_file=None))


class _PathBars:
    def __init__(self, closes_by_symbol):
        self._by = closes_by_symbol

    def fetch_bars(self, symbol, timeframe, *, limit):
        closes = self._by.get(symbol, [])
        bars = [
            Bar(ts=_BASE + dt.timedelta(days=i), open=Decimal(str(c)), high=Decimal(str(c)),
                low=Decimal(str(c)), close=Decimal(str(c)), volume=Decimal("1000000"))
            for i, c in enumerate(closes)
        ]
        return bars[-limit:]


def _router(closes):
    provider = _PathBars({"BTCUSDT": closes})
    return PricingRouter(default_catalog(), crypto=provider, equity=provider)


def _persist_survivor(store: Store) -> str:
    """A gate-passed crypto survivor whose entry signal is always true (mom=-1)."""
    now = "2024-01-01T00:00:00Z"
    strategy_id = store.insert("strategies", {"name": "Ignite", "thesis": "t", "origin": "finder", "created_at": now})
    vid = store.insert(
        "strategy_versions",
        {
            "strategy_id": strategy_id, "parent_id": None,
            "spec": {
                "name": "Ignite", "rationale": "r", "lane": "gate",
                "universe": {"venues": ["binance"], "asset_classes": ["crypto"], "min_instruments": 1},
                "horizon": {"bar_size": "1d", "min_hold_days": 1, "max_hold_days": 365},
                "entry": [{"feature": {"name": "ret_Nd", "lookback": 3}, "op": "gt", "threshold": {"param": "mom"}}],
                "exit": {"stop_loss": {"param": "sl"}, "take_profit": {"param": "tp"}, "signal_exits": []},
                "risk": {"max_concurrent_positions": 1, "max_position_pct": 1.0, "conviction": 0.5},
                "param_space": {}, "direction": 1,
            },
            "generated_code": "# t", "code_hash": "hash-ignite", "params": {"mom": -1.0, "sl": 0.05, "tp": 0.50},
            "mutation_operator": None, "mutation_rationale": None, "origin": "finder",
            "status": "paper", "created_at": now, "killed_at": None, "kill_reason": None,
        },
    )
    store.insert("tracks", {"strategy_version_id": vid, "starting_capital": "1000", "equity": "1000",
                            "return_pct": "0", "updated_at": now})
    store.insert("backtests", {"strategy_version_id": vid, "kind": "screen", "oos_return": "0.2", "sharpe": "1.5",
                               "sortino": "1.5", "deflated_sharpe": "1.5", "max_dd": "0.1", "win_rate": "0.6",
                               "num_trades": 30, "pbo": "0.0", "trials_counted": 1, "regime_label": "mixed",
                               "folds_positive": 5, "passed_gates": 1, "holdout_passed": 1, "created_at": now})
    # A promoted survivor is FROZEN — live entries only open on this exact config (paper_step._frozen_config_ok).
    from cosmu.master.promotion import freeze_promotion

    freeze_promotion(store, vid)
    return vid


class _FakeLiveAdapter:
    """An ACTIVE execution adapter (no keys, no network) to prove the live routing path end-to-end."""

    asset_class = AssetClass.CRYPTO

    def __init__(self, venue="binance", mode="live"):
        self.venue = venue
        self.mode = mode
        self.submitted: list = []
        self.reconcile_calls = 0

    @property
    def active(self) -> bool:
        return True

    def submit(self, order):
        self.submitted.append(order)
        return OrderId(venue=self.venue, client_order_id=order.client_order_id, venue_order_id="VEN-1")

    def cancel(self, order_id):  # pragma: no cover - not exercised here
        pass

    def positions(self):
        return []

    def fills(self, since):
        return []


def _fund_flat(store, router) -> None:
    assert fund_tracks_from_survivors(store, router=router).funded == 1


def _live_position(store, vid):
    return store.row(
        "SELECT venue, qty FROM positions WHERE strategy_version_id = ? AND CAST(qty AS REAL) != 0", (vid,)
    )


def test_live_track_on_armed_venue_routes_live(tmp_path, monkeypatch):
    store = _store(tmp_path)
    vid = _persist_survivor(store)
    router = _router([30000.0] * 25)
    _fund_flat(store, router)  # registers the track FLAT (no position yet)
    store.rows("UPDATE strategy_versions SET status='live' WHERE id = ?", (vid,))

    fake = _FakeLiveAdapter(venue="binance", mode="live")
    monkeypatch.setattr(ps, "_resolve_live_adapters", lambda s: {"binance": fake})

    report = step_tracks(store, router=router)

    assert report.opened == 1
    assert len(fake.submitted) == 1 and fake.submitted[0].side == 1  # the entry went to the REAL adapter
    pos = _live_position(store, vid)
    assert pos is not None and pos["venue"] == "live"  # booked on the LIVE book, not sim
    live_exec = store.row(
        "SELECT is_paper FROM executions WHERE side='buy' AND strategy_version_id = ?", (vid,))
    assert int(live_exec["is_paper"]) == 0  # a real (non-paper) fill
    assert store.row("SELECT id FROM events WHERE kind='order_submitted_live'") is not None


def test_live_position_exit_also_routes_live(tmp_path, monkeypatch):
    store = _store(tmp_path)
    vid = _persist_survivor(store)
    router = _router([30000.0] * 25)
    _fund_flat(store, router)
    store.rows("UPDATE strategy_versions SET status='live' WHERE id = ?", (vid,))
    fake = _FakeLiveAdapter(venue="binance", mode="live")
    monkeypatch.setattr(ps, "_resolve_live_adapters", lambda s: {"binance": fake})
    step_tracks(store, router=router)  # opens the live position
    assert _live_position(store, vid)["venue"] == "live"

    # -7% beyond the fitted 5% stop → the live position must close THROUGH the real adapter.
    drop_router = _router([30000.0] * 25 + [27900.0])
    report = step_tracks(store, router=drop_router)

    assert report.closed == 1 and report.exits[0]["reason"] == "stop_loss"
    assert len(fake.submitted) == 2 and fake.submitted[1].side == -1  # the exit routed live too
    assert _live_position(store, vid) is None  # flat on the live book


def test_unarmed_live_track_stays_sim(tmp_path):
    """SAFE DEFAULT: a status='live' track with NO armed venue (toggle off / no keys) paper-trades in SIM —
    it never routes a real order. This is the byte-identical-to-before behaviour every existing run relies on."""
    store = _store(tmp_path)
    vid = _persist_survivor(store)
    router = _router([30000.0] * 25)
    _fund_flat(store, router)
    store.rows("UPDATE strategy_versions SET status='live' WHERE id = ?", (vid,))
    # No monkeypatch: _resolve_live_adapters reads the (off) live_toggle and returns {}.

    report = step_tracks(store, router=router)

    assert report.opened == 1
    assert _live_position(store, vid)["venue"] == "sim"  # SIM book, not live
    assert store.row("SELECT id FROM events WHERE kind='order_submitted_live'") is None


def test_demoted_live_track_still_exits_its_open_live_position(tmp_path, monkeypatch):
    """A track demoted from 'live' to 'paper' while HOLDING an open live position must still manage+exit it on
    the live book (routing follows the real position, not the current status) — never orphan a real position."""
    store = _store(tmp_path)
    vid = _persist_survivor(store)
    router = _router([30000.0] * 25)
    _fund_flat(store, router)
    store.rows("UPDATE strategy_versions SET status='live' WHERE id = ?", (vid,))
    fake = _FakeLiveAdapter(venue="binance", mode="live")
    monkeypatch.setattr(ps, "_resolve_live_adapters", lambda s: {"binance": fake})
    step_tracks(store, router=router)  # opens the live position
    assert _live_position(store, vid)["venue"] == "live"

    # Demote to 'paper' while the live position is still open, then trip the stop.
    store.rows("UPDATE strategy_versions SET status='paper' WHERE id = ?", (vid,))
    drop_router = _router([30000.0] * 25 + [27900.0])
    report = step_tracks(store, router=drop_router)

    assert report.closed == 1  # the open live position is still exited (not orphaned)
    assert fake.submitted[-1].side == -1
    assert _live_position(store, vid) is None


def test_step_tracks_slow_strategy_holds_no_churn_and_marks_equity(tmp_path):
    """PHASE-1a property: a SLOW (monthly-cadence) track must OPEN once, then HOLD across many daily executor
    ticks WITHOUT churning (no re-entry / no double-fill each tick), while the paper clock keeps marking equity.
    bar_size maxes at '1d' (no monthly bar), so a monthly-rebalanced equity sleeve runs the DAILY clock — its
    'no churn' guarantee is that a held position is only re-touched on an actual exit signal, and the
    decision-bar-stamped client_order_id makes a same-bar re-tick a no-op. (Multi-asset monthly REBALANCE of a
    basket is the deploy-lane arms' job, which step_tracks skips — this proves the single-symbol hold path.)"""
    store = _store(tmp_path)
    vid = _persist_survivor(store)  # entry true while flat; stop 5% / take 50% / no signal-exit → holds when flat-priced
    flat = _router([30000.0] * 30)  # a quiet, range-bound tape: no stop/take/signal exit ever fires
    _fund_flat(store, flat)

    open_report = step_tracks(store, router=flat)
    assert open_report.opened == 1 and open_report.closed == 0  # opened exactly once
    held = _live_position(store, vid)
    assert held is not None and held["venue"] == "sim" and Decimal(str(held["qty"])) > 0

    def _n_fills() -> int:
        return store.row("SELECT COUNT(*) AS n FROM executions WHERE strategy_version_id = ?", (vid,))["n"]

    fills_after_open = _n_fills()
    assert fills_after_open == 1

    # Re-tick on the SAME bar 5×, and on fresh quiet bars 5× — must be a true no-op each time (no churn).
    for k in range(5):
        r = step_tracks(store, router=flat)
        assert r.opened == 0 and r.closed == 0, f"churned on same-bar re-tick {k}"
    for k in range(5):
        r = step_tracks(store, router=_router([30000.0] * (31 + k)))  # one more quiet bar each time
        assert r.opened == 0 and r.closed == 0, f"churned on fresh quiet bar {k}"
    assert _n_fills() == 1, "extra fills => churn"  # still a single open, position untouched
    assert Decimal(str(_live_position(store, vid)["qty"])) == Decimal(str(held["qty"]))  # qty stable

    # The paper clock marks equity for the held track across the held window (no order, marks only).
    snap = mark_tracks(store, router=flat)
    assert snap["equity"] > 0
    trow = store.row("SELECT equity FROM tracks WHERE strategy_version_id = ?", (vid,))
    assert trow is not None and Decimal(str(trow["equity"])) > 0


def test_live_venue_normalizes_paper_to_testnet():
    """The booking-label helper: a real-venue SANDBOX ('paper' on Alpaca, 'testnet' on Binance) is a LIVE book
    ('testnet'), distinct from the offline 'sim' lane — so an is_paper=0 fill never collides with the sim book.
    Regression for the Alpaca-paper bug where 'paper' fell through to 'sim' (booked is_paper=0 under 'sim')."""
    from cosmu.master.execution import _live_venue

    assert _live_venue(_FakeLiveAdapter(venue="alpaca", mode="paper")) == "testnet"
    assert _live_venue(_FakeLiveAdapter(venue="binance", mode="testnet")) == "testnet"
    assert _live_venue(_FakeLiveAdapter(venue="binance", mode="live")) == "live"
    assert _live_venue(_FakeLiveAdapter(venue="alpaca", mode="disabled")) == "sim"
    assert _live_venue(object()) == "sim"  # no .mode attr → safe default


def test_alpaca_paper_order_books_on_live_testnet_book_not_sim(tmp_path):
    """End-to-end through the ONE order path (execute_orders) with an ACTIVE Alpaca-'paper'-mode adapter:
    the live-routed entry must book is_paper=0 on the 'testnet' LIVE book (which step_tracks' held_live manages)
    — never on 'sim'. Offline (fake adapter, no network); mirrors the observed Alpaca-paper exercise."""
    from cosmu.master.execution import IntendedOrder, execute_orders
    from cosmu.master.portfolio import Portfolio

    store = Store(Settings(database_url=f"sqlite:///{tmp_path}/alp.sqlite3", openrouter_api_key=None,
                           sim_bankroll=Decimal("100000")))
    portfolio = Portfolio(store, bankroll=Decimal("100000"))
    cat = default_catalog()
    fake = _FakeLiveAdapter(venue="alpaca", mode="paper")
    fake.asset_class = AssetClass.EQUITY
    order = IntendedOrder(
        strategy_version_id="ignite-alpaca-paper", symbol="IEF", venue_id="alpaca", side=1,
        qty=Decimal("1"), price=Decimal("93.62"), stop_loss=Decimal("88.94"), take_profit=Decimal("102.98"),
        conviction=Decimal("0.5"), gate_passed=True, order_type="market", client_order_id="coid-alp-1",
    )
    outcomes = execute_orders([order], live_enabled=True, kill_switch=False, adapter=fake,
                              store=store, portfolio=portfolio, risk=store.settings.risk, catalog=cat)

    assert outcomes[0].accepted and outcomes[0].routed_live and outcomes[0].venue == "testnet"
    assert len(fake.submitted) == 1  # it reached the REAL adapter, not a sim fill
    pos = store.row("SELECT venue, qty FROM positions WHERE strategy_version_id = ? AND CAST(qty AS REAL) != 0",
                    ("ignite-alpaca-paper",))
    assert pos is not None and pos["venue"] == "testnet"  # the LIVE book (held_live), not 'sim'
    ex = store.row("SELECT is_paper, venue_id FROM executions WHERE strategy_version_id = ?", ("ignite-alpaca-paper",))
    assert int(ex["is_paper"]) == 0 and ex["venue_id"] == "alpaca"


def test_resolve_live_adapters_empty_when_toggle_off(tmp_path):
    store = _store(tmp_path)
    assert ps._resolve_live_adapters(store) == {}  # toggle defaults off


def test_resolve_live_adapters_empty_without_keys_even_when_armed(tmp_path):
    """Toggle ON but no venue keys → still {} (every adapter resolves disabled). Arming the toggle alone can
    never hand the order path a live adapter."""
    store = _store(tmp_path)
    store.rows("UPDATE live_toggle SET enabled = 1 WHERE id = 'global'")
    assert ps._resolve_live_adapters(store) == {}
