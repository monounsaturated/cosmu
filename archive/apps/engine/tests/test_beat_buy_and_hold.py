# fix-2 (money-path): a promoted strategy must BEAT buy-and-hold on the validation slice, net of fees. Without it
# a bull-regime long can clear DSR/PBO/holdout/FDR yet underperform BTC and still get funded. The backtest surfaces
# the validation-slice buy-and-hold NET return on BacktestMetrics and the deterministic scorer adds a "buy_and_hold"
# kill-reason (toggleable via GateSettings.require_beat_buy_and_hold).

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from cosmu.config.settings import GateSettings
from cosmu.data.backtest import _buy_and_hold_return, run_strategy_backtest_detailed
from cosmu.data.market import Bar
from cosmu.evolution.loop import fit_params
from cosmu.evolution.seeder import seed_population
from cosmu.master.scorer import BacktestMetrics, score


def _bull_bars(n: int = 200, step: str = "1.01") -> list[Bar]:
    ts = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
    price = Decimal("100")
    bars: list[Bar] = []
    for i in range(n):
        open_ = price
        close = (price * Decimal(step)).quantize(Decimal("0.0001"))
        bars.append(Bar(ts=ts + dt.timedelta(days=i), open=open_, high=close, low=open_, close=close, volume=Decimal("1000000")))
        price = close
    return bars


def _metrics(*, oos: str, bnh: str) -> BacktestMetrics:
    # A minimal metrics row — only oos_return / buy_and_hold_return matter for the buy_and_hold check (the other
    # gates' reasons are irrelevant to the membership assertions below).
    return BacktestMetrics(
        oos_return=Decimal(oos),
        buy_and_hold_return=Decimal(bnh),
        sharpe=Decimal("0"),
        sortino=Decimal("0"),
        max_drawdown=Decimal("0"),
        win_rate=Decimal("0"),
        num_trades=50,
    )


# --- scorer gate -------------------------------------------------------------------------------

def test_underperforming_buy_and_hold_is_killed():
    verdict = score(_metrics(oos="0.10", bnh="0.50"), GateSettings())
    assert "buy_and_hold" in verdict.reasons


def test_equalling_buy_and_hold_is_not_enough():
    # The check is `oos_return <= buy_and_hold_return` — merely matching the benchmark does not earn promotion.
    verdict = score(_metrics(oos="0.20", bnh="0.20"), GateSettings())
    assert "buy_and_hold" in verdict.reasons


def test_beating_buy_and_hold_clears_the_check():
    verdict = score(_metrics(oos="0.60", bnh="0.10"), GateSettings())
    assert "buy_and_hold" not in verdict.reasons


def test_gate_can_be_disabled():
    verdict = score(_metrics(oos="0.10", bnh="0.50"), GateSettings(require_beat_buy_and_hold=False))
    assert "buy_and_hold" not in verdict.reasons


def test_default_zero_benchmark_imposes_no_hurdle_on_positive_return():
    # A directly-constructed metrics (buy_and_hold_return defaults to 0) only trips the gate when oos_return <= 0,
    # so existing positive-return callers that never populate the field are unaffected.
    assert "buy_and_hold" not in score(_metrics(oos="0.01", bnh="0"), GateSettings()).reasons
    assert "buy_and_hold" in score(_metrics(oos="-0.01", bnh="0"), GateSettings()).reasons


# --- backtest surface --------------------------------------------------------------------------

def test_backtest_surfaces_validation_slice_buy_and_hold_net_of_fees():
    bars = _bull_bars()
    split = max(40, int(len(bars) * 0.8))
    fee = Decimal("10")
    expected = float(bars[split - 1].close) / float(bars[0].close) - 1.0 - 2.0 * (float(fee) / 10000.0)
    # the standalone helper and the metrics field agree, and both use the bars[:split] validation window (never holdout)
    assert abs(_buy_and_hold_return({"BTCUSDT": bars}, fee) - expected) < 1e-6
    metrics = run_strategy_backtest_detailed(seed_population()[0], fit_params(seed_population()[0]), {"BTCUSDT": bars}, fee_bps=fee).metrics
    assert abs(float(metrics.buy_and_hold_return) - expected) < 1e-6


def test_empty_market_has_no_buy_and_hold_hurdle():
    assert _buy_and_hold_return({}, Decimal("10")) == 0.0
