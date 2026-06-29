# END-TO-END LIVE-ARMING DRY-RUN (roadmap #10 POC) — the ONE deterministic, seeded test that exercises the
# WHOLE capital path on a SYNTHETIC MATURED equity (TAA) track, once, reversibly, on SIM/TESTNET only, so every
# silent gap in the chain surfaces BEFORE the operator ever clicks launch on real money.
#
# The chain it walks, using the REAL functions (never re-implemented):
#   1. seed a matured equity cell — backdated track_opened clock, N real forward fills, a scope='track'
#      portfolio_snapshots trajectory that CLEARS the forward-significance bar (PAPER_MIN_FORWARD_DSR /
#      PAPER_MIN_FORWARD_OBS) + the maturity gate (PAPER_MIN_DAYS net-positive) + a proven-regime passport;
#   2. live_eligibility.live_eligibility_verdict says ELIGIBLE;
#   3. the arming entry api.routers.live.live_launch(confirm=True, venue='alpaca', symbol='SPY') returns ARMED
#      and the confirm-required human interlock holds (confirm=False refuses, no status write);
#   4. one orchestrator.paper_step.step_tracks tick routes a TESTNET order through a stub sandbox adapter (no
#      keys, no network) and the fill is read back into the book (is_paper=0 on the 'testnet' live book);
#   5. a seeded drawdown breach makes ops.capital_guard.run_capital_guard DISARM/reduce the track (reduce-only);
#   6. the Gate + per-combo BRUT model are untouched and NO real-money venue is reachable in the test.
#
# SAFETY: throwaway sqlite Store + the SIM/paper book; the only "live" adapter is an in-process STUB whose
# mode='paper' (Alpaca's sandbox → the 'testnet' book) — it never opens a socket, never carries a key, never
# touches a real venue. _resolve_live_adapters is monkeypatched so the executor can only ever see the stub.
# The conftest network guard would fail the test instantly if any real socket were opened.

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal

from conftest import seed_track_snapshots

import cosmu.api.app as app_mod
import cosmu.master.execution as execmod
import cosmu.orchestrator.paper_step as ps
from cosmu.config.settings import (
    PAPER_MIN_DAYS,
    PAPER_MIN_FORWARD_DSR,
    PAPER_MIN_FORWARD_OBS,
    LiveSettings,
    Settings,
)
from cosmu.core.interfaces import AssetClass, OrderId
from cosmu.data.market import Bar
from cosmu.knowledge.store import Store, utcnow
from cosmu.master.live_eligibility import live_eligibility_verdict
from cosmu.master.portfolio import Portfolio
from cosmu.ops import capital_guard
from cosmu.orchestrator.loop import PricingRouter
from cosmu.orchestrator.paper_step import step_tracks
from cosmu.spine.venue import default_catalog

# The one synthetic matured cell the whole dry-run is built around: an equity TAA strategy on SHY @ alpaca.
# alpaca is the equity FUNDING venue (orchestrator.loop._FUNDING_VENUE_BY_ASSET_CLASS) and the only equity venue
# with a real ExecutionAdapter — so its SANDBOX ('paper' mode → the 'testnet' live book) is the honest SIM/TESTNET
# target for an equity arm. SHY (1-3yr Treasury ETF) is the canonical TAA "safe asset" AND, being low-priced
# (~$82), lets a $1000 sim track-capital buy >= 1 whole share — so the gauntlet's lot_size floor is cleared and
# the entry genuinely routes (a higher-priced ETF like SPY at ~$550 would size to < 1 share and be lot_size-rejected;
# see the GAP note in the report).
_VID = "v-dryrun-taa"
_SYMBOL = "SHY"
_VENUE = "alpaca"
_INSTRUMENT = "shy-alpaca"
_NOW = dt.datetime(2026, 6, 28, tzinfo=dt.UTC)
# Bars anchored to ~now so step_tracks' equity data-recency guard treats them as FRESH (else the entry is
# rejected as stale and nothing routes). A gently rising tape → a 'bull' current regime (matches the proven set).
_BASE = dt.datetime.now(tz=dt.UTC) - dt.timedelta(days=80)


