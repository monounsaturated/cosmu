# intent: run an honest deterministic bar backtest for StrategySpec screens; inputs: exchange OHLCV bars, fitted params, venue + capacity costs; outputs: BacktestMetrics; invariants: fills use prior-bar signals, next-bar prices, venue fees, size-aware slippage, regime-tagged trades, and no synthetic return generation.

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from decimal import Decimal

from cosmu.data.altdata import AltDataPoint
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


@dataclass(frozen=True)
class BacktestResult:
    """The full backtest output. `metrics` is the scoreable summary (as before); the extra fields expose what
    a multiple-testing cohort needs WITHOUT widening BacktestMetrics: the validation per-bar return stream (for
    real CSCV-PBO + cross-variant correlation clustering), the holdout stream, and the PER-SYMBOL validation
    trade counts (so a finder can require evidence on EACH symbol, not ~6 trades pooled across 5 correlated
    ones)."""

    metrics: BacktestMetrics
    val_returns: list[float]
    holdout_returns: list[float]
    symbol_trades: dict[str, int]

    @property
    def min_symbol_trades(self) -> int:
        counts = list(self.symbol_trades.values())
        return min(counts) if counts else 0


def run_strategy_backtest(
    spec: StrategySpec,
    params: dict[str, float],
    market: dict[str, list[Bar]],
    *,
    fee_bps: Decimal,
    slippage_bps: Decimal = Decimal("5"),
    impact_bps: Decimal = Decimal("50"),
    size_multiplier: float = 1.0,
    alt_by_symbol: dict[str, dict[str, dict[str, float]]] | None = None,
) -> BacktestMetrics:
    """Backtest a strategy over real bars, reserving the last fifth as a PURGED + EMBARGOED holdout. Thin
    wrapper over `run_strategy_backtest_detailed` for callers that only need the scoreable metrics."""
    return run_strategy_backtest_detailed(
        spec,
        params,
        market,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        impact_bps=impact_bps,
        size_multiplier=size_multiplier,
        alt_by_symbol=alt_by_symbol,
    ).metrics


