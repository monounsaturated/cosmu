# The honest alt-data correlation engine: PIT information coefficients, FDR-controlled, propose-only.

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.data.market import Bar
from cosmu.research.correlation_scan import _forward_returns, spearman_ic


def test_spearman_ic_perfect_and_noise():
    xs = [float(i) for i in range(60)]
    ic, p, n = spearman_ic(xs, [x * 3 - 5 for x in xs])  # perfectly monotone
    assert ic == 1.0 and p == 0.0 and n == 60
    ic2, _, _ = spearman_ic(xs, list(reversed(xs)))       # perfectly anti-monotone
    assert ic2 == -1.0


def test_spearman_ic_fails_closed_on_thin_or_degenerate():
    assert spearman_ic([1, 2, 3], [1, 2, 3]) == (0.0, 1.0, 3)        # n<10 → fail-closed
    assert spearman_ic([1.0] * 20, list(range(20))) == (0.0, 1.0, 20)  # zero variance → fail-closed


def test_forward_returns_are_strictly_future_no_lookahead():
    t0 = datetime(2020, 1, 1, tzinfo=UTC)
    bars = [Bar(ts=t0 + timedelta(days=i), open=Decimal("1"), high=Decimal("1"), low=Decimal("1"),
                close=Decimal(str(100 + i)), volume=Decimal("0")) for i in range(10)]
    fwd = _forward_returns(bars, horizon=2)
    # the forward return at bar i uses close[i+2]/close[i] — strictly future; last `horizon` bars have no entry.
    assert fwd[bars[0].ts.isoformat()] == (102 / 100) - 1.0
    assert bars[-1].ts.isoformat() not in fwd and bars[-2].ts.isoformat() not in fwd
    assert len(fwd) == 8