def _store(tmp_path) -> Store:
    # _env_file=None → hermetic: never inherit the dev box's real venue keys from .env.local (a real key would
    # let _resolve_live_adapters build a real adapter — this test must only ever see the in-process stub).
    return Store(
        Settings(
            database_url=f"sqlite:///{tmp_path}/dryrun.sqlite3",
            openrouter_api_key=None,
            live=LiveSettings(),
            _env_file=None,
        )
    )


def _bull_bars() -> list[Bar]:
    """A deterministic, gently-rising synthetic close series → current_regime reads 'bull'. Used for BOTH the
    eligibility regime reference AND the executor's price provider (so the entry signal sees real fresh bars).
    Anchored low (~$82, SHY's level) so the sized order buys >= 1 whole share (clears the lot_size floor)."""
    price = 82.0
    out: list[Bar] = []
    for i in range(80):
        price *= 1.001
        out.append(
            Bar(
                ts=_BASE + dt.timedelta(days=i),
                open=Decimal(str(round(price, 4))),
                high=Decimal(str(round(price * 1.002, 4))),
                low=Decimal(str(round(price * 0.998, 4))),
                close=Decimal(str(round(price, 4))),
                volume=Decimal("1000000"),
            )
        )
    return out


_BULL = _bull_bars()


class _EquityBars:
    """A deterministic equity bar provider (no network) serving the synthetic bull series for SPY."""

    def __init__(self, bars: list[Bar]) -> None:
        self._bars = bars

    def fetch_bars(self, symbol, timeframe, *, limit):  # noqa: ANN001, ANN201
        return self._bars[-limit:] if symbol == _SYMBOL else []


def _router(bars: list[Bar]) -> PricingRouter:
    provider = _EquityBars(bars)
    return PricingRouter(default_catalog(), crypto=provider, equity=provider)


# An always-true entry (ret_3d > -1 holds on any tape), a wide 5% stop / 50% take so a held leg HOLDS on a quiet
# tape — the SAME spec shape test_live_ignition uses, retargeted to equity (SPY @ alpaca).
_EQUITY_SPEC = {
    "name": "DryRunTAA",
    "rationale": "synthetic matured equity TAA cell for the live-arming dry-run",
    "lane": "gate",
    "universe": {"venues": ["alpaca"], "asset_classes": ["equity"], "min_instruments": 1},
    "horizon": {"bar_size": "1d", "min_hold_days": 1, "max_hold_days": 365},
    "entry": [{"feature": {"name": "ret_Nd", "lookback": 3}, "op": "gt", "threshold": {"param": "mom"}}],
    "exit": {"stop_loss": {"param": "sl"}, "take_profit": {"param": "tp"}, "signal_exits": []},
    "risk": {"max_concurrent_positions": 1, "max_position_pct": 1.0, "conviction": 0.5},
    "param_space": {},
    "direction": 1,
}
_EQUITY_PARAMS = {"mom": -1.0, "sl": 0.05, "tp": 0.50}


