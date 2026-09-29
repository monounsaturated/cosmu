# The SCHEDULED capital-guard watchdog (cosmu/orchestrator/loop.run_capital_guard_pass) — the wiring that makes the
# reduce-only drawdown / profit-lock supervisor actually RUN on every paper-clock cycle, instead of only when the
# operator hits the manual API kill-switch. These tests prove the SCHEDULED entrypoint (not run_capital_guard called
# by hand): a funded track whose OWN marked equity breaches the capital floor is auto-liquidated by the pass; a
# healthy track is left untouched; the pass is a clean no-op with nothing funded; a guard error can never crash the
# tick; and the human-arming interlock + the Gate are untouched by any of it. Offline: temp sqlite Store + a stub
# pricing router (no network), live OFF (every close reduce-fills the sim/paper book).

from __future__ import annotations

from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store, utcnow
from cosmu.master.portfolio import Portfolio
from cosmu.orchestrator import loop
from cosmu.spine.venue import default_catalog

CATALOG = default_catalog()
_INSTRUMENT = "btc-usdt-binance"
_SYMBOL = "BTCUSDT"
_VENUE = "binance"


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/guard_sched.sqlite3"))


class _StubRouter:
    """Deterministic pricing router: every symbol marks at `price` (no network). Mirrors PricingRouter.last_price."""

    def __init__(self, price: Decimal) -> None:
        self._price = price

    def last_price(self, symbol: str, venue: str) -> Decimal:  # noqa: ARG002
        return self._price


