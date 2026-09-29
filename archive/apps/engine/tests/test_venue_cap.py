# The Rules-modal per-venue hard cap, enforced deterministically in the gauntlet (master/risk.py). The check
# is purely additive: gated on a configured cap (None → skipped, today's behavior exactly), inside the
# non-reduce_only block so a close is never trapped, and a reject can NEVER push a venue past its limit.

from __future__ import annotations

from decimal import Decimal

from cosmu.config.settings import RiskSettings
from cosmu.master.risk import OrderIntent, PortfolioRiskState, validate_order_full
from cosmu.spine.venue import default_catalog

_CAT = default_catalog()
_VENUE = _CAT.venue("binance")
_INSTR = _CAT.instrument("BTCUSDT", "binance")
_RISK = RiskSettings()  # generous defaults (global 100k, per-strategy 10k) so only the venue cap can bite


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


def test_venue_cap_rejects_when_order_would_exceed_the_per_venue_limit():
    # $100 already deployed on the venue, a $100 order, a $150 cap → 200 > 150 → deterministic reject.
    d = validate_order_full(_entry("1"), _VENUE, _INSTR, _RISK,
                            _state(venue_open_notional=Decimal("100"), venue_max_notional=Decimal("150")))
    assert "venue_cap" in d.issues and not d.accepted


def test_venue_cap_allows_within_the_limit():
    d = validate_order_full(_entry("1"), _VENUE, _INSTR, _RISK,
                            _state(venue_open_notional=Decimal("40"), venue_max_notional=Decimal("150")))
    assert "venue_cap" not in d.issues and d.accepted


def test_no_venue_cap_when_unconfigured_is_todays_behavior():
    # venue_max_notional=None → the check is skipped entirely, even with huge prior deployment (regression guard
    # for the SIM/paper lane, which is never fed a per-venue cap).
    d = validate_order_full(_entry("1"), _VENUE, _INSTR, _RISK,
                            _state(venue_open_notional=Decimal("999999"), venue_max_notional=None))
    assert "venue_cap" not in d.issues


def test_reduce_only_close_is_exempt_from_venue_cap():
    # A genuine close (sell against a held long) is exempt — a venue cap must never trap an exit open.
    close = OrderIntent(symbol="BTCUSDT", side="sell", qty=Decimal("1"), price=Decimal("100"),
                        stop_loss=None, take_profit=None, conviction=Decimal("1"),
                        sizing_basis="equity_vol_conviction", reduce_only=True)
    d = validate_order_full(close, _VENUE, _INSTR, _RISK,
                            _state(existing_qty=Decimal("2"), venue_open_notional=Decimal("100"), venue_max_notional=Decimal("1")))
    assert "venue_cap" not in d.issues and d.accepted