def _seed_matured_equity_cell(
    store: Store,
    *,
    net_pct: float = 4.0,
    proven: tuple[str, ...] = ("bull", "chop"),
    forward_sharpe: float = 0.40,
    fills: int = 2,
) -> None:
    """Seed ONE synthetic MATURED equity (TAA) cell that clears the live-arming gate by the REAL readers:

      • strategies + strategy_versions rows (status='paper', the gate-lane equity spec above + fitted params);
      • a per-cell `tracks` row (symbol/venue_id carried) whose return_pct is net-positive;
      • a scope='track' portfolio_snapshots series with enough marks (> PAPER_MIN_FORWARD_OBS) and a high enough
        forward Sharpe to clear PAPER_MIN_FORWARD_DSR (forward_significance);
      • a backdated track_opened event (clock origin > PAPER_MIN_DAYS ago) carrying the proven-regime passport;
      • `fills` REAL forward paper fills (executions is_paper=1, AFTER the clock origin, on the cell's own
        instrument+venue) — the >= MIN_FORWARD_FILLS "it actually traded forward" precondition;
      • a FLAT (zero-qty) position on the sim book so step_tracks' flat-row query picks the cell up next tick;
      • a passed backtest + a 'pass' backtest_symbols cell (the BRUT per-combo proof) so the eligible-listing
        query and the funded-cell attribution guard both resolve this cell.

    Every number is read back by the production functions (no faked verdicts)."""
    sid = store.insert("strategies", {"name": "DryRunTAA", "thesis": "t", "origin": "finder", "created_at": utcnow()})
    store.insert(
        "strategy_versions",
        {
            "id": _VID, "strategy_id": sid, "parent_id": None,
            "spec": _EQUITY_SPEC, "generated_code": "# taa", "code_hash": "hash-dryrun-taa",
            "params": _EQUITY_PARAMS, "mutation_operator": None, "mutation_rationale": None,
            "origin": "finder", "status": "paper", "created_at": utcnow(),
            "killed_at": None, "kill_reason": None,
        },
    )
    store.insert(
        "tracks",
        {
            "strategy_version_id": _VID, "symbol": _SYMBOL, "venue_id": _VENUE,
            "starting_capital": "100000", "equity": str(100000 * (1 + net_pct / 100)),
            "return_pct": str(net_pct), "updated_at": utcnow(),
        },
    )
    # Forward trajectory + proven-regime passport keyed BOTH ways, on purpose:
    #   • the BRUT CELL key (version:symbol:venue) — what the cell-scoped eligibility verdict reads (step 1+2);
    #   • the VERSION-only key — what the ARMING ENTRY reads, because live_launch calls live_eligibility_verdict
    #     WITHOUT symbol/venue (see the GAP note in the report: the arming path is still version-scoped, not yet
    #     re-keyed per BRUT triple). Seeding both keeps every REAL reader honest without faking a verdict.
    cell_ref = f"{_VID}:{_SYMBOL}:{_VENUE}"
    obs = PAPER_MIN_FORWARD_OBS + 18  # well over the minimum so the PSR estimate is trusted
    seed_track_snapshots(store, cell_ref, obs=obs, forward_sharpe=forward_sharpe, now=_NOW)
    seed_track_snapshots(store, _VID, obs=obs, forward_sharpe=forward_sharpe, now=_NOW)

    origin = _NOW - dt.timedelta(days=PAPER_MIN_DAYS + 10)  # matured: clock older than PAPER_MIN_DAYS
    ts = origin.isoformat()
    passport = json.dumps({"proven_regimes": list(proven), "symbol": _SYMBOL, "venue_id": _VENUE})
    with store.batch() as w:
        for ref in (cell_ref, _VID):  # passport under both the cell key AND the version-only key
            w.execute(
                "INSERT INTO events(ts, actor, kind, ref_type, ref_id, payload) "
                "VALUES (?, 'master', 'track_opened', 'strategy_version', ?, ?)",
                (ts, ref, passport),
            )
        w.execute(
            "INSERT INTO runs(id, strategy_version_id, mode, venue_id, seed, started_at, status) "
            "VALUES (?, ?, 'sandbox', ?, 1, ?, 'completed')",
            (f"run-{_VID}", _VID, _VENUE, ts),
        )
        for i in range(fills):
            w.execute(
                "INSERT INTO executions(id, run_id, strategy_version_id, instrument_id, venue_id, side, qty, "
                "price, fee, slippage, order_type, is_paper, ts, fill_log) "
                "VALUES (?, ?, ?, ?, ?, 'buy', '1', '400', '0.1', '0', 'market', 1, ?, '{}')",
                (f"ex-{_VID}-{i}", f"run-{_VID}", _VID, _INSTRUMENT, _VENUE,
                 (origin + dt.timedelta(hours=i + 1)).isoformat()),
            )
    # A passed backtest + the BRUT per-combo 'pass' cell (the only proof the gate funds on).
    bt_id = store.insert(
        "backtests",
        {"strategy_version_id": _VID, "kind": "screen", "oos_return": "0.2", "sharpe": "1.5", "sortino": "1.5",
         "deflated_sharpe": "1.5", "max_dd": "0.1", "win_rate": "0.6", "num_trades": 30, "pbo": "0.0",
         "trials_counted": 1, "regime_label": json.dumps({"bull": 0.05, "chop": 0.01}), "folds_positive": 5,
         "passed_gates": 1, "holdout_passed": 1, "created_at": utcnow()},
    )
    store.insert(
        "backtest_symbols",
        {"backtest_id": bt_id, "strategy_version_id": _VID, "symbol": _SYMBOL, "venue_id": _VENUE,
         "return_pct": "0.2", "sharpe": "1.5", "max_drawdown": "0.1", "trades": 30, "verdict": "pass",
         "created_at": utcnow()},
    )
    # FLAT sim registration so step_tracks' flat-row query (venue='sim', qty=0) sees the cell as a re-entry
    # candidate — exactly what the funder writes for a survivor before its first signal fires.
    Portfolio(store, bankroll=store.settings.sim_bankroll).register_track(
        instrument_id=_INSTRUMENT, symbol=_SYMBOL, venue="sim", strategy_version_id=_VID
    )