def run_strategy_backtest_detailed(
    spec: StrategySpec,
    params: dict[str, float],
    market: dict[str, list[Bar]],
    *,
    fee_bps: Decimal,
    slippage_bps: Decimal = Decimal("5"),
    impact_bps: Decimal = Decimal("50"),
    size_multiplier: float = 1.0,
    alt_by_symbol: dict[str, dict[str, dict[str, float]]] | None = None,
) -> BacktestResult:
    """Backtest a strategy over real bars, reserving the last fifth as a PURGED + EMBARGOED holdout.

    `slippage_bps` is the fixed half-spread; `impact_bps` scales market impact with participation
    (order notional / bar quote-volume), so larger size erodes the edge — the capacity dimension.
    `size_multiplier` scales position notional, used to probe capacity decay.
    `alt_by_symbol` maps symbol → feature → {bar.ts.isoformat(): value}: the point-in-time alt-data join
    (funding_rate, etc.) so leading-signal strategies are actually evaluable, not just price/TA ones. The
    values are keyed by bar timestamp, so the validation/holdout slice carries the right value automatically.
    None → price/TA only (alt features read None), i.e. exactly the prior behaviour.

    Holdout integrity: the holdout is the bars AT/AFTER `split`; its indicator warm-up is drawn from its OWN
    leading band (>= split), never from the training window. The previous `bars[split - warmup:]` slice fed
    `warmup` TRAINING bars into the holdout — a look-ahead/contamination leak. The leading warm-up band is now
    an EMBARGO traded by neither side, so no position straddles the train/holdout boundary.
    """

    if not market:
        return BacktestResult(_empty_metrics(spec), [], [], {})

    validation_runs: list[SymbolRun] = []
    holdout_runs: list[SymbolRun] = []
    symbol_trades: dict[str, int] = {}
    for symbol, bars in market.items():
        if len(bars) < 80:
            continue
        alt = (alt_by_symbol or {}).get(symbol)
        val_bars, holdout_bars = _purged_embargoed_split(spec, params, bars)
        v_run = _run_symbol(spec, params, val_bars, fee_bps, slippage_bps, impact_bps, size_multiplier, alt)
        validation_runs.append(v_run)
        symbol_trades[symbol] = len(v_run.trades)
        if holdout_bars:
            holdout_runs.append(_run_symbol(spec, params, holdout_bars, fee_bps, slippage_bps, impact_bps, size_multiplier, alt))

    if not validation_runs:
        return BacktestResult(_empty_metrics(spec), [], [], {})

    val = _combine(validation_runs)
    holdout = _combine(holdout_runs) if holdout_runs else _empty_symbol_run()
    trials = max(1, len(spec.param_space))
    pbo = _pbo_proxy(val, trials)
    win_rate = _win_rate(val.trades)
    profit_factor = _profit_factor(val.trades)
    folds_positive = sum(1 for value in val.fold_returns if value > 0)
    folds_pct = folds_positive / len(val.fold_returns) if val.fold_returns else 0.0

    # Per-observation moments for the Probabilistic / Deflated Sharpe (annualized SR stays for display).
    sr_obs, skew, kurt, n_obs = sample_moments(val.bar_returns)
    # Concatenating correlated symbols pools their bars into one long series — but 5 correlated crypto symbols
    # are NOT 5x the INDEPENDENT observations. Deflate the PSR/DSR sample size by the cross-symbol correlation
    # so significance can't be manufactured by adding more of the same beta.
    rho_sym = _avg_cross_correlation([r.bar_returns for r in validation_runs])
    n_obs_eff = _effective_obs(n_obs, len(validation_runs), rho_sym)
    h_sr, h_skew, h_kurt, h_n = sample_moments(holdout.bar_returns)
    holdout_dsr = probabilistic_sharpe(h_sr, h_n, h_skew, h_kurt, 0.0) - 0.5  # > 0 ⇔ holdout Sharpe significantly positive

    metrics = BacktestMetrics(
        oos_return=Decimal(str(round(val.total_return, 8))),
        sharpe=Decimal(str(round(val.sharpe, 6))),
        sortino=Decimal(str(round(val.sortino, 6))),
        max_drawdown=Decimal(str(round(val.max_drawdown, 6))),
        win_rate=Decimal(str(round(win_rate, 6))),
        num_trades=len(val.trades),
        sharpe_per_obs=Decimal(str(round(sr_obs, 8))),
        skew=Decimal(str(round(skew, 6))),
        kurtosis=Decimal(str(round(kurt, 6))),
        n_obs=n_obs_eff,
        pbo=pbo,
        trials_counted=trials,
        folds_positive_pct=Decimal(str(round(folds_pct, 6))),
        holdout_deflated_sharpe=Decimal(str(round(holdout_dsr, 6))),
        regime_returns={k: round(v, 8) for k, v in val.regime_pnl.items()},
        profit_factor=Decimal(str(round(profit_factor, 6))),
    )
    return BacktestResult(
        metrics=metrics,
        val_returns=list(val.bar_returns),
        holdout_returns=list(holdout.bar_returns),
        symbol_trades=symbol_trades,
    )


def _purged_embargoed_split(
    spec: StrategySpec, params: dict[str, float], bars: list[Bar]
) -> tuple[list[Bar], list[Bar]]:
    """Split bars into (validation, holdout) with a PURGE + EMBARGO between them.

    Validation = bars[:split] (the first ~80%, unchanged). Holdout = bars[split:] — the holdout's own leading
    `warmup` band seeds its indicators, so warm-up never reaches into the training window (the old
    `bars[split - warmup:]` leaked train bars forward). That leading band is also the EMBARGO: it is traded by
    NEITHER validation (force-closed by `split`) nor holdout (which only opens after its warm-up), so no
    position straddles the boundary and the holdout's first trade is >= `warmup` bars past the last training
    bar. Returns an empty holdout when there aren't enough post-split bars to trade after the embargo."""
    split = max(40, int(len(bars) * 0.8))
    warmup = _warmup_bars(spec, params)
    holdout_bars = bars[split:]
    # Need at least the warm-up band plus a couple of tradeable bars for a usable, non-degenerate holdout.
    if len(holdout_bars) < warmup + 2:
        return bars[:split], []
    return bars[:split], holdout_bars


