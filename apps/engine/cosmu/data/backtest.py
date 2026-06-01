# intent: run an honest deterministic bar backtest for StrategySpec screens; inputs: exchange OHLCV bars, fitted params, venue + capacity costs; outputs: BacktestMetrics; invariants: fills use prior-bar signals, next-bar prices, venue fees, size-aware slippage, regime-tagged trades, and no synthetic return generation.

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from decimal import Decimal

from cosmu.data.market import Bar
from cosmu.master.scorer import BacktestMetrics, probabilistic_sharpe, sample_moments
from cosmu.strategy.spec import Condition, ParamRef, StrategySpec

_REGIMES = ("bull", "bear", "chop")


@dataclass(frozen=True)
class Trade:
    entry: float
    exit: float
    pnl_pct: float
    regime: str = "chop"


@dataclass(frozen=True)
class SymbolRun:
    total_return: float
    sharpe: float
    sortino: float
    max_drawdown: float
    trades: list[Trade]
    bar_returns: list[float]
    fold_returns: list[float]
    regime_pnl: dict[str, float]
    periods_per_year: float


def run_strategy_backtest(
    spec: StrategySpec,
    params: dict[str, float],
    market: dict[str, list[Bar]],
    *,
    fee_bps: Decimal,
    slippage_bps: Decimal = Decimal("5"),
    impact_bps: Decimal = Decimal("50"),
    size_multiplier: float = 1.0,
) -> BacktestMetrics:
    """Backtest a strategy over real bars, reserving the last fifth as holdout.

    `slippage_bps` is the fixed half-spread; `impact_bps` scales market impact with participation
    (order notional / bar quote-volume), so larger size erodes the edge — the capacity dimension.
    `size_multiplier` scales position notional, used to probe capacity decay.
    """

    if not market:
        return _empty_metrics(spec)

    validation_runs: list[SymbolRun] = []
    holdout_runs: list[SymbolRun] = []
    for bars in market.values():
        if len(bars) < 80:
            continue
        split = max(40, int(len(bars) * 0.8))
        validation_runs.append(_run_symbol(spec, params, bars[:split], fee_bps, slippage_bps, impact_bps, size_multiplier))
        holdout_runs.append(
            _run_symbol(spec, params, bars[split - _warmup_bars(spec, params) :], fee_bps, slippage_bps, impact_bps, size_multiplier)
        )

    if not validation_runs:
        return _empty_metrics(spec)

    val = _combine(validation_runs)
    holdout = _combine(holdout_runs) if holdout_runs else _empty_symbol_run()
    trials = max(1, len(spec.param_space))
    pbo = _pbo_proxy(val, trials)
    win_rate = _win_rate(val.trades)
    folds_positive = sum(1 for value in val.fold_returns if value > 0)
    folds_pct = folds_positive / len(val.fold_returns) if val.fold_returns else 0.0

    # Per-observation moments for the Probabilistic / Deflated Sharpe (annualized SR stays for display).
    sr_obs, skew, kurt, n_obs = sample_moments(val.bar_returns)
    h_sr, h_skew, h_kurt, h_n = sample_moments(holdout.bar_returns)
    holdout_dsr = probabilistic_sharpe(h_sr, h_n, h_skew, h_kurt, 0.0) - 0.5  # > 0 ⇔ holdout Sharpe significantly positive

    return BacktestMetrics(
        oos_return=Decimal(str(round(val.total_return, 8))),
        sharpe=Decimal(str(round(val.sharpe, 6))),
        sortino=Decimal(str(round(val.sortino, 6))),
        max_drawdown=Decimal(str(round(val.max_drawdown, 6))),
        win_rate=Decimal(str(round(win_rate, 6))),
        num_trades=len(val.trades),
        sharpe_per_obs=Decimal(str(round(sr_obs, 8))),
        skew=Decimal(str(round(skew, 6))),
        kurtosis=Decimal(str(round(kurt, 6))),
        n_obs=n_obs,
        pbo=pbo,
        trials_counted=trials,
        folds_positive_pct=Decimal(str(round(folds_pct, 6))),
        holdout_deflated_sharpe=Decimal(str(round(holdout_dsr, 6))),
        regime_returns={k: round(v, 8) for k, v in val.regime_pnl.items()},
    )


