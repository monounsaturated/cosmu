"""fillability.py — the honest filter. Synthetic candidates exercise every classification deterministically."""

from __future__ import annotations

from datetime import date

from cosmu.options.chain import OptionQuote
from cosmu.options.fillability import (
    MAKER_ONLY,
    MIRAGE,
    NO_SIZE,
    RISK_PREMIUM,
    RISKLESS_LOCK,
    FillabilityModel,
)
from cosmu.options.scanner import KIND_ARB, KIND_PREMIUM, Candidate, Leg

_INDEX = 1000.0


def _q(instrument, bid, ask, *, bid_size=None, ask_size=None, strike=1000.0, is_call=True, mark_iv=44.0):
    mid = (bid + ask) / 2 if (bid is not None and ask is not None) else None
    return OptionQuote(
        instrument=instrument, currency="BTC", expiry=date(2026, 7, 3), strike=strike, is_call=is_call,
        bid_price=bid, ask_price=ask, mark_price=mid, mark_iv=mark_iv, open_interest=10.0, volume=1.0,
        underlying_price=_INDEX, bid_size=bid_size, ask_size=ask_size,
    )


def _cand(legs, mid_edge, kind=KIND_ARB):
    return Candidate(camper="t", kind=kind, description="t", legs=tuple(legs), mid_edge_usd=mid_edge)


def test_no_size_when_legs_not_enriched():
    legs = [Leg(_q("A", 0.049, 0.051), "BUY"), Leg(_q("B", 0.069, 0.071), "SELL")]
    v = FillabilityModel().assess(_cand(legs, 20.0), _INDEX)
    assert v.classification == NO_SIZE and not v.is_real


def test_riskless_lock_when_taker_positive():
    legs = [Leg(_q("A", 0.049, 0.051, bid_size=10, ask_size=10), "BUY"),
            Leg(_q("B", 0.069, 0.071, bid_size=10, ask_size=10), "SELL")]
    v = FillabilityModel().assess(_cand(legs, 20.0), _INDEX)
    assert v.classification == RISKLESS_LOCK and v.is_real
    assert v.taker_edge_usd > 0 and v.max_units == 10.0


def test_maker_only_single_leg_is_confirmed():
    legs = [Leg(_q("A", 0.01, 0.09, bid_size=5, ask_size=5), "BUY")]
    v = FillabilityModel().assess(_cand(legs, 2.0), _INDEX)
    assert v.classification == MAKER_ONLY and v.is_real
    assert v.taker_edge_usd < 0 < v.maker_edge_usd  # only resting captures it


def test_maker_only_multileg_needs_allow_legging():
    legs = [Leg(_q("A", 0.01, 0.09, bid_size=5, ask_size=5), "BUY"),
            Leg(_q("B", 0.01, 0.09, bid_size=5, ask_size=5, strike=1100.0), "SELL")]
    cand = _cand(legs, 2.0)
    strict = FillabilityModel().assess(cand, _INDEX)
    assert strict.classification == MAKER_ONLY and not strict.is_real  # legging risk by default
    lax = FillabilityModel(allow_legging=True).assess(cand, _INDEX)
    assert lax.classification == MAKER_ONLY and lax.is_real
    assert lax.capacity_usd > 0


def test_mirage_when_edge_below_floor_after_costs():
    legs = [Leg(_q("A", 0.0549, 0.0551, bid_size=5, ask_size=5), "BUY")]
    v = FillabilityModel().assess(_cand(legs, 0.5), _INDEX)
    assert v.classification == MIRAGE and not v.is_real


def test_premium_is_never_a_lock():
    legs = [Leg(_q("A", 0.05, 0.06, bid_size=5, ask_size=5), "SELL")]
    v = FillabilityModel().assess(_cand(legs, 60.0, kind=KIND_PREMIUM), _INDEX)
    assert v.classification == RISK_PREMIUM and not v.is_real


def test_zero_index_cannot_be_valued():
    legs = [Leg(_q("A", 0.01, 0.09, bid_size=5, ask_size=5), "BUY")]
    v = FillabilityModel().assess(_cand(legs, 2.0), 0.0)
    assert v.classification == MIRAGE and not v.is_real