def _fund_track(
    store: Store, *, version_id: str, qty: Decimal, avg_price: Decimal, starting_capital: Decimal
) -> Portfolio:
    """Make a FUNDED, HELD (armed) track: a tracks row (the cell) + a real open long position on the sim book."""
    store.rows(
        "INSERT INTO strategies (id, name, thesis, origin, created_at) VALUES (?, ?, ?, ?, ?)",
        ("strat1", "guard-sched-test", "guard sched test", "test", utcnow()),
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
    return pf


def _snapshot(store: Store, *, version_id: str, equity: Decimal, ts: str) -> None:
    """Write one cell-keyed scope='track' marked-equity snapshot (ref_id = version:symbol:venue)."""
    store.insert(
        "portfolio_snapshots",
        {
            "scope": "track",
            "ref_id": f"{version_id}:{_SYMBOL}:{_VENUE}",
            "ts": ts,
            "equity": str(equity),
            "cash": "0.00",
            "positions_value": str(equity),
            "pnl": "0.00",
            "drawdown": "0.0000",
        },
    )


def test_scheduled_pass_auto_liquidates_a_drawdown_breach(tmp_path):
    # A funded/ARMED track whose marked equity (650) breaches the capital floor (1000 * 0.70 = 700) is
    # auto-LIQUIDATED by the SCHEDULED pass — the watchdog now disarms a breaching position on its own clock,
    # without any operator action.
    store = _store(tmp_path)
    qty = Decimal("0.02")
    _fund_track(store, version_id="sv-breach", qty=qty, avg_price=Decimal("50000"),
                starting_capital=Decimal("1000"))
    _snapshot(store, version_id="sv-breach", equity=Decimal("650"), ts=utcnow())

    out = loop.run_capital_guard_pass(store, catalog=CATALOG, router=_StubRouter(Decimal("32500")))

    assert out["evaluated"] == 1 and out["protected"] == 1
    # the position was flattened (whole position reduce-only closed) and audited as a capital_guard_action
    pf = Portfolio(store, bankroll=Decimal("100000"))
    pos = pf.position(_INSTRUMENT, "sim", strategy_version_id="sv-breach")
    assert pos is not None and pos.qty == Decimal("0")
    ev = store.row("SELECT payload FROM events WHERE kind = 'capital_guard_action'")
    assert ev is not None
    # SIM-only: the close routed to the sim book (no real money), since no venue is armed
    assert store.row("SELECT id FROM executions WHERE side = 'sell'") is not None


def test_scheduled_pass_leaves_a_healthy_track_untouched(tmp_path):
    # A healthy funded/ARMED track (well above the floor, no give-back) is NOT touched by the scheduled pass.
    store = _store(tmp_path)
    qty = Decimal("0.02")
    _fund_track(store, version_id="sv-healthy", qty=qty, avg_price=Decimal("50000"),
                starting_capital=Decimal("1000"))
    _snapshot(store, version_id="sv-healthy", equity=Decimal("1080"), ts=utcnow())

    out = loop.run_capital_guard_pass(store, catalog=CATALOG, router=_StubRouter(Decimal("54000")))

    assert out["protected"] == 0
    pf = Portfolio(store, bankroll=Decimal("100000"))
    pos = pf.position(_INSTRUMENT, "sim", strategy_version_id="sv-healthy")
    assert pos is not None and pos.qty == qty  # held, untouched
    assert store.row("SELECT id FROM events WHERE kind = 'capital_guard_action'") is None


def test_scheduled_pass_is_noop_with_nothing_funded(tmp_path):
    # Zero funded/armed tracks → a clean no-op: nothing evaluated, nothing protected, no order path touched.
    store = _store(tmp_path)
    out = loop.run_capital_guard_pass(store, catalog=CATALOG, router=_StubRouter(Decimal("65000")))
    assert out["evaluated"] == 0 and out["protected"] == 0
    assert store.row("SELECT id FROM events WHERE kind = 'capital_guard_action'") is None
    assert store.row("SELECT id FROM executions") is None


def test_scheduled_pass_can_be_disabled_by_flag(tmp_path, monkeypatch):
    # COSMU_CAPITAL_GUARD_ENABLED=0 is a cadence knob only: the breaching track is left for the next pass, the
    # order path is never touched, and the MANUAL API kill-switch is unaffected (it does not read this flag).
    store = _store(tmp_path)
    _fund_track(store, version_id="sv-flag", qty=Decimal("0.02"), avg_price=Decimal("50000"),
                starting_capital=Decimal("1000"))
    _snapshot(store, version_id="sv-flag", equity=Decimal("650"), ts=utcnow())  # would breach if it ran
    monkeypatch.setenv("COSMU_CAPITAL_GUARD_ENABLED", "0")

    out = loop.run_capital_guard_pass(store, catalog=CATALOG, router=_StubRouter(Decimal("32500")))

    assert out["protected"] == 0 and out.get("skipped") == 1
    pf = Portfolio(store, bankroll=Decimal("100000"))
    assert pf.position(_INSTRUMENT, "sim", strategy_version_id="sv-flag").qty == Decimal("0.02")  # untouched


def test_scheduled_pass_never_crashes_the_tick(tmp_path):
    # A guard error must NEVER crash the marking tick: an exploding router is swallowed (fail-safe skip), audited
    # as capital_guard_failed, and the pass returns a clean skipped report rather than propagating.
    store = _store(tmp_path)
    _fund_track(store, version_id="sv-boom", qty=Decimal("0.02"), avg_price=Decimal("50000"),
                starting_capital=Decimal("1000"))
    _snapshot(store, version_id="sv-boom", equity=Decimal("650"), ts=utcnow())

    class _BoomRouter:
        def last_price(self, symbol, venue):  # noqa: ANN001, ARG002
            raise RuntimeError("pricing source exploded")

    out = loop.run_capital_guard_pass(store, catalog=CATALOG, router=_BoomRouter())

    assert out["protected"] == 0 and out.get("skipped") == 1
    assert store.row("SELECT id FROM events WHERE kind = 'capital_guard_failed'") is not None


def test_scheduled_pass_does_not_arm_live_or_touch_the_interlock(tmp_path):
    # SAFETY INVARIANT: the watchdog only PROTECTS. It never arms live, never flips the live_toggle interlock, and
    # never deploys/opens capital — even when it liquidates a breaching track. The human-arming interlock is read
    # exactly as it was (default OFF) before AND after the pass.
    from cosmu.master.scheduler import _live_enabled

    store = _store(tmp_path)
    _fund_track(store, version_id="sv-interlock", qty=Decimal("0.02"), avg_price=Decimal("50000"),
                starting_capital=Decimal("1000"))
    _snapshot(store, version_id="sv-interlock", equity=Decimal("650"), ts=utcnow())  # a breach the pass will close

    assert _live_enabled(store) is False  # interlock OFF before
    out = loop.run_capital_guard_pass(store, catalog=CATALOG, router=_StubRouter(Decimal("32500")))
    assert out["protected"] == 1  # it DID protect (liquidate)
    assert _live_enabled(store) is False  # interlock STILL OFF after — the guard never arms anything

    # and the close routed SIM (no real order): the audited action carries routed_live False / venue 'sim'
    import json

    ev = store.row("SELECT payload FROM events WHERE kind = 'capital_guard_action'")
    payload = json.loads(ev["payload"]) if isinstance(ev["payload"], str) else ev["payload"]
    assert payload["routed_live"] is False and payload["venue"] == "sim"