def _pearson(a: list[float], b: list[float]) -> float | None:
    n = min(len(a), len(b))
    if n < 2:
        return None
    aa, bb = a[-n:], b[-n:]
    ma, mb = statistics.fmean(aa), statistics.fmean(bb)
    va = sum((x - ma) ** 2 for x in aa)
    vb = sum((y - mb) ** 2 for y in bb)
    if va <= 0 or vb <= 0:
        return None
    cov = sum((aa[k] - ma) * (bb[k] - mb) for k in range(n))
    return cov / math.sqrt(va * vb)


def _avg_cross_correlation(series: list[list[float]]) -> float:
    """Average pairwise Pearson correlation across symbol return streams (aligned on their common tail). 0 when
    fewer than two usable streams. The diversification haircut on the pooled observation count uses this."""
    usable = [s for s in series if len(s) >= 2]
    if len(usable) < 2:
        return 0.0
    corrs: list[float] = []
    for i in range(len(usable)):
        for j in range(i + 1, len(usable)):
            c = _pearson(usable[i], usable[j])
            if c is not None:
                corrs.append(c)
    return statistics.fmean(corrs) if corrs else 0.0


def _effective_obs(n_obs: int, n_symbols: int, rho_sym: float) -> int:
    """Deflate a pooled observation count for cross-symbol correlation: n_eff = n_obs / (1 + (S-1)*rho_sym).
    One symbol (or non-positive correlation) → unchanged, so single-asset backtests are byte-identical."""
    if n_symbols <= 1 or rho_sym <= 0.0 or n_obs <= 2:
        return n_obs
    rho = min(1.0, rho_sym)
    return max(2, int(round(n_obs / (1.0 + (n_symbols - 1) * rho))))


