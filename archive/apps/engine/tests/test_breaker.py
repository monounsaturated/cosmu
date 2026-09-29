# The LATCHING CIRCUIT-BREAKER (cosmu/ops/breaker.py): the aviation-model hard-stop that, on a HARD aggregate
# breach, DISARMS live + LIQUIDATES the armed book (via the existing gauntlet-exempt capital_guard.kill) and STAYS
# latched until a human re-arms. These prove SENSE→DECIDE→STATE offline on the sim book: a temp sqlite Store, a
# stub pricing router (no network), live OFF (every close reduce-fills the sim/paper book). NOTHING here arms or
# trades — the breaker can only ever disarm + reduce. The Gate is never touched.

from __future__ import annotations

from decimal import Decimal

from cosmu.config.settings import RiskSettings, Settings
from cosmu.knowledge.store import Store, utcnow
from cosmu.master.portfolio import Portfolio
from cosmu.master.risk import (
    OrderIntent,
    PortfolioRiskState,
    validate_order_full,
)
from cosmu.ops import breaker
from cosmu.spine.venue import default_catalog

CATALOG = default_catalog()
_INSTRUMENT = "btc-usdt-binance"
_SYMBOL = "BTCUSDT"
_VENUE = "binance"


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/breaker.sqlite3"))


class _StubRouter:
    """Deterministic pricing: every symbol marks at `price` (no network). Mirrors PricingRouter.last_price."""

    def __init__(self, price: Decimal) -> None:
        self._price = price

    def last_price(self, symbol: str, venue: str) -> Decimal:  # noqa: ARG002
        return self._price


def _fund_held_track(
    store: Store, *, version_id: str, qty: Decimal, avg_price: Decimal, starting_capital: Decimal
) -> Portfolio:
    """A FUNDED, HELD track: a tracks row (the cell) + a real open long on the sim book. Mirrors the
    capital-guard test harness so the breaker's delegated kill has a real position to liquidate."""
    store.rows(
        "INSERT INTO strategies (id, name, thesis, origin, created_at) VALUES (?, ?, ?, ?, ?)",
        ("strat1", "breaker-test", "breaker test", "test", utcnow()),
    )
    store.rows(
        "INSERT INTO strategy_versions "
        "(id, strategy_id, spec, generated_code, code_hash, params, origin, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (version_id, "strat1", "{}", "", "h", "{}", "test", "paper", utcnow()),
    )
    store.insert(
        "tracks",
        {
            "strategy_version_id": version_id,
            "symbol": _SYMBOL,
            "venue_id": _VENUE,
            "starting_capital": str(starting_capital),
            "equity": str(starting_capital),
            "return_pct": "0.00",
            "updated_at": utcnow(),
        },
    )
    pf = Portfolio(store, bankroll=Decimal("100000"))
    pf.apply_fill(
        instrument_id=_INSTRUMENT, symbol=_SYMBOL, venue="sim", side=1,
        qty=qty, price=avg_price, fee=Decimal("0"), strategy_version_id=version_id,
    )
    # A cell-keyed scope='track' snapshot so capital_guard._funded_holdings can resolve marked equity.
    store.insert(
        "portfolio_snapshots",
        {"scope": "track", "ref_id": f"{version_id}:{_SYMBOL}:{_VENUE}", "ts": utcnow(),
         "equity": str(starting_capital), "cash": "0.00", "positions_value": str(starting_capital),
         "pnl": "0.00", "drawdown": "0.0000"},
    )
    return pf


def _agg_snapshot(store: Store, *, drawdown: Decimal, equity: Decimal = Decimal("100000"), ts: str | None = None) -> None:
    """Write one aggregate portfolio_snapshot with a given drawdown — this is what portfolio.drawdown() reads,
    the axis the breaker senses. `equity` sets the aggregate equity (daily_loss reads it vs the day's first snap)."""
    store.insert(
        "portfolio_snapshots",
        {"scope": "aggregate", "ref_id": "global", "ts": ts or utcnow(),
         "equity": str(equity), "cash": str(equity), "positions_value": "0",
         "pnl": "0.00", "drawdown": str(drawdown)},
    )


def _arm_live(store: Store) -> None:
    store.rows("UPDATE live_toggle SET enabled = 1, enabled_at = ?, enabled_by = ? WHERE id = 'global'",
               (utcnow(), "test"))


def _live_enabled(store: Store) -> bool:
    row = store.row("SELECT enabled FROM live_toggle WHERE id = 'global'")
    return bool(row and row["enabled"])


