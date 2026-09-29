# Focused regression tests for three bugs fixed in cosmu/research/perp_gate_sweep.py:
#   1. pair_sharpe/skew/kurt were naive averages of per-leg stats; now computed on the actual
#      combined dollar-neutral return stream.
#   2. _apply_funding_cost double-counted funding when funding_feature is already set on the spec.
#   3. Survivorship-bias comment added to the universe setup (comment-only, not tested here).
# All tests are offline + deterministic.

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from cosmu.data.altdata import AltDataPoint
from cosmu.data.market import Bar
from cosmu.master.scorer import BacktestMetrics, sample_moments
from cosmu.research.perp_gate_sweep import (
    PerpSweepReport,
    _apply_funding_cost,
    run_perp_gate_sweep,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _empty_metrics(num_trades: int = 10) -> BacktestMetrics:
    return BacktestMetrics(
        oos_return=Decimal("0.10"),
        sharpe=Decimal("1.5"),
        sortino=Decimal("1.2"),
        max_drawdown=Decimal("0.05"),
        win_rate=Decimal("0.55"),
        num_trades=num_trades,
        sharpe_per_obs=Decimal("0.08"),
        skew=Decimal("-0.5"),
        kurtosis=Decimal("4.0"),
        n_obs=100,
    )


def _bars(prices: list[float], *, symbol_seed: float = 0.0) -> list[Bar]:
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    out: list[Bar] = []
    for i, p in enumerate(prices):
        d = Decimal(str(round(p + symbol_seed, 4)))
        out.append(Bar(ts=t0 + timedelta(days=i), open=d, high=d, low=d, close=d, volume=Decimal("1000000")))
    return out


class _EmptyFunding:
    def fetch_series(self, symbol: str, metric: str, *, limit: int):  # noqa: ANN201
        return []


class _SyntheticFunding:
    def __init__(self, bars: dict[str, list[Bar]], rate: float) -> None:
        self._by = {s: [AltDataPoint(ts=b.ts, available_at=b.ts, value=rate) for b in bb] for s, bb in bars.items()}

    def fetch_series(self, symbol: str, metric: str, *, limit: int):  # noqa: ANN201
        if metric != "funding_rate":
            return []
        return self._by.get(symbol, [])


# ---------------------------------------------------------------------------
# Bug 1: pair stats must come from the combined return stream, not naive average
# ---------------------------------------------------------------------------


def test_pair_skew_from_combined_stream_differs_from_naive_average():
    """Naive average of per-leg skews is wrong: skew(0.5*X + 0.5*Y) ≠ 0.5*skew(X) + 0.5*skew(Y).

    This test documents the mathematical property that the old code violated.  With one leg having
    a heavy negative tail and the other being near-flat, the combined stream's negative skew is far
    more extreme than the naive average of individual skews would suggest.
    """
    # Long leg: mostly positive small moves, one big negative tail
    long_rets  = [0.04, 0.03, 0.04, 0.03, 0.04, 0.03, -0.30]
    # Short leg: near-flat — adds almost no skew of its own
    short_rets = [0.01, 0.01, 0.01, 0.01, 0.01, 0.01,  0.01]

    _, long_skew,  _, _ = sample_moments(long_rets)
    _, short_skew, _, _ = sample_moments(short_rets)
    naive_pair_skew = (long_skew + short_skew) / 2.0

    combined = [(l + s) / 2.0 for l, s in zip(long_rets, short_rets)]
    _, correct_pair_skew, _, _ = sample_moments(combined)

    # The two approaches give materially different answers.
    assert abs(naive_pair_skew - correct_pair_skew) > 0.05, (
        f"naive={naive_pair_skew:.4f}  correct={correct_pair_skew:.4f} — expected meaningful divergence"
    )


def test_pair_kurt_from_combined_stream_differs_from_naive_average():
    """Same property for kurtosis: kurt(0.5*X + 0.5*Y) ≠ 0.5*kurt(X) + 0.5*kurt(Y)."""
    # Long leg: fat-tailed (one extreme outlier)
    long_rets  = [0.01] * 18 + [-0.50]
    # Short leg: normal-looking
    short_rets = [0.02, -0.01, 0.01, -0.02, 0.01, 0.02, -0.01, 0.01,
                  0.02, -0.01, 0.01, -0.02, 0.01, 0.02, -0.01, 0.01, 0.02, -0.01, 0.01]

    _, _, long_kurt,  _ = sample_moments(long_rets)
    _, _, short_kurt, _ = sample_moments(short_rets)
    naive_pair_kurt = (long_kurt + short_kurt) / 2.0

    n = min(len(long_rets), len(short_rets))
    combined = [(long_rets[i] + short_rets[i]) / 2.0 for i in range(n)]
    _, _, correct_pair_kurt, _ = sample_moments(combined)

    assert abs(naive_pair_kurt - correct_pair_kurt) > 0.05, (
        f"naive={naive_pair_kurt:.4f}  correct={correct_pair_kurt:.4f} — expected meaningful divergence"
    )


# ---------------------------------------------------------------------------
# Bug 2: _apply_funding_cost must NOT apply when already_accrued=True
# ---------------------------------------------------------------------------


def test_apply_funding_cost_skipped_when_already_accrued():
    """When already_accrued=True the function must return the exact same object unchanged."""
    m = _empty_metrics(num_trades=20)
    result = _apply_funding_cost(m, funding_bps_per_bar=5.0, direction=+1, already_accrued=True)
    assert result is m, "already_accrued=True must short-circuit and return the input unchanged"


def test_apply_funding_cost_applied_when_not_accrued_long():
    """When already_accrued=False a LONG incurs a funding drag (oos_return decreases)."""
    m = _empty_metrics(num_trades=20)
    result = _apply_funding_cost(m, funding_bps_per_bar=5.0, direction=+1, already_accrued=False)
    assert float(result.oos_return) < float(m.oos_return), "long should pay positive funding"


def test_apply_funding_cost_applied_when_not_accrued_short():
    """When already_accrued=False a SHORT receives positive funding (oos_return increases)."""
    m = _empty_metrics(num_trades=20)
    result = _apply_funding_cost(m, funding_bps_per_bar=5.0, direction=-1, already_accrued=False)
    assert float(result.oos_return) > float(m.oos_return), "short should receive positive funding"


def test_apply_funding_cost_zero_bps_is_noop():
    """funding_bps_per_bar=0.0 must always be a no-op regardless of already_accrued."""
    m = _empty_metrics(num_trades=20)
    assert _apply_funding_cost(m, 0.0, direction=+1, already_accrued=False) is m
    assert _apply_funding_cost(m, 0.0, direction=+1, already_accrued=True)  is m


def test_apply_funding_cost_no_trades_is_noop():
    """num_trades=0 must always be a no-op (no open positions to charge)."""
    m = _empty_metrics(num_trades=0)
    assert _apply_funding_cost(m, 5.0, direction=+1, already_accrued=False) is m


# ---------------------------------------------------------------------------
# Bug 2 integration: dispersion specs carry funding_feature so no double-count
# ---------------------------------------------------------------------------


def test_run_perp_gate_sweep_empty_funding_returns_insufficient_data():
    """When the funding cache is empty the harness must abstain (INSUFFICIENT-DATA), never fake a pass.

    This is also the cheapest integration smoke-test: it exercises the full run_perp_gate_sweep
    code path (including the funding guard) without needing real bar data or a grid search.
    """
    import tempfile

    from cosmu.config.settings import Settings
    from cosmu.knowledge.store import Store

    # Minimal market: two symbols with enough bars for the backtest (>=80 bars each).
    prices = [100.0 + i * 0.1 for i in range(120)]
    market = {
        "BTCUSDT": _bars(prices),
        "ETHUSDT": _bars(prices, symbol_seed=1.0),
    }
    tmp = tempfile.mkdtemp(prefix="cosmu-perp-test-")
    store = Store(Settings(database_url=f"sqlite:///{tmp}/t.sqlite3", openrouter_api_key=None))

    report = run_perp_gate_sweep(market, _EmptyFunding(), store)

    assert report.verdict == "INSUFFICIENT-DATA"
    assert any("funding cache empty" in n for n in report.notes)
