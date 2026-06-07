# The regime classifier done RIGHT: NO-REPAINT (appending future bars never rewrites a past label — the trap the
# retail "hedge-fund Markov" hype falls into), STATIONARY trailing features, STRIDE-SAMPLED transition matrix (so
# the diagonal measures real persistence, not window-autocorrelation), deterministic, and honest on thin data.

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.data.market import Bar
from cosmu.research.regime import (
    BEAR,
    BULL,
    RegimeConfig,
    regime_points,
    regime_states,
    transition_matrix,
)


def _bars(closes: list[float]) -> list[Bar]:
    t0 = datetime(2020, 1, 1, tzinfo=UTC)
    out = []
    for i, c in enumerate(closes):
        d = Decimal(str(c))
        out.append(Bar(ts=t0 + timedelta(days=i), open=d, high=d, low=d, close=d, volume=Decimal("1")))
    return out


def _trend(n: int, daily: float, start: float = 100.0) -> list[float]:
    """A deterministic compounding trend (daily drift), with a tiny fixed wiggle so vol > 0."""
    closes, p = [], start
    for i in range(n):
        p *= 1 + daily + (0.002 if i % 2 == 0 else -0.002)
        closes.append(p)
    return closes


_CFG = RegimeConfig(window=20, min_dwell=5)


def test_no_repaint_appending_future_bars_never_changes_past_labels():
    """THE invariant: regime_states(bars[:k]) must equal regime_states(bars)[:k] for every k — a past label is
    computed from past bars ONLY, so it can't be rewritten by data that arrives later."""
    closes = _trend(120, 0.01) + _trend(120, -0.01, start=_trend(120, 0.01)[-1])  # bull then bear
    bars = _bars(closes)
    full = [s.state for s in regime_states(bars, _CFG)]
    assert len(full) > 50
    for k in range(_CFG.warmup + 10, len(bars), 7):
        prefix = [s.state for s in regime_states(bars[:k], _CFG)]
        assert prefix == full[: len(prefix)], f"repaint at k={k}: label history changed when future bars appended"


def test_mutating_a_future_close_cannot_change_a_past_label():
    """Causality, directly: changing the LAST bar's close must not alter any earlier label."""
    bars = _bars(_trend(100, 0.008))
    before = [s.state for s in regime_states(bars, _CFG)]
    bars[-1] = Bar(ts=bars[-1].ts, open=Decimal("1"), high=Decimal("1"), low=Decimal("1"),
                   close=Decimal("1"), volume=Decimal("1"))  # violent future move
    after = [s.state for s in regime_states(bars, _CFG)]
    assert before[:-1] == after[:-1]  # every label before the mutated bar is unchanged


def test_classifies_strong_uptrend_bull_and_downtrend_bear():
    bull_states = {s.state for s in regime_states(_bars(_trend(120, 0.015)), _CFG)}
    bear_states = {s.state for s in regime_states(_bars(_trend(120, -0.015)), _CFG)}
    assert BULL in bull_states and BEAR not in bull_states
    assert BEAR in bear_states and BULL not in bear_states


def _oscillating(blocks: int, block_len: int, daily: float) -> list[float]:
    """Alternating bull/bear blocks (each many bars long) so the regime genuinely flips several times while each
    state persists in long runs — the exact shape where overlapping daily labels inflate the diagonal."""
    closes, p = [], 100.0
    for b in range(blocks):
        d = daily if b % 2 == 0 else -daily
        for i in range(block_len):
            p *= 1 + d + (0.002 if i % 2 == 0 else -0.002)
            closes.append(p)
    return closes


def test_stride_sampling_avoids_diagonal_inflation_from_overlap():
    """Overlapping daily labels (stride=1) share window-1 bars → their diagonal is inflated by window-
    autocorrelation (a long state-run is counted as ~block_len self-transitions). Stride=window samples disjoint
    windows → far fewer self-transitions relative to the real flips → a lower, HONEST persistence."""
    states = regime_states(_bars(_oscillating(8, 60, 0.012)), _CFG)
    overlap = transition_matrix(states, RegimeConfig(window=20, min_dwell=5, stride=1))
    disjoint = transition_matrix(states, RegimeConfig(window=20, min_dwell=5))  # stride defaults to window
    diag_overlap = (overlap[0][0] + overlap[1][1] + overlap[2][2]) / 3
    diag_disjoint = (disjoint[0][0] + disjoint[1][1] + disjoint[2][2]) / 3
    assert diag_overlap > diag_disjoint  # overlap manufactures persistence the stride-sampling removes


def test_transition_matrix_rows_are_stochastic():
    states = regime_states(_bars(_trend(200, 0.005) + _trend(200, -0.005)), _CFG)
    for row in transition_matrix(states, _CFG):
        assert math.isclose(sum(row), 1.0, abs_tol=1e-9)
        assert all(0.0 <= x <= 1.0 for x in row)


def test_deterministic():
    bars = _bars(_trend(150, 0.007))
    a = [(s.state, s.z) for s in regime_states(bars, _CFG)]
    b = [(s.state, s.z) for s in regime_states(bars, _CFG)]
    assert a == b


def test_available_at_is_lagged_strictly_prior():
    """Each label is USABLE only from the next bar — a bar's exposure is sized from a strictly-prior regime read."""
    states = regime_states(_bars(_trend(80, 0.006)), _CFG)
    for s in states:
        assert s.available_at > s.ts


def test_regime_points_value_range_and_thin_data_abstains():
    pts = regime_points(_bars(_trend(80, 0.006)), _CFG)
    assert all(p.value in (0.0, 0.5, 1.0) for p in pts)
    assert regime_states(_bars(_trend(5, 0.01)), _CFG) == []  # < warmup → abstain, never fabricate