# --- assess / no-op --------------------------------------------------------------------------------

def test_no_op_when_not_breaching(tmp_path):
    # A healthy book (drawdown 3% — below the 8% warn band) → tier 'none', a strict no-op: the paper-clock pass
    # neither trips nor latches nor emits any breaker event nor touches the order path.
    from cosmu.orchestrator.loop import run_breaker_pass

    store = _store(tmp_path)
    _agg_snapshot(store, drawdown=Decimal("0.03"))
    verdict = breaker.assess(store)
    assert verdict.tier == "none" and verdict.soft is False
    res = run_breaker_pass(store, router=_StubRouter(Decimal("65000")))
    assert res["tier"] == "none" and res["tripped"] == 0
    assert breaker.is_latched(store) is False
    assert store.row("SELECT id FROM events WHERE kind = 'breaker_tripped'") is None
    assert store.row("SELECT id FROM events WHERE kind = 'breaker_warn'") is None


# --- hard drawdown trips liquidate + disarm --------------------------------------------------------

def test_hard_drawdown_trips_liquidate_and_disarm(tmp_path):
    # Drawdown 30% ≥ the 25% liquidate band → HARD trip: (1) live disarmed, (2) the held position reduce-only
    # CLOSED, (3) a breaker_tripped freeze-frame event, (4) latched.
    store = _store(tmp_path)
    _arm_live(store)
    assert _live_enabled(store) is True
    _fund_held_track(store, version_id="sv-hard", qty=Decimal("0.02"), avg_price=Decimal("50000"),
                     starting_capital=Decimal("1000"))
    _agg_snapshot(store, drawdown=Decimal("0.30"))

    verdict = breaker.assess(store)
    assert verdict.tier == "liquidate" and verdict.soft is False
    assert verdict.freeze_frame["trigger"] == "drawdown"

    tripped = breaker.trip(store, verdict.freeze_frame, catalog=CATALOG, router=_StubRouter(Decimal("50000")))
    assert tripped is True

    # (1) live DISARMED
    assert _live_enabled(store) is False
    # (2) the held position is reduce-only CLOSED (flat) + a sell execution booked
    pf = Portfolio(store, bankroll=Decimal("100000"))
    pos = pf.position(_INSTRUMENT, "sim", strategy_version_id="sv-hard")
    assert pos is not None and pos.qty == Decimal("0")
    assert store.row("SELECT id FROM executions WHERE side = 'sell'") is not None
    # (3) a breaker_tripped freeze-frame event
    trip_ev = store.row("SELECT payload FROM events WHERE kind = 'breaker_tripped' ORDER BY id DESC LIMIT 1")
    assert trip_ev is not None
    # (4) latched
    assert breaker.is_latched(store) is True


# --- latch is idempotent across ticks (liquidates exactly once) ------------------------------------

def test_latch_is_idempotent_across_ticks(tmp_path):
    # A latched breaker liquidates EXACTLY once: a second trip() on the next tick is a no-op (no second close,
    # no second event), even with the breach still present.
    store = _store(tmp_path)
    _arm_live(store)
    _fund_held_track(store, version_id="sv-once", qty=Decimal("0.02"), avg_price=Decimal("50000"),
                     starting_capital=Decimal("1000"))
    _agg_snapshot(store, drawdown=Decimal("0.30"))

    v1 = breaker.assess(store)
    assert breaker.trip(store, v1.freeze_frame, catalog=CATALOG, router=_StubRouter(Decimal("50000"))) is True
    sells_after_first = len(store.rows("SELECT id FROM executions WHERE side = 'sell'"))
    trips_after_first = len(store.rows("SELECT id FROM events WHERE kind = 'breaker_tripped'"))

    # Next tick, breach still present → trip() must be a NO-OP (already latched).
    v2 = breaker.assess(store)
    assert breaker.trip(store, v2.freeze_frame, catalog=CATALOG, router=_StubRouter(Decimal("50000"))) is False
    assert len(store.rows("SELECT id FROM executions WHERE side = 'sell'")) == sells_after_first
    assert len(store.rows("SELECT id FROM events WHERE kind = 'breaker_tripped'")) == trips_after_first == 1


# --- dwell debounce on the soft band ---------------------------------------------------------------