class _StubSandboxAdapter:
    """An ACTIVE Alpaca-SANDBOX execution adapter (mode='paper' → the 'testnet' live book) with NO keys and NO
    network. It records every order it receives so the test can prove the order genuinely reached the venue
    adapter (not a sim fill). This is the ONLY 'live' adapter the executor can see in this test — it can never
    touch real money."""

    asset_class = AssetClass.EQUITY

    def __init__(self) -> None:
        self.venue = _VENUE
        self.mode = "paper"  # Alpaca sandbox; _live_venue normalizes 'paper' → the 'testnet' live book
        self.submitted: list = []

    @property
    def active(self) -> bool:
        return True

    def submit(self, order):  # noqa: ANN001, ANN201
        self.submitted.append(order)
        return OrderId(venue=self.venue, client_order_id=order.client_order_id, venue_order_id="STUB-1")

    def cancel(self, order_id):  # noqa: ANN001 — not exercised here  # pragma: no cover
        pass

    def positions(self):  # noqa: ANN201
        return []

    def fills(self, since):  # noqa: ANN001, ANN201
        return []


def _arm_via_router(store, settings, monkeypatch, *, confirm: bool, override_paper: bool = False):
    """Drive the REAL arming entry (api.routers.live.live_launch) against the throwaway store. The app.store/
    app.settings write fans out to the live router (app._INJECTABLE_MODULES). _venue_connected is stubbed True to
    simulate TESTNET keys being present WITHOUT putting a key on disk; _version_reference_bars is stubbed to the
    deterministic bull series so the regime read needs no network."""
    from cosmu.api.models import LaunchActivateRequest
    from cosmu.api.routers import live as live_router

    monkeypatch.setattr(app_mod, "store", store)
    monkeypatch.setattr(app_mod, "settings", settings)
    monkeypatch.setattr(live_router, "_venue_connected", lambda venue_id: True)  # simulate testnet keys present
    monkeypatch.setattr(live_router, "_version_reference_bars", lambda vid: _BULL)  # deterministic regime, no net
    req = LaunchActivateRequest(
        version_id=_VID, venue_id=_VENUE, symbol=_SYMBOL, budget=100.0,
        per_strategy_cap=100.0, global_cap=1000.0, max_daily_loss=50.0,
        confirm=confirm, override_paper=override_paper,
    )
    return live_router.live_launch(req)