def _run_symbol(
    spec: StrategySpec,
    params: dict[str, float],
    bars: list[Bar],
    fee_bps: Decimal,
    slippage_bps: Decimal,
    impact_bps: Decimal,
    size_multiplier: float,
) -> SymbolRun:
    closes = [float(bar.close) for bar in bars]
    features = _feature_matrix(spec, params, bars)
    regimes = _regime_labels(closes)
    fee = float(fee_bps) / 10000.0
    base_slip = float(slippage_bps) / 10000.0
    impact = float(impact_bps) / 10000.0
    cash = 100000.0
    position = 0.0
    entry_price = 0.0
    entry_idx = 0
    high_water = cash
    equity_points: list[float] = []
    trades: list[Trade] = []
    stop_pct = max(0.0, float(params[spec.exit.stop_loss.param]))
    take_pct = max(0.0, float(params[spec.exit.take_profit.param]))
    max_hold_bars = max(1, int(spec.horizon.max_hold_days * _bars_per_day(spec.horizon.bar_size)))

    start = max(_warmup_bars(spec, params), 2)
    for idx in range(start, len(bars)):
        bar = bars[idx]
        slip = _slippage(base_slip, impact, _entry_notional(cash, spec, size_multiplier), bar)
        if position > 0:
            stop_price = entry_price * (1 - stop_pct)
            take_price = entry_price * (1 + take_pct)
            exit_price: float | None = None
            if float(bar.low) <= stop_price:
                exit_price = stop_price * (1 - slip)
            elif float(bar.high) >= take_price:
                exit_price = take_price * (1 - slip)
            elif idx - entry_idx >= max_hold_bars or _exit_signal(spec, params, features, idx - 1):
                exit_price = float(bar.open) * (1 - slip)

            if exit_price is not None:
                gross = position * exit_price
                cash += gross * (1 - fee)
                pnl_pct = (exit_price * (1 - fee) - entry_price * (1 + fee)) / entry_price
                trades.append(Trade(entry=entry_price, exit=exit_price, pnl_pct=pnl_pct, regime=regimes[entry_idx]))
                position = 0.0
                entry_price = 0.0

        if position == 0 and _entry_signal(spec, params, features, idx - 1):
            notional = _entry_notional(cash, spec, size_multiplier)
            if notional > 0:
                fill = float(bar.open) * (1 + slip)
                position = (notional * (1 - fee)) / fill
                cash -= notional
                entry_price = fill
                entry_idx = idx

        equity = cash + position * closes[idx]
        high_water = max(high_water, equity)
        equity_points.append(equity)

    if position > 0:
        slip = _slippage(base_slip, impact, position * closes[-1], bars[-1])
        exit_price = closes[-1] * (1 - slip)
        gross = position * exit_price
        cash += gross * (1 - fee)
        pnl_pct = (exit_price * (1 - fee) - entry_price * (1 + fee)) / entry_price
        trades.append(Trade(entry=entry_price, exit=exit_price, pnl_pct=pnl_pct, regime=regimes[entry_idx]))
        equity_points.append(cash)

    periods_per_year = 365.0 * _bars_per_day(spec.horizon.bar_size)
    return _symbol_metrics(equity_points, trades, periods_per_year=periods_per_year)


def _entry_notional(cash: float, spec: StrategySpec, size_multiplier: float) -> float:
    frac = max(0.0, min(float(spec.risk.max_position_pct), 1.0)) * max(0.0, min(float(spec.risk.conviction), 1.0))
    return max(0.0, min(cash, cash * frac * max(0.0, size_multiplier)))