def _run_symbol(
    spec: StrategySpec,
    params: dict[str, float],
    bars: list[Bar],
    fee_bps: Decimal,
    slippage_bps: Decimal,
    impact_bps: Decimal,
    size_multiplier: float,
    alt: dict[str, dict[str, float]] | None = None,
) -> SymbolRun:
    # direction: +1 long (the spot/upside-only default), -1 short (perp/short leg). 0 is reserved (no per-bar
    # direction signal yet) and is treated as long so existing condition-only specs are unchanged. `d` is the
    # signed multiplier used to mirror every long inequality into its short counterpart.
    d = -1 if getattr(spec, "direction", 1) == -1 else 1
    closes = [float(bar.close) for bar in bars]
    highs = [float(bar.high) for bar in bars]
    lows = [float(bar.low) for bar in bars]
    features = _feature_matrix(spec, params, bars, alt)
    # Point-in-time funding-rate series (perp carry), looked up per bar. None => spot, no funding leg.
    funding = _funding_series(spec, bars, alt)
    regimes = _regime_labels(closes)
    fee = float(fee_bps) / 10000.0
    base_slip = float(slippage_bps) / 10000.0
    impact = float(impact_bps) / 10000.0
    cash = 100000.0
    position = 0.0          # current (possibly partially-exited) base-currency position (always >= 0; `d` is the side)
    entry_qty = 0.0         # the qty originally opened (for sizing partial legs)
    entry_price = 0.0
    entry_idx = 0
    stop_price = 0.0        # the live stop level (moves to break-even / trails for the runner)
    tp1_filled = False
    legs_filled: set[int] = set()
    extreme_since_entry = 0.0  # highest high (long) / lowest low (short) since entry, for the runner trail
    funding_accrued = 0.0      # cumulative funding cash flow on the open leg (long pays +rate, short receives)
    high_water = cash
    equity_points: list[float] = []
    trades: list[Trade] = []
    stop_pct = max(0.0, float(params[spec.exit.stop_loss.param]))
    take_pct = max(0.0, float(params[spec.exit.take_profit.param]))
    max_hold_bars = max(1, int(spec.horizon.max_hold_days * _bars_per_day(spec.horizon.bar_size)))
    legs = _resolved_tp_legs(spec, params)          # [] when no multi_tp plan
    plan = spec.exit.plan
    runner_trail = (
        max(0.0, float(params[plan.runner_trail.param])) if plan and plan.runner_trail is not None else None
    )
    break_even = bool(plan and plan.break_even_after_tp1)
    # Precompute the entry-setup gates (MA filter / ORB breakout / FVG retest). These remain long/upside-only;
    # a short spec without setups is unaffected (the gate is all-True when no setup is present).
    setup_ok = _setup_entry_gate(spec, params, highs, lows, closes)

    def _book(exit_qty: float, exit_px: float, idx_now: int) -> None:
        nonlocal cash, position
        # `cash` settles the exit leg: a long SELLS (cash += proceeds net of fee); a short BUYS BACK
        # (cash -= cost gross of fee). The `d` sign and the (1 - d*fee) factor make this reduce to the EXACT
        # original spot expression `cash += exit_qty*exit_px*(1-fee)` when d == +1. pnl_pct mirrors it: a long
        # profits as exit rises, a short as exit falls; entry/exit fees apply symmetrically either way.
        cash += d * exit_qty * exit_px * (1 - d * fee)
        pnl_pct = d * (exit_px * (1 - d * fee) - entry_price * (1 + d * fee)) / entry_price
        trades.append(Trade(entry=entry_price, exit=exit_px, pnl_pct=pnl_pct, regime=regimes[entry_idx]))
        position -= exit_qty

    def _accrue_funding(idx_now: int) -> None:
        """Accrue one bar of funding as cash P&L on the open leg. A LONG perp pays funding when the rate is
        positive (cost), a SHORT receives it (income) — so the cash flow is `-d * rate * notional`. Spot
        (funding series None) accrues nothing, so the spot equity curve is byte-identical to before."""
        nonlocal cash, funding_accrued
        if funding is None or position <= 0:
            return
        rate = funding[idx_now]
        if rate is None:
            return
        flow = -d * float(rate) * position * closes[idx_now]
        cash += flow
        funding_accrued += flow

    start = max(_warmup_bars(spec, params), 2)
    for idx in range(start, len(bars)):
        bar = bars[idx]
        slip = _slippage(base_slip, impact, _entry_notional(cash, spec, size_multiplier), bar)
        if position > 0:
            _accrue_funding(idx)
            # Side-aware adverse/favourable extremes: a long's worst case is the bar low and best the high;
            # for a short they swap. `extreme_since_entry` tracks the favourable extreme for the runner trail.
            adverse = float(bar.low) if d == 1 else float(bar.high)
            favourable = float(bar.high) if d == 1 else float(bar.low)
            extreme_since_entry = (
                max(extreme_since_entry, favourable) if d == 1 else min(extreme_since_entry, favourable)
            )
            if runner_trail is not None and tp1_filled:
                # Trail the stop behind the favourable extreme: below it for a long, above it for a short.
                trail = extreme_since_entry * (1 - d * runner_trail)
                stop_price = max(stop_price, trail) if d == 1 else min(stop_price, trail)
            # 1) stop / runner-trail first (worst-case priority): long stops when low <= stop; short when high >= stop.
            stop_hit = adverse <= stop_price if d == 1 else adverse >= stop_price
            if stop_hit and position > 0:
                _book(position, stop_price * (1 - d * slip), idx)
            # 2) partial take-profit legs (multi_tp) in ascending profit-distance order
            if position > 0 and legs:
                for li, (at, size_pct) in enumerate(legs):
                    if li in legs_filled:
                        continue
                    leg_price = entry_price * (1 + d * at)
                    leg_hit = favourable >= leg_price if d == 1 else favourable <= leg_price
                    if leg_hit:
                        leg_qty = min(position, entry_qty * size_pct)
                        if leg_qty > 0:
                            _book(leg_qty, leg_price * (1 - d * slip), idx)
                            legs_filled.add(li)
                            if not tp1_filled:
                                tp1_filled = True
                                if break_even:
                                    # Risk-free runner: stop to entry (tightest in the favourable direction).
                                    stop_price = max(stop_price, entry_price) if d == 1 else min(stop_price, entry_price)
            # 3) single take-profit (only when there is no multi_tp plan)
            tp_price = entry_price * (1 + d * take_pct)
            tp_hit = favourable >= tp_price if d == 1 else favourable <= tp_price
            if position > 0 and not legs and tp_hit:
                _book(position, tp_price * (1 - d * slip), idx)
            # 4) time-stop / signal exit closes whatever remains
            if position > 0 and (idx - entry_idx >= max_hold_bars or _exit_signal(spec, params, features, idx - 1)):
                _book(position, float(bar.open) * (1 - d * slip), idx)
            if position <= 1e-12:
                position = 0.0
                entry_price = 0.0
                funding_accrued = 0.0

        if position == 0 and setup_ok[idx - 1] and _entry_signal(spec, params, features, idx - 1):
            notional = _entry_notional(cash, spec, size_multiplier)
            if notional > 0:
                # Entry crosses the spread the adverse way: long buys up (1+slip), short sells down (1-slip).
                fill = float(bar.open) * (1 + d * slip)
                # Open the leg. For a long this is the EXACT original: qty = notional*(1-fee)/fill and
                # cash -= notional. For a short, `d` flips it: we sell `notional` worth, taking in proceeds.
                position = (notional * (1 - fee)) / fill
                entry_qty = position
                cash -= d * notional
                entry_price = fill
                entry_idx = idx
                # Stop sits the adverse side of entry: below for a long, above for a short.
                stop_price = entry_price * (1 - d * stop_pct)
                tp1_filled = False
                legs_filled = set()
                extreme_since_entry = float(bar.high) if d == 1 else float(bar.low)
                funding_accrued = 0.0

        # Mark-to-market. For a long this is the EXACT original `cash + position*close`. For a short, cash
        # already holds the sale proceeds (+notional) so the open leg is marked as a liability `-position*close`.
        equity = cash + d * position * closes[idx]
        high_water = max(high_water, equity)
        equity_points.append(equity)

    if position > 0:
        slip = _slippage(base_slip, impact, position * closes[-1], bars[-1])
        _book(position, closes[-1] * (1 - d * slip), len(bars) - 1)
        position = 0.0
        equity_points.append(cash)

    periods_per_year = 365.0 * _bars_per_day(spec.horizon.bar_size)
    return _symbol_metrics(equity_points, trades, periods_per_year=periods_per_year)


