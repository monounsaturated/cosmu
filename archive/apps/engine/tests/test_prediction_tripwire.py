# The prediction-lane leakage gate (scout #385 Fix-C): a Polymarket cell's odds/resolution series MUST clear the
# standing leakage tripwire (research/leakage_tripwire.py) before the cell can be funded. Covers: a clean PIT
# odds series + a PIT-honest resolution passes; a future-peeking (look-ahead) odds series FAILS; a resolution
# stamped EARLIER than its real ts (a settlement look-ahead) FAILS. All pure/offline.

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cosmu.data.market import Bar
from cosmu.data.providers._types import AltDataPoint
from cosmu.research.leakage_tripwire import _synthetic_clean_feature, _synthetic_leaked_feature
from cosmu.research.prediction_tripwire import (
    audit_prediction_cell,
    resolution_pit_ok,
)

_RES_TS = datetime(2025, 3, 1, tzinfo=UTC)


def _resolution(value: float, *, available_at: datetime, ts: datetime = _RES_TS) -> AltDataPoint:
    return AltDataPoint(ts=ts, available_at=available_at, value=value)


# --------------------------------------------------------------------------- resolution PIT honesty

def test_resolution_pit_ok_clean_binary_stamped_at_resolution():
    # A clean $1 payout stamped at its real resolution time (available_at == ts) is PIT-honest.
    assert resolution_pit_ok([_resolution(1.0, available_at=_RES_TS)])
    assert resolution_pit_ok([_resolution(0.0, available_at=_RES_TS)])
    assert resolution_pit_ok([])  # no resolution yet → vacuously honest


def test_resolution_pit_fails_on_lookahead_availability():
    # available_at EARLIER than the real resolution ts = the outcome was 'knowable' before it happened — the
    # cardinal settlement look-ahead. MUST fail.
    early = _RES_TS - timedelta(days=5)
    assert not resolution_pit_ok([_resolution(1.0, available_at=early)])


def test_resolution_pit_fails_on_non_binary_payout():
    # A 0.62 'payout' is a still-trading mid-odds masquerading as a settlement — not a clean $1/$0. MUST fail.
    assert not resolution_pit_ok([_resolution(0.62, available_at=_RES_TS)])


# --------------------------------------------------------------------------- the bundled cell gate

def test_clean_odds_and_resolution_cell_passes():
    points, bars = _synthetic_clean_feature(seed=7)  # a genuinely PIT-honest, forward-predictive series
    result = audit_prediction_cell(
        condition_id="0xCLEAN", odds_points=points, bars=bars,
        resolution_points=[_resolution(1.0, available_at=_RES_TS)],
        metric="odds", shuffle_trials=60, seed=7,
    )
    assert result.passed, result.render()
    assert result.odds_report is not None and result.odds_report.passed
    assert result.resolution_pit_ok


def test_leaked_odds_cell_fails_the_tripwire():
    # The deliberately future-peeking control (bar t carries bar t+1's value): the forward-shift sanity catches
    # the baked-in look-ahead, so the cell is REFUSED funding.
    leaked, bars = _synthetic_leaked_feature(seed=7)
    result = audit_prediction_cell(
        condition_id="0xLEAK", odds_points=leaked, bars=bars,
        resolution_points=[_resolution(1.0, available_at=_RES_TS)],
        metric="odds", shuffle_trials=60, seed=7,
    )
    assert not result.passed
    assert "forward_shift_sanity" in (result.odds_report.failed_checks if result.odds_report else ())


def test_lookahead_resolution_cell_fails_even_with_clean_odds():
    # Clean odds, but the RESOLUTION point is stamped before its real ts → the settlement look-ahead fails the
    # cell as a whole, even though the odds tripwire passes.
    points, bars = _synthetic_clean_feature(seed=7)
    result = audit_prediction_cell(
        condition_id="0xRESLEAK", odds_points=points, bars=bars,
        resolution_points=[_resolution(1.0, available_at=_RES_TS - timedelta(days=3))],
        metric="odds", shuffle_trials=60, seed=7,
    )
    assert not result.passed
    assert "resolution_not_pit_honest" in result.reasons


def test_empty_odds_cell_is_refused():
    # No odds to audit → refuse rather than bless an empty cell.
    result = audit_prediction_cell(condition_id="0xEMPTY", odds_points=[], bars=[], resolution_points=[])
    assert not result.passed
    assert "no_odds_to_audit" in result.reasons


def _bar(ts: datetime, v: float) -> Bar:
    from decimal import Decimal
    px = Decimal(str(v))
    return Bar(ts=ts, open=px, high=px, low=px, close=px, volume=Decimal("1000"))
