"""campers.py + scanner.py — the three example campers on SYNTHETIC chains, then run_scan end-to-end (a real
confirmed lock survives, a mirage is filtered)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from cosmu.options.campers import (
    PutCallParityCamper,
    VerticalArbCamper,
    VolRiskPremiumCamper,
    default_campers,
)
from cosmu.options.chain import ChainSnapshot, OptionQuote
from cosmu.options.fillability import RISKLESS_LOCK, FillabilityModel
from cosmu.options.scanner import run_scan

_INDEX = 1000.0
_EXP = date(2026, 7, 3)


def _q(strike, is_call, bid, ask, *, bid_size=10.0, ask_size=10.0, mark_iv=44.0, forward=_INDEX):
    name = f"BTC-3JUL26-{strike:g}-{'C' if is_call else 'P'}"
    mid = (bid + ask) / 2
    return OptionQuote(
        instrument=name, currency="BTC", expiry=_EXP, strike=float(strike), is_call=is_call,
        bid_price=bid, ask_price=ask, mark_price=mid, mark_iv=mark_iv, open_interest=10.0, volume=1.0,
        underlying_price=forward, bid_size=bid_size, ask_size=ask_size,
    )


def _chain(quotes, *, dvol=45.0):
    return ChainSnapshot(capture_ts=datetime(2026, 6, 29, tzinfo=UTC), currency="BTC",
                         index_price=_INDEX, dvol=dvol, quotes=tuple(quotes))


def test_vertical_camper_finds_monotonicity_arb():
    # higher-strike call priced ABOVE the lower-strike call → static arb
    chain = _chain([_q(1000, True, 0.049, 0.051), _q(1100, True, 0.069, 0.071)])
    cands = VerticalArbCamper().scan(chain)
    assert len(cands) == 1
    c = cands[0]
    assert abs(c.mid_edge_usd - 20.0) < 1e-6  # (0.07 - 0.05) * index
    assert {leg.side for leg in c.legs} == {"BUY", "SELL"}
    assert c.detail["type"] == "monotonicity"


def test_vertical_camper_silent_on_clean_chain():
    # calls monotone-decreasing in strike, spread within bounds → no violation
    chain = _chain([_q(1000, True, 0.069, 0.071), _q(1100, True, 0.049, 0.051)])
    assert VerticalArbCamper().scan(chain) == []


def test_parity_camper_finds_residual():
    # K=900, forward=1000 → parity expects C−P = 0.1 coin; we set C−P = 0.11 → residual ≈ $10
    call = _q(900, True, 0.155, 0.165, forward=1000.0)
    put = _q(900, False, 0.045, 0.055, forward=1000.0)
    cands = PutCallParityCamper().scan(_chain([call, put]))
    assert len(cands) == 1
    assert abs(cands[0].mid_edge_usd - 10.0) < 1e-6
    assert cands[0].detail["requires_future_hedge"] == "BUY future"


def test_parity_camper_silent_when_parity_holds():
    call = _q(900, True, 0.145, 0.155, forward=1000.0)  # C−P = 0.10 = (F−K)/S → residual 0
    put = _q(900, False, 0.045, 0.055, forward=1000.0)
    assert PutCallParityCamper().scan(_chain([call, put])) == []


def test_vrp_camper_needs_context_and_clears_threshold():
    chain = _chain([_q(1000, True, 0.05, 0.06, mark_iv=60.0)])
    camper = VolRiskPremiumCamper(min_vrp_points=5.0)
    assert camper.scan(chain) == []                                   # no context → no RV → silent
    assert camper.scan(chain, context={"realized_vol": 58.0}) == []   # +2 vol pts < threshold
    hot = camper.scan(chain, context={"realized_vol": 40.0})          # +20 vol pts → fire
    assert len(hot) == 1 and hot[0].kind == "PREMIUM"


def test_run_scan_confirms_lock_and_filters_mirage():
    chain = _chain([
        _q(1000, True, 0.049, 0.051), _q(1100, True, 0.069, 0.071),  # vertical arb, tight → confirmable LOCK
        _q(2000, True, 0.0549, 0.0551), _q(2100, True, 0.0548, 0.0552),  # near-equal → tiny edge → mirage
    ])
    opps = run_scan(chain, default_campers(), FillabilityModel())
    confirmed = [o for o in opps if o.is_real]
    assert any(o.verdict.classification == RISKLESS_LOCK for o in confirmed)
    # confirmed_only returns the same short-list
    assert run_scan(chain, default_campers(), FillabilityModel(), confirmed_only=True) == \
        [o for o in opps if o.is_real]
    # sorted by capacity (most capturable first)
    caps = [o.verdict.capacity_usd for o in opps]
    assert caps == sorted(caps, reverse=True)
