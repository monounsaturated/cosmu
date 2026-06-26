# The shared rotation-close (research/arm_rotation.py): a deploy-lane arm re-arming into new target holdings
# must CLOSE the stale legs first — at the latest real close, net of its own per-side fee — instead of stacking
# the new leg on top (the double-buy every arm had before). Offline legs defer honestly; nothing fabricates.

from __future__ import annotations

from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.master.portfolio import Portfolio
from cosmu.research.arm_rotation import close_stale_legs


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/rot.sqlite3", openrouter_api_key=None))


def _open(pf: Portfolio, symbol: str, qty: str, price: str, vid: str = "v1") -> None:
    pf.apply_fill(instrument_id=f"{symbol.lower()}-ibkr", symbol=symbol, venue="ibkr", side=1,
                  qty=Decimal(qty), price=Decimal(price), fee=Decimal("0.2"), strategy_version_id=vid)


def test_rotation_closes_stale_leg_and_books_real_pnl(tmp_path):
    store = _store(tmp_path)
    pf = Portfolio(store, bankroll=Decimal("100000"))
    _open(pf, "SPY", "2.5", "400")  # $1000 leg, rotated OUT this month

    result = close_stale_legs(
        store, pf, version_id="v1", keep_symbols={"AGG"},
        price_fn=lambda s: Decimal("420"), fee_per_side_bps=1.0,
    )

    assert [c["symbol"] for c in result["closed"]] == ["SPY"]
    pos = pf.position("spy-ibkr", "ibkr", strategy_version_id="v1")
    assert pos.qty == 0
    # +$20/share on 2.5 shares minus entry fee 0.2 + exit fee (1bp of 1050) — a REAL net win, booked.
    assert pos.realized_pnl > Decimal("49")
    assert store.row("SELECT id FROM events WHERE kind = 'rotation_closed'") is not None
    # FRONT-DISPLAY fix (audit 2026-06-26): a rotation SELL is a real paper trade and must write an `executions`
    # row so the trade-count + blotter ADVANCE on a real rebalance (not just `positions`). Idempotent, paper-only.
    fill = store.row("SELECT side, is_paper FROM executions WHERE strategy_version_id = 'v1'")
    assert fill is not None and fill["side"] == "sell" and int(fill["is_paper"]) == 1


def test_kept_legs_and_other_tracks_are_untouched(tmp_path):
    store = _store(tmp_path)
    pf = Portfolio(store, bankroll=Decimal("100000"))
    _open(pf, "SPY", "2.5", "400", vid="v1")   # stays (in keep set)
    _open(pf, "EFA", "10", "80", vid="v1")     # stale → closes
    _open(pf, "SPY", "1", "400", vid="v2")     # ANOTHER track's leg — never touched

    result = close_stale_legs(
        store, pf, version_id="v1", keep_symbols={"SPY"},
        price_fn=lambda s: Decimal("80"), fee_per_side_bps=1.0,
    )

    assert [c["symbol"] for c in result["closed"]] == ["EFA"]
    assert pf.position("spy-ibkr", "ibkr", strategy_version_id="v1").qty == Decimal("2.5")
    assert pf.position("spy-ibkr", "ibkr", strategy_version_id="v2").qty == Decimal("1")
    assert pf.position("efa-ibkr", "ibkr", strategy_version_id="v1").qty == 0


def test_offline_leg_defers_instead_of_fabricating_an_exit(tmp_path):
    store = _store(tmp_path)
    pf = Portfolio(store, bankroll=Decimal("100000"))
    _open(pf, "SPY", "2.5", "400")

    result = close_stale_legs(
        store, pf, version_id="v1", keep_symbols=set(),
        price_fn=lambda s: Decimal("0"), fee_per_side_bps=1.0,  # offline: no close fetchable
    )

    assert result["closed"] == [] and result["deferred"] == ["SPY"]
    assert pf.position("spy-ibkr", "ibkr", strategy_version_id="v1").qty == Decimal("2.5")


def test_noop_when_nothing_is_stale(tmp_path):
    store = _store(tmp_path)
    pf = Portfolio(store, bankroll=Decimal("100000"))
    _open(pf, "SPY", "2.5", "400")

    result = close_stale_legs(
        store, pf, version_id="v1", keep_symbols={"SPY"},
        price_fn=lambda s: Decimal("400"), fee_per_side_bps=1.0,
    )

    assert result == {"closed": [], "deferred": []}