# ---------------------------------------------------------------------------------------------------------------
# STEP 1 + 2 — a synthetic matured equity cell is judged ELIGIBLE by the REAL live-eligibility verdict.
# ---------------------------------------------------------------------------------------------------------------

def test_step1_2_matured_cell_is_eligible(tmp_path):
    store = _store(tmp_path)
    _seed_matured_equity_cell(store)

    v = live_eligibility_verdict(store, _VID, _BULL, now=_NOW, symbol=_SYMBOL, venue_id=_VENUE)

    assert v.regime_eligible is True, v.reason          # current regime (bull) is in the proven set
    assert v.paper_age_days >= PAPER_MIN_DAYS, v.reason  # matured
    assert v.forward_obs >= PAPER_MIN_FORWARD_OBS        # enough daily marks for a trusted PSR
    assert v.forward_dsr > PAPER_MIN_FORWARD_DSR, v.reason  # forward trajectory is SIGNIFICANTLY positive
    assert v.forward_ready is True, v.reason
    assert v.eligible is True, v.reason
    assert v.overridden is False                          # earned by evidence, NOT a human override


# ---------------------------------------------------------------------------------------------------------------
# STEP 3 — the arming entry ARMS the eligible cell on the SIM/TESTNET venue, and the confirm interlock holds.
# ---------------------------------------------------------------------------------------------------------------

def test_step3_confirm_interlock_required(tmp_path, monkeypatch):
    """The human-arming interlock: confirm=False NEVER arms and NEVER writes status='live' (two-click safety)."""
    store = _store(tmp_path)
    _seed_matured_equity_cell(store)

    resp = _arm_via_router(store, store.settings, monkeypatch, confirm=False)

    assert resp.armed is False
    assert "confirm" in (resp.reason or "").lower()
    status = store.row("SELECT status FROM strategy_versions WHERE id = ?", (_VID,))["status"]
    assert status == "paper"  # NOT promoted to live — the interlock held