def test_dwell_debounce_soft_band(tmp_path):
    # A soft (warn) band must PERSIST breaker_dwell_ticks consecutive ticks before a breaker_warn is emitted:
    # a single spike (1 tick) stays silent; K consecutive ticks escalate. Drives the loop's run_breaker_pass.
    from cosmu.orchestrator.loop import run_breaker_pass

    store = _store(tmp_path)
    dwell = int(store.settings.risk.breaker_dwell_ticks)
    assert dwell >= 2  # the default; the test asserts the debounce holds for the configured K

    # Tick 1: a single warn-band spike (drawdown 10% — ≥ 8% warn, < 15% halt) → NO breaker_warn yet (count 1 < K).
    _agg_snapshot(store, drawdown=Decimal("0.10"))
    res = run_breaker_pass(store, router=_StubRouter(Decimal("65000")))
    assert res["tier"] == "warn" and res["tripped"] == 0
    assert store.row("SELECT id FROM events WHERE kind = 'breaker_warn'") is None

    # Persist the warn band for the remaining consecutive ticks until it reaches K → breaker_warn fires.
    for _ in range(dwell - 1):
        _agg_snapshot(store, drawdown=Decimal("0.10"))
        run_breaker_pass(store, router=_StubRouter(Decimal("65000")))
    assert store.row("SELECT id FROM events WHERE kind = 'breaker_warn'") is not None
    # Still NOT latched (a soft band never liquidates/disarms).
    assert breaker.is_latched(store) is False


def test_dwell_resets_on_healthy_tick(tmp_path):
    # A soft-band run interrupted by a healthy tick RESETS the debounce: the count starts over, so the warn
    # requires a fresh full K consecutive ticks (a spike-then-recover never accumulates toward a warn).
    from cosmu.orchestrator.loop import run_breaker_pass

    store = _store(tmp_path)
    dwell = int(store.settings.risk.breaker_dwell_ticks)

    _agg_snapshot(store, drawdown=Decimal("0.10"))  # warn spike (count 1)
    run_breaker_pass(store, router=_StubRouter(Decimal("65000")))
    assert breaker.dwell_count(store) == 1
    _agg_snapshot(store, drawdown=Decimal("0.02"))  # healthy → reset
    run_breaker_pass(store, router=_StubRouter(Decimal("65000")))
    assert breaker.dwell_count(store) == 0
    # A single warn tick after the reset is again below K → still no warn event.
    _agg_snapshot(store, drawdown=Decimal("0.10"))
    run_breaker_pass(store, router=_StubRouter(Decimal("65000")))
    if dwell > 1:
        assert store.row("SELECT id FROM events WHERE kind = 'breaker_warn'") is None


# --- daily-loss multiple trips ---------------------------------------------------------------------

def test_daily_loss_multiple_trips(tmp_path):
    # daily_loss ≥ daily_loss_cap × liquidate_mult trips the HARD band even when drawdown alone is below the
    # liquidate drawdown band. Default cap $250 × 1.5 = $375 → a $400 intraday loss trips on the daily-loss axis.
    store = _store(tmp_path)
    _arm_live(store)
    _fund_held_track(store, version_id="sv-daily", qty=Decimal("0.02"), avg_price=Decimal("50000"),
                     starting_capital=Decimal("1000"))
    # Day's FIRST aggregate snapshot at equity 100000 (drawdown small), then 'now' down $400 with a modest 10%
    # drawdown (≥ warn/halt but < the 25% liquidate drawdown) so the ONLY hard trigger is daily loss.
    day = utcnow()[:10]
    _agg_snapshot(store, drawdown=Decimal("0.02"), equity=Decimal("100000"), ts=f"{day}T00:00:00+00:00")
    _agg_snapshot(store, drawdown=Decimal("0.10"), equity=Decimal("99600"), ts=f"{day}T12:00:00+00:00")

    verdict = breaker.assess(store)
    assert verdict.tier == "liquidate"
    assert verdict.freeze_frame["trigger"] == "daily_loss"
    assert breaker.trip(store, verdict.freeze_frame, catalog=CATALOG, router=_StubRouter(Decimal("50000"))) is True
    assert _live_enabled(store) is False
    assert breaker.is_latched(store) is True


# --- reduce_only is NEVER blocked when latched (Therac-25 lesson) -----------------------------------

