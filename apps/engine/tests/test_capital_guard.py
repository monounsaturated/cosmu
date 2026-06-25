# The capital-protection supervisor (cosmu/ops/capital_guard.py): a funded track whose OWN marked equity falls to
# the floor is LIQUIDATED via a reduce-only close; one that gives back from its peak is TRIMMED (profit-lock); and
# with no funded/held tracks the pass is a clean NO-OP. Offline: temp sqlite Store + a stub pricing router (no
# network), live OFF (every close reduce-fills the sim/paper book — the same mechanics the paper executor uses).

from __future__ import annotations

from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store, utcnow
from cosmu.master.portfolio import Portfolio
from cosmu.ops import capital_guard
from cosmu.ops.capital_guard import GuardConfig
from cosmu.spine.venue import default_catalog

CATALOG = default_catalog()
_INSTRUMENT = "btc-usdt-binance"
_SYMBOL = "BTCUSDT"
_VENUE = "binance"


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/guard.sqlite3"))


class _StubRouter:
    """A deterministic pricing router: every symbol marks at `price` (no network). Mirrors PricingRouter.last_price."""

    def __init__(self, price: Decimal) -> None:
        self._price = price

    def last_price(self, symbol: str, venue: str) -> Decimal:  # noqa: ARG002
        return self._price


def _fund_track(
    store: Store, *, version_id: str, qty: Decimal, avg_price: Decimal, starting_capital: Decimal
) -> Portfolio:
    """Make a FUNDED, HELD track: a tracks row (the cell) + a real open long position on the sim book."""
    store.rows(
        "INSERT INTO strategies (id, name, thesis, origin, created_at) VALUES (?, ?, ?, ?, ?)",
        ("strat1", "guard-test", "guard test", "test", utcnow()),
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


def test_noop_with_no_tracks(tmp_path):
    # Zero funded tracks → a clean no-op: nothing evaluated, nothing protected, no order path touched.
    store = _store(tmp_path)
    report = capital_guard.run_capital_guard(store, catalog=CATALOG, router=_StubRouter(Decimal("65000")))
    assert report.evaluated == 0 and report.protected == 0 and report.actions == []
    assert store.row("SELECT id FROM events WHERE kind = 'capital_guard_action'") is None
    assert store.row("SELECT id FROM executions") is None


def test_noop_when_track_is_flat(tmp_path):
    # A funded track with NO open position has no exposure to protect → no-op even with a marked-equity series.
    store = _store(tmp_path)
    _fund_track(store, version_id="sv-flat", qty=Decimal("0.01"), avg_price=Decimal("60000"),
                starting_capital=Decimal("1000"))
    # close the position back to flat
    pf = Portfolio(store, bankroll=Decimal("100000"))
    pf.apply_fill(instrument_id=_INSTRUMENT, symbol=_SYMBOL, venue="sim", side=-1,
                  qty=Decimal("0.01"), price=Decimal("30000"), fee=Decimal("0"), strategy_version_id="sv-flat")
    _snapshot(store, version_id="sv-flat", equity=Decimal("300"), ts=utcnow())
    report = capital_guard.run_capital_guard(store, catalog=CATALOG, router=_StubRouter(Decimal("30000")))
    assert report.evaluated == 0 and report.protected == 0


def test_liquidates_at_capital_floor(tmp_path):
    # Equity 650 vs starting_capital 1000 → at/below the 0.70 floor (700) → FULL liquidation via reduce-only.
    store = _store(tmp_path)
    qty = Decimal("0.02")
    _fund_track(store, version_id="sv-floor", qty=qty, avg_price=Decimal("50000"),
                starting_capital=Decimal("1000"))
    _snapshot(store, version_id="sv-floor", equity=Decimal("650"), ts=utcnow())
    report = capital_guard.run_capital_guard(store, catalog=CATALOG, router=_StubRouter(Decimal("32500")))
    assert report.protected == 1
    action = report.actions[0]
    assert action["kind"] == "liquidate" and action["reason"] == "capital_floor"
    assert action["routed_live"] is False and action["venue"] == "sim"
    # the audit event fired
    assert store.row("SELECT id FROM events WHERE kind = 'capital_guard_action'") is not None
    # a reduce-only SELL execution booked, and the position is now FLAT (whole position liquidated)
    assert store.row("SELECT id FROM executions WHERE side = 'sell'") is not None
    pf = Portfolio(store, bankroll=Decimal("100000"))
    pos = pf.position(_INSTRUMENT, "sim", strategy_version_id="sv-floor")
    assert pos is not None and pos.qty == Decimal("0")


def test_trims_on_profit_lock_giveback(tmp_path):
    # Peak 1400 (+40% over starting 1000), now back to 1000 → gave back (1400-1000)/1400 = 28.6% (> 25%) → TRIM.
    store = _store(tmp_path)
    qty = Decimal("0.02")
    _fund_track(store, version_id="sv-lock", qty=qty, avg_price=Decimal("50000"),
                starting_capital=Decimal("1000"))
    _snapshot(store, version_id="sv-lock", equity=Decimal("1400"), ts="2026-06-20T00:00:00+00:00")  # the peak
    _snapshot(store, version_id="sv-lock", equity=Decimal("1000"), ts="2026-06-24T00:00:00+00:00")  # now
    report = capital_guard.run_capital_guard(store, catalog=CATALOG, router=_StubRouter(Decimal("50000")))
    assert report.protected == 1
    action = report.actions[0]
    assert action["kind"] == "trim" and action["reason"] == "profit_lock"
    # half the position sold (trim_fraction default 0.50), the rest still held
    pf = Portfolio(store, bankroll=Decimal("100000"))
    pos = pf.position(_INSTRUMENT, "sim", strategy_version_id="sv-lock")
    assert pos is not None and pos.qty == Decimal("0.01")  # 0.02 * 0.50 sold


def test_no_action_when_healthy(tmp_path):
    # Above the floor and not given back from peak → no protective action.
    store = _store(tmp_path)
    _fund_track(store, version_id="sv-ok", qty=Decimal("0.02"), avg_price=Decimal("50000"),
                starting_capital=Decimal("1000"))
    _snapshot(store, version_id="sv-ok", equity=Decimal("1100"), ts="2026-06-20T00:00:00+00:00")
    _snapshot(store, version_id="sv-ok", equity=Decimal("1080"), ts="2026-06-24T00:00:00+00:00")
    report = capital_guard.run_capital_guard(store, catalog=CATALOG, router=_StubRouter(Decimal("54000")))
    assert report.protected == 0 and report.actions == []


def test_floor_disabled_is_respected(tmp_path):
    # Config-driven: floor_fraction=None disables the capital-preservation guard entirely.
    store = _store(tmp_path)
    _fund_track(store, version_id="sv-nofloor", qty=Decimal("0.02"), avg_price=Decimal("50000"),
                starting_capital=Decimal("1000"))
    _snapshot(store, version_id="sv-nofloor", equity=Decimal("400"), ts=utcnow())  # well below any floor
    cfg = GuardConfig(floor_fraction=None, giveback_fraction=None)
    report = capital_guard.run_capital_guard(
        store, catalog=CATALOG, router=_StubRouter(Decimal("20000")), config=cfg
    )
    assert report.protected == 0