def test_step3_arms_on_confirm(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _seed_matured_equity_cell(store)

    resp = _arm_via_router(store, store.settings, monkeypatch, confirm=True)

    assert resp.armed is True, resp.reason
    assert resp.readiness == "proven"
    assert resp.overridden is False
    # status='live' is written ONLY here, on a confirmed eligible launch.
    assert store.row("SELECT status FROM strategy_versions WHERE id = ?", (_VID,))["status"] == "live"
    # the live-launch + lifecycle-armed audit marks fired.
    assert store.row("SELECT id FROM events WHERE kind = 'live_launched' AND ref_id = ?", (_VID,)) is not None
    # a frozen promotion record now exists → the executor will only ever open the EXACT proven config.
    from cosmu.master.promotion import promotion_record

    assert promotion_record(store, _VID) is not None


# ---------------------------------------------------------------------------------------------------------------
# STEP 4 — one executor tick routes a REAL (testnet) order through the sandbox adapter and books the fill.
# ---------------------------------------------------------------------------------------------------------------

def test_step4_executor_routes_testnet_order_and_books_fill(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _seed_matured_equity_cell(store)
    # Arm the cell through the real entry (writes status='live' + freezes the config).
    _arm_via_router(store, store.settings, monkeypatch, confirm=True)
    # Flip the global live toggle on (the DB half of the ignition switch).
    store.rows("UPDATE live_toggle SET enabled = 1 WHERE id = 'global'")

    # The ONLY 'live' adapter the executor can see is the in-process sandbox stub (no keys, no network). This is
    # what keeps the dry-run on testnet — _resolve_live_adapters can never resolve a real adapter here.
    stub = _StubSandboxAdapter()
    monkeypatch.setattr(ps, "_resolve_live_adapters", lambda s: {_VENUE: stub})
    # Make the per-order regime gate (master/execution) deterministic + network-free: proven {bull,chop}, current
    # bull → eligible. (Without this it tries adapter.reference_bars / data and would advisory-skip; we pin it.)
    monkeypatch.setattr(execmod, "_regime_returns", lambda store_, vid: {"bull": 0.05, "chop": 0.01})
    monkeypatch.setattr(execmod, "_reference_bars", lambda adapter, symbol: [float(b.close) for b in _BULL])

    report = step_tracks(store, router=_router(_BULL), now=_NOW)

    assert report.opened == 1, report                     # the entry signal fired and the order was ACCEPTED
    assert len(stub.submitted) == 1 and stub.submitted[0].side == 1  # it reached the REAL sandbox adapter
    # The fill was read back into the book on the 'testnet' LIVE book (not the offline 'sim' lane).
    pos = store.row(
        "SELECT venue, qty FROM positions WHERE strategy_version_id = ? AND CAST(qty AS REAL) != 0", (_VID,)
    )
    assert pos is not None and pos["venue"] == "testnet"
    # The ROUTED order is recorded as a genuine (non-paper) venue fill — scoped to is_paper=0 so it is the live
    # fill, not one of the seeded maturity-evidence paper fills (is_paper=1).
    ex = store.row(
        "SELECT is_paper, venue_id FROM executions WHERE side = 'buy' AND is_paper = 0 AND strategy_version_id = ?",
        (_VID,),
    )
    assert ex is not None and int(ex["is_paper"]) == 0 and ex["venue_id"] == _VENUE
    assert store.row("SELECT id FROM events WHERE kind = 'order_submitted_live'") is not None


# ---------------------------------------------------------------------------------------------------------------
# STEP 5 — a drawdown breach makes the capital guard DISARM (reduce-only liquidate) the now-held cell.
# ---------------------------------------------------------------------------------------------------------------

def test_step5_drawdown_breach_disarms_via_capital_guard(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _seed_matured_equity_cell(store)
    _arm_via_router(store, store.settings, monkeypatch, confirm=True)
    store.rows("UPDATE live_toggle SET enabled = 1 WHERE id = 'global'")
    stub = _StubSandboxAdapter()
    monkeypatch.setattr(ps, "_resolve_live_adapters", lambda s: {_VENUE: stub})
    monkeypatch.setattr(execmod, "_regime_returns", lambda store_, vid: {"bull": 0.05, "chop": 0.01})
    monkeypatch.setattr(execmod, "_reference_bars", lambda adapter, symbol: [float(b.close) for b in _BULL])
    step_tracks(store, router=_router(_BULL), now=_NOW)  # open the (testnet) position
    held = store.row("SELECT qty FROM positions WHERE strategy_version_id = ? AND CAST(qty AS REAL) != 0", (_VID,))
    assert held is not None  # a real open leg exists to protect

    # Seed a FLOOR breach: mark the cell's equity down to 60% of its 100000 starting capital (below the 0.70
    # floor = 70000). The guard reads the LATEST scope='track' snapshot for the cell — stamp it strictly AFTER the
    # seeded healthy series (now + 1d) so it is unambiguously the most-recent mark that forces the liquidation.
    store.insert(
        "portfolio_snapshots",
        {"scope": "track", "ref_id": f"{_VID}:{_SYMBOL}:{_VENUE}",
         "ts": (_NOW + dt.timedelta(days=1)).isoformat(),
         "equity": "60000", "cash": "0", "positions_value": "60000", "pnl": "0", "drawdown": "0.40"},
    )

    # Run the guard. The held leg is on the 'testnet' live book; with the stub armed it routes the reduce-only
    # close through the stub (a real protective close on the sandbox), then books it. NO armed venue → it would
    # sim-close instead; either way the breach DISARMS the cell.
    monkeypatch.setattr(capital_guard, "_resolve_live_adapters", lambda s: {_VENUE: stub})
    pricer = _router(_BULL)  # last_price > 0 so the close fills at a real mark
    rep = capital_guard.run_capital_guard(store, catalog=default_catalog(), router=pricer, now=_NOW)

    assert rep.evaluated == 1 and rep.protected == 1, rep
    assert rep.actions[0]["kind"] == "liquidate" and rep.actions[0]["reason"] == "capital_floor"
    # the cell is FLAT after the protective close — disarmed, no exposure left to ride down.
    flat = store.row(
        "SELECT COALESCE(SUM(CAST(qty AS REAL)), 0) AS q FROM positions WHERE strategy_version_id = ?", (_VID,)
    )
    assert float(flat["q"]) == 0.0
    assert store.row("SELECT id FROM events WHERE kind = 'capital_guard_action' AND ref_id = ?", (_VID,)) is not None


# ---------------------------------------------------------------------------------------------------------------
# STEP 6 — the Gate + per-combo BRUT model are UNTOUCHED, and NO real-money path is reachable from this test.
# ---------------------------------------------------------------------------------------------------------------

def test_step6_gate_and_brut_untouched_and_no_real_money_reachable(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _seed_matured_equity_cell(store)

    # (a) The Gate is a separate, locked module — arming reads it (passed_gates) but never writes or loosens it.
    #     The arm leaves the backtest's gate verdict + the BRUT 'pass' cell byte-identical.
    before_bt = store.row("SELECT passed_gates, holdout_passed FROM backtests WHERE strategy_version_id = ?", (_VID,))
    before_brut = store.row(
        "SELECT verdict, return_pct FROM backtest_symbols WHERE strategy_version_id = ?", (_VID,)
    )
    _arm_via_router(store, store.settings, monkeypatch, confirm=True)
    after_bt = store.row("SELECT passed_gates, holdout_passed FROM backtests WHERE strategy_version_id = ?", (_VID,))
    after_brut = store.row(
        "SELECT verdict, return_pct FROM backtest_symbols WHERE strategy_version_id = ?", (_VID,)
    )
    assert dict(before_bt) == dict(after_bt)         # the Gate verdict is untouched by arming
    assert dict(before_brut) == dict(after_brut)     # the per-combo BRUT proof is untouched

    # (b) NO real-money adapter is reachable: with the toggle ON but ZERO keys (hermetic store), the real
    #     resolver returns {} — arming the toggle alone can NEVER hand the order path a live adapter.
    store.rows("UPDATE live_toggle SET enabled = 1 WHERE id = 'global'")
    assert ps._resolve_live_adapters(store) == {}, "a real exec adapter resolved with no keys — REAL MONEY RISK"

    # (c) The aggregate live mode with no keys is 'disabled' (never 'live'): there is no real venue to route to.
    from cosmu.adapters.exec.registry import live_mode

    assert live_mode(store.settings) == "disabled"


def test_step6_unarmed_live_track_stays_sim_safe_default(tmp_path, monkeypatch):
    """The safe default that backs the whole dry-run: a status='live' cell with NO armed adapter paper-trades in
    SIM — it can never route a real order. (No _resolve_live_adapters monkeypatch → the real resolver returns {}.)"""
    store = _store(tmp_path)
    _seed_matured_equity_cell(store)
    _arm_via_router(store, store.settings, monkeypatch, confirm=True)
    store.rows("UPDATE live_toggle SET enabled = 1 WHERE id = 'global'")  # toggle on, but still NO keys

    report = step_tracks(store, router=_router(_BULL), now=_NOW)

    assert report.opened == 1
    pos = store.row(
        "SELECT venue FROM positions WHERE strategy_version_id = ? AND CAST(qty AS REAL) != 0", (_VID,)
    )
    assert pos is not None and pos["venue"] == "sim"  # the offline SIM book, not a live book
    assert store.row("SELECT id FROM events WHERE kind = 'order_submitted_live'") is None  # no real submit