def test_reduce_only_never_blocked_when_latched():
    # THE critical safety invariant: a reduce-only CLOSE must be accepted even when the breaker is latched —
    # trapping an exit behind the latch would lock in the very loss the breaker exists to stop. An ENTRY with the
    # same latched state is rejected (breaker_latched issue); the CLOSE is accepted. Pure in-memory gauntlet call —
    # no store/network/order path (the interlock is a gauntlet decision, verifiable without a book).
    venue = CATALOG.venue(_VENUE)
    instrument = CATALOG.instrument(_SYMBOL, _VENUE)
    risk = RiskSettings()

    # A latched, live-armed ENTRY → rejected with the breaker_latched issue.
    entry = OrderIntent(
        symbol=_SYMBOL, side="buy", qty=Decimal("0.01"), price=Decimal("50000"),
        stop_loss=Decimal("49000"), take_profit=Decimal("52000"), conviction=Decimal("0.5"),
        sizing_basis="equity_vol_conviction", reduce_only=False,
    )
    entry_state = PortfolioRiskState(breaker_latched=True)
    entry_decision = validate_order_full(entry, venue, instrument, risk, entry_state)
    assert entry_decision.accepted is False
    assert "breaker_latched" in entry_decision.issues

    # A latched, live-armed reduce-only CLOSE of a held long → ACCEPTED, and never carries the breaker_latched issue.
    close = OrderIntent(
        symbol=_SYMBOL, side="sell", qty=Decimal("0.01"), price=Decimal("50000"),
        stop_loss=None, take_profit=None, conviction=Decimal("0.5"),
        sizing_basis="equity_vol_conviction", reduce_only=True,
    )
    close_state = PortfolioRiskState(breaker_latched=True, existing_qty=Decimal("0.02"))
    close_decision = validate_order_full(close, venue, instrument, risk, close_state)
    assert close_decision.accepted is True
    assert "breaker_latched" not in close_decision.issues


# --- rearm requires confirm + clears latch ---------------------------------------------------------

def test_rearm_requires_confirm_and_clears_latch(tmp_path):
    # rearm() clears the latch (appends breaker_rearmed → is_latched False); a rearm of an OPEN breaker is a
    # no-op (never writes a spurious marker). The API route's confirm gate is exercised in test_ops_router-style
    # below via the model; here we prove the state machine.
    store = _store(tmp_path)
    _arm_live(store)
    _fund_held_track(store, version_id="sv-rearm", qty=Decimal("0.02"), avg_price=Decimal("50000"),
                     starting_capital=Decimal("1000"))
    _agg_snapshot(store, drawdown=Decimal("0.30"))
    v = breaker.assess(store)
    breaker.trip(store, v.freeze_frame, catalog=CATALOG, router=_StubRouter(Decimal("50000")))
    assert breaker.is_latched(store) is True

    # Re-arm clears the latch.
    assert breaker.rearm(store) is True
    assert breaker.is_latched(store) is False
    # Re-arming an already-open breaker is a no-op (no second marker).
    assert breaker.rearm(store) is False
    assert len(store.rows("SELECT id FROM events WHERE kind = 'breaker_rearmed'")) == 1


def test_rearm_route_requires_confirm(tmp_path, monkeypatch):
    # The ops route refuses without confirm=true and clears the latch with it — proving the two-click safety.
    import cosmu.api._shared as shared
    from cosmu.api.routers import ops as ops_router
    from cosmu.api.models import BreakerRearmRequest

    store = _store(tmp_path)
    monkeypatch.setattr(shared, "store", store)
    monkeypatch.setattr(ops_router, "store", store)
    _arm_live(store)
    _fund_held_track(store, version_id="sv-route", qty=Decimal("0.02"), avg_price=Decimal("50000"),
                     starting_capital=Decimal("1000"))
    _agg_snapshot(store, drawdown=Decimal("0.30"))
    v = breaker.assess(store)
    breaker.trip(store, v.freeze_frame, catalog=CATALOG, router=_StubRouter(Decimal("50000")))
    assert breaker.is_latched(store) is True

    # confirm omitted → refused, latch untouched.
    resp = ops_router.ops_breaker_rearm(BreakerRearmRequest(confirm=False))
    assert resp.rearmed is False and resp.was_latched is True
    assert breaker.is_latched(store) is True

    # confirm=true → cleared.
    resp2 = ops_router.ops_breaker_rearm(BreakerRearmRequest(confirm=True))
    assert resp2.rearmed is True and resp2.was_latched is True
    assert breaker.is_latched(store) is False


# --- live-toggle interlock (weight-on-wheels) ------------------------------------------------------