def _slippage(base_slip: float, impact: float, notional: float, bar: Bar) -> float:
    """Half-spread plus square-root market impact on participation = notional / bar quote-volume."""
    quote_volume = float(bar.volume) * float(bar.close)
    if quote_volume <= 0 or notional <= 0:
        return base_slip
    participation = min(1.0, notional / quote_volume)
    return base_slip + impact * math.sqrt(participation)


def _regime_labels(closes: list[float], lookback: int = 30, band: float = 0.05) -> list[str]:
    labels = ["chop"] * len(closes)
    for idx in range(lookback, len(closes)):
        base = closes[idx - lookback]
        ret = (closes[idx] / base - 1.0) if base else 0.0
        labels[idx] = "bull" if ret > band else "bear" if ret < -band else "chop"
    return labels


def _feature_matrix(spec: StrategySpec, params: dict[str, float], bars: list[Bar]) -> dict[str, list[float | None]]:
    wanted = {condition.feature.name for condition in [*spec.entry, *spec.exit.signal_exits]}
    closes = [float(bar.close) for bar in bars]
    highs = [float(bar.high) for bar in bars]
    lows = [float(bar.low) for bar in bars]
    out: dict[str, list[float | None]] = {}
    for name in wanted:
        lookback = _lookback_for(name, spec, params)
        if name == "ret_Nd":
            out[name] = _returns(closes, lookback)
        elif name == "rsi":
            out[name] = _rsi(closes, lookback)
        elif name == "bb_z":
            out[name] = _bb_z(closes, lookback)
        elif name == "vol_realized":
            out[name] = _realized_vol(closes, lookback)
        elif name == "atr":
            out[name] = _atr(highs, lows, closes, lookback)
        elif name == "adx":
            out[name] = _adx(highs, lows, closes, lookback)
        else:
            out[name] = [None] * len(bars)
    return out


def _entry_signal(spec: StrategySpec, params: dict[str, float], features: dict[str, list[float | None]], idx: int) -> bool:
    return all(_condition_true(condition, params, features, idx) for condition in spec.entry)


def _exit_signal(spec: StrategySpec, params: dict[str, float], features: dict[str, list[float | None]], idx: int) -> bool:
    return any(_condition_true(condition, params, features, idx) for condition in spec.exit.signal_exits)


def _condition_true(condition: Condition, params: dict[str, float], features: dict[str, list[float | None]], idx: int) -> bool:
    values = features.get(condition.feature.name, [])
    if idx <= 0 or idx >= len(values):
        return False
    current = values[idx]
    previous = values[idx - 1]
    if current is None:
        return False
    threshold = _param_value(condition.threshold, params)
    if condition.op == "gt":
        return current > threshold
    if condition.op == "gte":
        return current >= threshold
    if condition.op == "lt":
        return current < threshold
    if condition.op == "lte":
        return current <= threshold
    if condition.op == "cross_up":
        return previous is not None and previous <= threshold < current
    if condition.op == "cross_down":
        return previous is not None and previous >= threshold > current
    if condition.op == "between":
        return abs(current) <= abs(threshold)
    return False


def _param_value(ref: ParamRef, params: dict[str, float]) -> float:
    return float(params[ref.param])


def _lookback_for(name: str, spec: StrategySpec, params: dict[str, float]) -> int:
    for condition in [*spec.entry, *spec.exit.signal_exits]:
        if condition.feature.name != name:
            continue
        lookback = condition.feature.lookback
        if isinstance(lookback, ParamRef):
            return max(2, int(round(params[lookback.param])))
        if isinstance(lookback, int):
            return max(2, lookback)
    return 14


def _warmup_bars(spec: StrategySpec, params: dict[str, float]) -> int:
    lookbacks = [_lookback_for(condition.feature.name, spec, params) for condition in [*spec.entry, *spec.exit.signal_exits]]
    return max([20, *lookbacks]) + 2


def _bars_per_day(bar_size: str) -> float:
    return {"1h": 24.0, "4h": 6.0, "1d": 1.0}[bar_size]


