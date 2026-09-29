# The operator's LIVE caps (Rules modal: global pool "$ hard blocker", per-strategy live cap, daily-loss) are
# now ENFORCED in the order gauntlet — not just displayed. Mirrors test_venue_cap: additive + gated (None →
# skipped, SIM/paper lane unconstrained), measured against LIVE-book exposure only, closes exempt. The wiring
# (execute_orders reading live_caps + settings.live) is covered end-to-end at the bottom.

from __future__ import annotations

from decimal import Decimal

from cosmu.config.settings import RiskSettings, Settings
from cosmu.core.interfaces import AssetClass
from cosmu.knowledge.store import Store
from cosmu.master.execution import (
    IntendedOrder,
    _live_open_notional,
    _operator_live_caps,
    execute_orders,
)
from cosmu.master.portfolio import Portfolio
from cosmu.master.risk import OrderIntent, PortfolioRiskState, validate_order_full
from cosmu.spine.venue import default_catalog

_CAT = default_catalog()
_VENUE = _CAT.venue("binance")
_INSTR = _CAT.instrument("BTCUSDT", "binance")
_RISK = RiskSettings()  # generous static defaults (global 100k, per-strategy 10k) so only the LIVE caps bite


def _entry(qty: str, price: str = "100") -> OrderIntent:
    return OrderIntent(
        symbol="BTCUSDT", side="buy", qty=Decimal(qty), price=Decimal(price),
        stop_loss=Decimal("90"), take_profit=Decimal("110"), conviction=Decimal("1"),
        sizing_basis="equity_vol_conviction",
    )


def _state(**kw) -> PortfolioRiskState:
    base = dict(equity=Decimal("100000"), cash=Decimal("100000"))
    base.update(kw)
    return PortfolioRiskState(**base)


# ── gauntlet checks (unit) ──────────────────────────────────────────────────

def test_global_live_cap_rejects_when_live_exposure_would_exceed_it():
    # $40 already on live books, a $100 order, a $120 operator global cap → 140 > 120 → reject.
    d = validate_order_full(_entry("1"), _VENUE, _INSTR, _RISK,
                            _state(live_open_notional=Decimal("40"), global_live_max_notional=Decimal("120")))
    assert "global_live_cap" in d.issues and not d.accepted


def test_global_live_cap_allows_within_the_limit():
    d = validate_order_full(_entry("1"), _VENUE, _INSTR, _RISK,
                            _state(live_open_notional=Decimal("40"), global_live_max_notional=Decimal("500")))
    assert "global_live_cap" not in d.issues and d.accepted


def test_per_strategy_live_cap_rejects_when_this_strategys_live_exposure_would_exceed_it():
    d = validate_order_full(_entry("1"), _VENUE, _INSTR, _RISK,
                            _state(strategy_live_open_notional=Decimal("60"), per_strategy_live_max_notional=Decimal("120")))
    assert "per_strategy_live_cap" in d.issues and not d.accepted


def test_no_live_caps_when_unconfigured_is_todays_behavior():
    # None → both checks skipped, even with huge prior live deployment (the SIM/paper lane, never fed live caps).
    d = validate_order_full(_entry("1"), _VENUE, _INSTR, _RISK,
                            _state(live_open_notional=Decimal("9e9"), strategy_live_open_notional=Decimal("9e9")))
    assert "global_live_cap" not in d.issues and "per_strategy_live_cap" not in d.issues


def test_reduce_only_close_is_exempt_from_live_caps():
    close = OrderIntent(symbol="BTCUSDT", side="sell", qty=Decimal("1"), price=Decimal("100"),
                        stop_loss=None, take_profit=None, conviction=Decimal("1"),
                        sizing_basis="equity_vol_conviction", reduce_only=True)
    d = validate_order_full(close, _VENUE, _INSTR, _RISK,
                            _state(existing_qty=Decimal("2"), live_open_notional=Decimal("9e9"),
                                   global_live_max_notional=Decimal("1"), per_strategy_live_max_notional=Decimal("1")))
    assert "global_live_cap" not in d.issues and "per_strategy_live_cap" not in d.issues and d.accepted


# ── helpers (unit) ──────────────────────────────────────────────────────────

class _Pos:
    def __init__(self, venue, qty, avg_price, svid):
        self.venue, self.qty, self.avg_price, self.strategy_version_id = venue, Decimal(qty), Decimal(avg_price), svid


class _PF:
    def __init__(self, positions):
        self._p = positions

    def positions(self):
        return self._p


def test_live_open_notional_counts_only_live_books():
    pf = _PF([_Pos("live", "2", "100", "A"), _Pos("sim", "5", "100", "A"),
              _Pos("ibkr", "3", "100", "A"), _Pos("testnet", "1", "50", "B")])
    assert _live_open_notional(pf) == Decimal("250")  # live 2*100 + testnet 1*50; sim + ibkr (paper) excluded
    assert _live_open_notional(pf, strategy_version_id="A") == Decimal("200")  # only A's live exposure


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/caps.sqlite3", openrouter_api_key=None))


def test_operator_live_caps_are_gated_on_the_armed_row(tmp_path):
    store = _store(tmp_path)
    live = store.settings.live
    # No row (operator hasn't armed via the Rules modal) → ALL None → no live cap enforced (today's behavior).
    assert _operator_live_caps(store) == (None, None, None)
    # The operator's global row → its max_notional + max_daily_loss; per-strategy from settings.
    store.rows("INSERT INTO live_caps(id, scope, ref_id, max_notional, max_daily_loss) VALUES ('global','pool','global',?,?)",
               ("321", "77"))
    g, d, p = _operator_live_caps(store)
    assert g == Decimal("321") and d == Decimal("77") and p == live.per_strategy_live_cap


# ── wiring (integration through execute_orders) ─────────────────────────────

class _ActiveAdapter:
    asset_class = AssetClass.CRYPTO
    venue = "binance"
    mode = "live"
    active = True

    def __init__(self):
        self.submitted: list = []

    def submit(self, order):
        self.submitted.append(order)


def _order() -> IntendedOrder:
    return IntendedOrder(
        strategy_version_id="cap-test", symbol="BTCUSDT", venue_id="binance", side=1,
        qty=Decimal("1"), price=Decimal("100"), stop_loss=Decimal("90"), take_profit=Decimal("110"),
        conviction=Decimal("0.5"), gate_passed=True, order_type="market", client_order_id="coid-cap-1",
    )


def test_execute_orders_enforces_operator_global_cap_only_when_live_armed(tmp_path):
    store = _store(tmp_path)
    # Operator global cap $50; a $100 live order from a flat live book → 0 + 100 > 50 → rejected, no submit.
    store.rows("INSERT INTO live_caps(id, scope, ref_id, max_notional, max_daily_loss) VALUES ('global','pool','global',?,?)",
               ("50", "1000"))
    pf = Portfolio(store, bankroll=Decimal("100000"))
    adapter = _ActiveAdapter()
    live = execute_orders([_order()], live_enabled=True, kill_switch=False, adapter=adapter,
                          store=store, portfolio=pf, risk=store.settings.risk, catalog=_CAT)
    assert not live[0].accepted and "global_live_cap" in live[0].issues
    assert adapter.submitted == []  # rejected by the gauntlet BEFORE any real submit

    # Same order with live OFF → the live cap is never threaded → it is not what blocks it (SIM lane unconstrained).
    sim = execute_orders([_order()], live_enabled=False, kill_switch=False, adapter=adapter,
                         store=store, portfolio=pf, risk=store.settings.risk, catalog=_CAT)
    assert "global_live_cap" not in sim[0].issues