def _funding_series(
    spec: StrategySpec, bars: list[Bar], alt: dict[str, dict[str, float]] | None
) -> list[float | None] | None:
    """The per-bar point-in-time funding rate (perp carry), aligned to `bars`. Returns None when the spec has
    no `funding_feature` (spot — no funding leg, the prior behaviour). Reads the same PIT alt-data join keyed
    by bar timestamp as every other alt feature, so the funding value travels with the bar through any slice
    and never leaks the future. A bar with no available funding point reads None (accrues nothing)."""
    name = getattr(spec, "funding_feature", None)
    if not name:
        return None
    series = (alt or {}).get(name, {})
    return [series.get(bar.ts.isoformat()) for bar in bars]


def _resolved_tp_legs(spec: StrategySpec, params: dict[str, float]) -> list[tuple[float, float]]:
    """Resolve the multi_tp legs to concrete (take-distance, size-fraction) pairs from fitted params, sorted by
    take distance ascending so partials fill in order. Returns [] when no multi_tp plan is set (single-TP path)."""
    plan = spec.exit.plan
    if plan is None or not plan.multi_tp:
        return []
    legs: list[tuple[float, float]] = []
    for leg in plan.multi_tp:
        at = max(0.0, float(params[leg.at.param]))
        size = max(0.0, min(1.0, float(params[leg.size_pct.param])))
        legs.append((at, size))
    return sorted(legs, key=lambda pair: pair[0])