def _symbol_metrics(
    equity: list[float],
    trades: list[Trade],
    *,
    periods_per_year: float,
) -> SymbolRun:
    if len(equity) < 2:
        return _empty_symbol_run(trades)
    returns = [(equity[i] / equity[i - 1] - 1.0) if equity[i - 1] else 0.0 for i in range(1, len(equity))]
    total_return = equity[-1] / 100000.0 - 1.0
    high = equity[0]
    max_dd = 0.0
    for value in equity:
        high = max(high, value)
        if high:
            max_dd = max(max_dd, (high - value) / high)
    regime_pnl: dict[str, float] = {}
    for trade in trades:
        regime_pnl[trade.regime] = regime_pnl.get(trade.regime, 0.0) + trade.pnl_pct
    return SymbolRun(
        total_return=total_return,
        sharpe=_sharpe(returns, periods_per_year),
        sortino=_sortino(returns, periods_per_year),
        max_drawdown=max_dd,
        trades=trades,
        bar_returns=returns,
        fold_returns=_fold_returns(equity),
        regime_pnl=regime_pnl,
        periods_per_year=periods_per_year,
    )


def _combine(runs: list[SymbolRun]) -> SymbolRun:
    if not runs:
        return _empty_symbol_run()
    trades = [trade for run in runs for trade in run.trades]
    bar_returns = [ret for run in runs for ret in run.bar_returns]
    fold_returns = [ret for run in runs for ret in run.fold_returns]
    periods_per_year = statistics.fmean(run.periods_per_year for run in runs)
    regime_pnl: dict[str, float] = {}
    for run in runs:
        for regime, value in run.regime_pnl.items():
            regime_pnl[regime] = regime_pnl.get(regime, 0.0) + value
    return SymbolRun(
        total_return=statistics.fmean(run.total_return for run in runs),
        sharpe=_sharpe(bar_returns, periods_per_year),
        sortino=_sortino(bar_returns, periods_per_year),
        max_drawdown=max(run.max_drawdown for run in runs),
        trades=trades,
        bar_returns=bar_returns,
        fold_returns=fold_returns,
        regime_pnl=regime_pnl,
        periods_per_year=periods_per_year,
    )


def _empty_metrics(spec: StrategySpec) -> BacktestMetrics:
    trials = max(1, len(spec.param_space))
    return BacktestMetrics(
        oos_return=Decimal("0"),
        sharpe=Decimal("0"),
        sortino=Decimal("0"),
        max_drawdown=Decimal("1"),
        win_rate=Decimal("0"),
        num_trades=0,
        sharpe_per_obs=Decimal("0"),
        skew=Decimal("0"),
        kurtosis=Decimal("3"),
        n_obs=0,
        pbo=Decimal("0.95"),
        trials_counted=trials,
        folds_positive_pct=Decimal("0"),
        holdout_deflated_sharpe=Decimal("-1"),
        regime_returns={},
    )


def _empty_symbol_run(trades: list[Trade] | None = None) -> SymbolRun:
    return SymbolRun(0.0, 0.0, 0.0, 1.0, trades or [], [], [], {}, 365.0)


def _pbo_proxy(run: SymbolRun, trials: int) -> Decimal:
    if not run.fold_returns:
        return Decimal("0.95")
    losing = sum(1 for value in run.fold_returns if value <= 0) / len(run.fold_returns)
    dispersion = statistics.pstdev(run.fold_returns) if len(run.fold_returns) > 1 else 0.0
    trial_penalty = min(0.35, math.log1p(max(0, trials - 1)) * 0.06)
    value = min(0.95, max(0.02, losing * 0.55 + dispersion * 3.0 + trial_penalty))
    return Decimal(str(round(value, 6)))


def _win_rate(trades: list[Trade]) -> float:
    if not trades:
        return 0.0
    return sum(1 for trade in trades if trade.pnl_pct > 0) / len(trades)


def _sharpe(returns: list[float], periods_per_year: float) -> float:
    if len(returns) < 2:
        return 0.0
    std = statistics.pstdev(returns)
    if std == 0:
        return 0.0
    return statistics.fmean(returns) / std * math.sqrt(periods_per_year)