def test_live_toggle_interlock(tmp_path, monkeypatch):
    # A latched breaker makes re-enabling live IMPOSSIBLE via /toggle/live: the request is refused with the
    # documented reason and live stays OFF. Once re-armed, enabling live succeeds.
    import cosmu.api._shared as shared
    from cosmu.api.routers import toggle as toggle_router
    from cosmu.api.models import ToggleRequest

    store = _store(tmp_path)
    monkeypatch.setattr(shared, "store", store)
    monkeypatch.setattr(toggle_router, "store", store)
    _fund_held_track(store, version_id="sv-interlock", qty=Decimal("0.02"), avg_price=Decimal("50000"),
                     starting_capital=Decimal("1000"))
    _agg_snapshot(store, drawdown=Decimal("0.30"))
    v = breaker.assess(store)
    breaker.trip(store, v.freeze_frame, catalog=CATALOG, router=_StubRouter(Decimal("50000")))
    assert breaker.is_latched(store) is True
    assert _live_enabled(store) is False  # trip disarmed it

    # Attempt to re-enable live while latched → REFUSED (interlock), live stays off.
    resp = toggle_router.toggle_live(ToggleRequest(enabled=True, confirm=True))
    assert resp.enabled is False
    assert resp.reason == "breaker latched — POST /ops/breaker/rearm first"
    assert _live_enabled(store) is False

    # Re-arm, then re-enabling live succeeds (the interlock is open).
    assert breaker.rearm(store) is True
    resp2 = toggle_router.toggle_live(ToggleRequest(enabled=True, confirm=True))
    assert resp2.enabled is True
    assert _live_enabled(store) is True


# --- config-kill flag ------------------------------------------------------------------------------

def test_breaker_disabled_flag(tmp_path):
    # breaker_enabled=False → trip() is a NO-OP even on a hard breach (config-kill without a deploy): assess still
    # reads the tier, but no disarm/liquidate/latch happens. The order path also never blocks (not latched).
    store = Store(Settings(
        database_url=f"sqlite:///{tmp_path}/breaker_off.sqlite3",
        risk=RiskSettings(breaker_enabled=False),
    ))
    _arm_live(store)
    _fund_held_track(store, version_id="sv-off", qty=Decimal("0.02"), avg_price=Decimal("50000"),
                     starting_capital=Decimal("1000"))
    _agg_snapshot(store, drawdown=Decimal("0.30"))

    verdict = breaker.assess(store)
    assert verdict.tier == "liquidate"  # assess still SENSES it
    assert breaker.trip(store, verdict.freeze_frame, catalog=CATALOG, router=_StubRouter(Decimal("50000"))) is False
    # No disarm, no liquidation, no latch.
    assert _live_enabled(store) is True
    assert breaker.is_latched(store) is False
    pf = Portfolio(store, bankroll=Decimal("100000"))
    pos = pf.position(_INSTRUMENT, "sim", strategy_version_id="sv-off")
    assert pos is not None and pos.qty == Decimal("0.02")  # position untouched


# --- freeze-frame payload shape --------------------------------------------------------------------

def test_freeze_frame_payload(tmp_path):
    # The black-box freeze-frame is a deterministic dict carrying every number that decided the tier, and is
    # logged verbatim on the breaker_tripped event (+ the liquidated/evaluated counts trip appends). latch_reason
    # reads it back.
    store = _store(tmp_path)
    _arm_live(store)
    _fund_held_track(store, version_id="sv-ff", qty=Decimal("0.02"), avg_price=Decimal("50000"),
                     starting_capital=Decimal("1000"))
    _agg_snapshot(store, drawdown=Decimal("0.30"))

    verdict = breaker.assess(store)
    ff = verdict.freeze_frame
    for key in ("at", "drawdown_pct", "daily_loss", "daily_loss_cap", "warn_drawdown_pct",
                "halt_drawdown_pct", "liquidate_drawdown_pct", "liquidate_daily_loss", "trigger"):
        assert key in ff, f"freeze-frame missing {key}"
    assert ff["trigger"] == "drawdown"
    assert Decimal(ff["drawdown_pct"]) == Decimal("0.30")

    breaker.trip(store, ff, catalog=CATALOG, router=_StubRouter(Decimal("50000")))
    latch = breaker.latch_reason(store)
    assert latch is not None
    assert latch["trigger"] == "drawdown"
    assert latch["liquidated"] == 1  # one holding reduce-only closed
    assert latch["evaluated"] == 1
    # Not latched → latch_reason is None (clean branch).
    breaker.rearm(store)
    assert breaker.latch_reason(store) is None