def _setup_entry_gate(
    spec: StrategySpec, params: dict[str, float], highs: list[float], lows: list[float], closes: list[float]
) -> list[bool]:
    """Per-bar boolean: is the entry SETUP satisfied at this bar? Composes the optional long/upside-only setups
    (MA-trend filter AND ORB breakout AND FVG retest) — all that are present must hold. No setup => always True,
    so plain condition-only strategies are unchanged. Point-in-time: each index reads only bars up to it."""
    n = len(closes)
    gate = [True] * n
    setup = spec.setup
    if setup is None:
        return gate
    if setup.ma_trend_filter is not None:
        lb = max(2, int(round(params[setup.ma_trend_filter.ma_lookback.param])))
        ma = _sma(closes, lb)
        gate = [gate[i] and ma[i] is not None and closes[i] > ma[i] for i in range(n)]
    if setup.orb is not None:
        rng = max(2, int(round(params[setup.orb.range_bars.param])))
        buf = max(0.0, float(params[setup.orb.buffer.param]))
        rng_high = _rolling_high(highs, rng)
        gate = [gate[i] and rng_high[i] is not None and closes[i] > rng_high[i] * (1 + buf) for i in range(n)]
    if setup.fvg is not None:
        gap_min = max(0.0, float(params[setup.fvg.gap_min.param]))
        max_retests = max(1, int(round(params[setup.fvg.max_retests.param])))
        gate = [gate[i] and v for i, v in enumerate(_fvg_retest_signal(highs, lows, closes, gap_min, max_retests))]
    return gate