def _sortino(returns: list[float], periods_per_year: float) -> float:
    if len(returns) < 2:
        return 0.0
    downside = [ret for ret in returns if ret < 0]
    if not downside:
        return _sharpe(returns, periods_per_year)
    dd = statistics.pstdev(downside)
    if dd == 0:
        return 0.0
    return statistics.fmean(returns) / dd * math.sqrt(periods_per_year)


def _fold_returns(equity: list[float], folds: int = 4) -> list[float]:
    if len(equity) < folds * 2:
        return []
    size = len(equity) // folds
    out: list[float] = []
    for idx in range(folds):
        chunk = equity[idx * size : (idx + 1) * size if idx < folds - 1 else len(equity)]
        if len(chunk) > 1 and chunk[0]:
            out.append(chunk[-1] / chunk[0] - 1.0)
    return out


def _returns(values: list[float], lookback: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    for idx in range(lookback, len(values)):
        base = values[idx - lookback]
        out[idx] = values[idx] / base - 1.0 if base else None
    return out


def _realized_vol(values: list[float], lookback: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    rets = _returns(values, 1)
    for idx in range(lookback, len(values)):
        window = [ret for ret in rets[idx - lookback + 1 : idx + 1] if ret is not None]
        out[idx] = statistics.pstdev(window) * math.sqrt(lookback) if len(window) > 1 else None
    return out


def _rsi(values: list[float], lookback: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    for idx in range(lookback, len(values)):
        diffs = [values[j] - values[j - 1] for j in range(idx - lookback + 1, idx + 1)]
        gains = [max(diff, 0.0) for diff in diffs]
        losses = [abs(min(diff, 0.0)) for diff in diffs]
        avg_gain = statistics.fmean(gains)
        avg_loss = statistics.fmean(losses)
        out[idx] = 100.0 if avg_loss == 0 else 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))
    return out


def _bb_z(values: list[float], lookback: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    for idx in range(lookback, len(values)):
        window = values[idx - lookback + 1 : idx + 1]
        mean = statistics.fmean(window)
        std = statistics.pstdev(window)
        out[idx] = (values[idx] - mean) / std if std else 0.0
    return out


def _atr(highs: list[float], lows: list[float], closes: list[float], lookback: int) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    tr: list[float] = [0.0]
    for idx in range(1, len(closes)):
        tr.append(max(highs[idx] - lows[idx], abs(highs[idx] - closes[idx - 1]), abs(lows[idx] - closes[idx - 1])))
    for idx in range(lookback, len(closes)):
        out[idx] = statistics.fmean(tr[idx - lookback + 1 : idx + 1]) / closes[idx]
    return out


def _adx(highs: list[float], lows: list[float], closes: list[float], lookback: int) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    plus_dm = [0.0]
    minus_dm = [0.0]
    tr = [0.0]
    for idx in range(1, len(closes)):
        up = highs[idx] - highs[idx - 1]
        down = lows[idx - 1] - lows[idx]
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
        tr.append(max(highs[idx] - lows[idx], abs(highs[idx] - closes[idx - 1]), abs(lows[idx] - closes[idx - 1])))
    dx: list[float | None] = [None] * len(closes)
    for idx in range(lookback, len(closes)):
        tr_sum = sum(tr[idx - lookback + 1 : idx + 1])
        if tr_sum == 0:
            continue
        plus_di = 100 * sum(plus_dm[idx - lookback + 1 : idx + 1]) / tr_sum
        minus_di = 100 * sum(minus_dm[idx - lookback + 1 : idx + 1]) / tr_sum
        denom = plus_di + minus_di
        dx[idx] = 0.0 if denom == 0 else 100 * abs(plus_di - minus_di) / denom
    for idx in range(lookback * 2, len(closes)):
        window = [value for value in dx[idx - lookback + 1 : idx + 1] if value is not None]
        out[idx] = statistics.fmean(window) if window else None
    return out
