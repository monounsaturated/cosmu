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
from cosmu.orchestrator.loop import PricingRouter, fund_tracks_from_survivors
from cosmu.orchestrator.paper_step import step_tracks
from cosmu.spine.venue import default_catalog

_BASE = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/ignite.sqlite3", openrouter_api_key=None))


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


def test_resolve_live_adapters_empty_when_toggle_off(tmp_path):
    store = _store(tmp_path)
    assert ps._resolve_live_adapters(store) == {}  # toggle defaults off


def test_resolve_live_adapters_empty_without_keys_even_when_armed(tmp_path):
    """Toggle ON but no venue keys → still {} (every adapter resolves disabled). Arming the toggle alone can
    never hand the order path a live adapter."""
    store = _store(tmp_path)
    store.rows("UPDATE live_toggle SET enabled = 1 WHERE id = 'global'")
    assert ps._resolve_live_adapters(store) == {}