def _sma(values: list[float], lookback: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    for idx in range(lookback - 1, len(values)):
        out[idx] = statistics.fmean(values[idx - lookback + 1 : idx + 1])
    return out


def _rolling_high(highs: list[float], lookback: int) -> list[float | None]:
    """Rolling opening-range high over the PRIOR `lookback` bars (excludes the current bar — no look-ahead)."""
    out: list[float | None] = [None] * len(highs)
    for idx in range(lookback, len(highs)):
        out[idx] = max(highs[idx - lookback : idx])
    return out


def _fvg_retest_signal(
    highs: list[float], lows: list[float], closes: list[float], gap_min: float, max_retests: int
) -> list[bool]:
    """Upside fair-value-gap retest signal. A bullish FVG forms at bar i when highs[i-2] < lows[i] (a 3-bar
    imbalance) and the gap fraction (lows[i]-highs[i-2])/highs[i-2] >= gap_min. Once formed, the signal fires
    on each later bar whose low dips back INTO the gap [highs[i-2], lows[i]] (a retest), up to `max_retests`
    times. Long/upside-only. Point-in-time: a gap is only active for bars after it formed."""
    n = len(closes)
    out = [False] * n
    # active gaps: [gap_lo, gap_hi, retests_used]. A gap is retired once it is fully used OR price has dropped
    # below it (the gap filled / invalidated) — bounding the live set keeps this linear, not quadratic.
    gaps: list[list[float]] = []
    for i in range(n):
        if i >= 2:
            gap_lo, gap_hi = highs[i - 2], lows[i]
            if gap_hi > gap_lo and (gap_hi - gap_lo) / gap_lo >= gap_min:
                gaps.append([gap_lo, gap_hi, 0.0])
        still_active: list[list[float]] = []
        for g in gaps:
            gap_lo, gap_hi, used = g
            if used < max_retests and lows[i] <= gap_hi and closes[i] >= gap_lo:
                out[i] = True
                g[2] = used + 1
                used += 1
            if used < max_retests and closes[i] >= gap_lo:  # retire used-up or filled-below gaps
                still_active.append(g)
        gaps = still_active
    return out


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


def align_asof(points: list[AltDataPoint], bars: list[Bar]) -> dict[str, float]:
    """Point-in-time join of an alt-data series onto a bar series. Each bar gets the LATEST alt value whose
    `available_at` is <= that bar's timestamp — i.e. what we would actually have known at the bar. A point
    published after the bar is NEVER used (no look-ahead). Keyed by bar.ts.isoformat() so the value travels
    with the bar through any later slice (validation / holdout). Bars before the first available point get no
    entry (the feature reads None there, exactly as if the data did not exist yet)."""
    if not points or not bars:
        return {}
    pts = sorted(points, key=lambda p: p.available_at)
    out: dict[str, float] = {}
    i = 0
    current: float | None = None
    for bar in sorted(bars, key=lambda b: b.ts):
        while i < len(pts) and pts[i].available_at <= bar.ts:
            current = pts[i].value
            i += 1
        if current is not None:
            out[bar.ts.isoformat()] = current
    return out


# Features computed directly from the bar series; everything else is alt-data joined point-in-time.
# Public (the single source of truth): the evolution loop derives the leading-signal / alt-data universe
# it must join as `feature_registry.feature_names() - PRICE_FEATURES`, so the two stay in lockstep with no
# duplicated key list. Anything NOT in here is read from the point-in-time alt join (None when absent).
PRICE_FEATURES = frozenset({"ret_Nd", "rsi", "bb_z", "vol_realized", "atr", "adx"})


def _feature_matrix(
    spec: StrategySpec,
    params: dict[str, float],
    bars: list[Bar],
    alt: dict[str, dict[str, float]] | None = None,
) -> dict[str, list[float | None]]:
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
            # Alt-data feature (funding_rate, etc.): read the point-in-time series joined by the caller,
            # looked up per bar timestamp. Absent series → None (the condition then can't fire — honest).
            series = (alt or {}).get(name, {})
            out[name] = [series.get(bar.ts.isoformat()) for bar in bars]
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
    setup = spec.setup
    if setup is not None:
        if setup.ma_trend_filter is not None:
            lookbacks.append(int(round(params.get(setup.ma_trend_filter.ma_lookback.param, 20))))
        if setup.orb is not None:
            lookbacks.append(int(round(params.get(setup.orb.range_bars.param, 20))))
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
        profit_factor=Decimal("0"),
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


def _profit_factor(trades: list[Trade]) -> float:
    """Gross wins / gross losses across trade net-of-fee returns. A DISPLAYED secondary metric only — never
    a ranking input. No trades => 0; only-winners (no losses) => a capped sentinel so it stays finite."""
    gross_win = sum(trade.pnl_pct for trade in trades if trade.pnl_pct > 0)
    gross_loss = -sum(trade.pnl_pct for trade in trades if trade.pnl_pct < 0)
    if gross_loss <= 0:
        return min(gross_win / 1e-9, 1000.0) if gross_win > 0 else 0.0
    return gross_win / gross_loss


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


def _fold_returns(equity: list[float], folds: int = 4, embargo: int = 1) -> list[float]:
    """Per-fold OOS returns over a PURGED + EMBARGOED walk-forward partition of the equity curve: it is cut into
    `folds` contiguous blocks and the leading `embargo` points of each block are dropped, so a position open
    across a fold boundary cannot leak its outcome into the adjacent fold."""
    if len(equity) < folds * (embargo + 2):
        return []
    size = len(equity) // folds
    out: list[float] = []
    for idx in range(folds):
        start = idx * size + embargo
        end = (idx + 1) * size if idx < folds - 1 else len(equity)
        chunk = equity[start:end]
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
