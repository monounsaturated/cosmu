# intent: run an honest deterministic bar backtest for StrategySpec screens; inputs: exchange OHLCV bars, fitted params, venue + capacity costs; outputs: BacktestMetrics; invariants: fills use prior-bar signals, next-bar prices, venue fees, size-aware slippage, regime-tagged trades, and no synthetic return generation.

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Type-only: the runtime import is deferred inside `_build_meta_gate` to break the cosmu.ml ↔ backtest cycle
    # (see the note on the deferred import below). MetaGate is used in the return annotation of _build_meta_gate.
    from cosmu.ml.metalabel import MetaGate

from cosmu.data.altdata import AltDataPoint
from cosmu.data.market import Bar
from cosmu.master.scorer import BacktestMetrics, probabilistic_sharpe, sample_moments
from cosmu.master.sizing import compute_target_vol
from cosmu.strategy.spec import Condition, FeatureRef, MetaLabel, ParamRef, StrategySpec

# cosmu.ml.metalabel (MetaGate / MetaEvent / triple_barrier_outcome) is imported LAZILY inside `_build_meta_gate`:
# cosmu.ml.__init__ eagerly pulls cosmu.ml.regime, which imports `_regime_labels` from THIS module, so a top-level
# import would be circular. By gate-build time `backtest` is fully initialized, so the deferred import is safe.

_REGIMES = ("bull", "bear", "chop")

# THE single cost model both simulators share: research/gate.py::_simulate imports these constants + the
# `_slippage` participation curve below, so the single-signal Gate and the StrategySpec backtest charge the
# IDENTICAL slippage + market impact on every fill — they cannot disagree on net-of-fee profit. The fixed
# half-spread is the floor; impact scales with participation (order notional / bar quote-volume) so larger
# size erodes the edge (the capacity dimension). Named (DEFAULT_*) so the writers that PERSIST a backtest's
# cost assumptions (lab/finder._backtest_row) record the EXACT values charged — never a re-typed literal that
# could silently drift. These are the run_strategy_backtest defaults.
DEFAULT_SLIPPAGE_BPS = Decimal("5")
DEFAULT_IMPACT_BPS = Decimal("50")


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
    # PER-SYMBOL validation breakdown {symbol: {"return","sharpe","max_drawdown","trades"}} — the SAME strategy's
    # individual result on EACH symbol it was tested on, BEFORE the cross-sectional pool. The keystone for "which
    # symbols does this edge actually hold on?": out-of-asset generalization, deploy-where-confirmed (vs the
    # arbitrary round-robin), and the frontend per-symbol display. Additive + default-empty (existing callers,
    # incl. the two empty-result paths below, are untouched).
    per_symbol: dict[str, dict[str, float]] = field(default_factory=dict)
    # T1 SIZING: median EWMA realized vol (bar-frequency) of the underlying price returns over the validation
    # window, pooled across all symbols. Frozen at funding → tracks.target_vol. None when the series is too
    # short (< 21 bars after warmup). The paper/live executor uses this to scale position size dynamically;
    # NULL in the DB → T0 static sizing (max_position_pct × conviction).
    target_vol: float | None = None

    @property
    def min_symbol_trades(self) -> int:
        counts = list(self.symbol_trades.values())
        return min(counts) if counts else 0

    @property
    def symbols_tested(self) -> list[str]:
        """Every symbol the strategy was evaluated on (the breadth of this backtest)."""
        return list(self.per_symbol)

    @property
    def positive_symbols(self) -> list[str]:
        """Symbols whose INDIVIDUAL validation return was positive — where the edge actually held. The set a
        'deploy-where-confirmed' router should prefer over an arbitrary round-robin pick."""
        return [s for s, m in self.per_symbol.items() if m.get("return", 0.0) > 0.0]


def run_strategy_backtest(
    spec: StrategySpec,
    params: dict[str, float],
    market: dict[str, list[Bar]],
    *,
    fee_bps: Decimal,
    fee_schedule: dict[str, Decimal] | None = None,
    slippage_bps: Decimal = DEFAULT_SLIPPAGE_BPS,
    impact_bps: Decimal = DEFAULT_IMPACT_BPS,
    size_multiplier: float = 1.0,
    alt_by_symbol: dict[str, dict[str, dict[str, float]]] | None = None,
    size_series: dict[str, float] | None = None,
    include_holdout: bool = True,
) -> BacktestMetrics:
    """Backtest a strategy over real bars, reserving the last fifth as a PURGED + EMBARGOED holdout. Thin
    wrapper over `run_strategy_backtest_detailed` for callers that only need the scoreable metrics."""
    return run_strategy_backtest_detailed(
        spec,
        params,
        market,
        fee_bps=fee_bps,
        fee_schedule=fee_schedule,
        slippage_bps=slippage_bps,
        impact_bps=impact_bps,
        size_multiplier=size_multiplier,
        alt_by_symbol=alt_by_symbol,
        size_series=size_series,
        include_holdout=include_holdout,
    ).metrics


def run_strategy_backtest_detailed(
    spec: StrategySpec,
    params: dict[str, float],
    market: dict[str, list[Bar]],
    *,
    fee_bps: Decimal,
    fee_schedule: dict[str, Decimal] | None = None,
    slippage_bps: Decimal = DEFAULT_SLIPPAGE_BPS,
    impact_bps: Decimal = DEFAULT_IMPACT_BPS,
    size_multiplier: float = 1.0,
    alt_by_symbol: dict[str, dict[str, dict[str, float]]] | None = None,
    size_series: dict[str, float] | None = None,
    include_holdout: bool = True,
) -> BacktestResult:
    """Backtest a strategy over real bars, reserving the last fifth as a PURGED + EMBARGOED holdout.

    `include_holdout=False` SKIPS the holdout simulation entirely — holdout metrics read the same no-evidence
    sentinel an empty holdout stream produces (holdout_deflated_sharpe = PSR(∅) − 0.5 = −0.5). The
    grid-screening lane uses it so non-champion variants never touch the exam — the holdout is a CONFIRMATION
    set for the one selected champion (evaluated once, via the HoldoutLedger), never a selection filter a
    256-variant grid gets to retry against.

    `slippage_bps` is the fixed half-spread; `impact_bps` scales market impact with participation
    (order notional / bar quote-volume), so larger size erodes the edge — the capacity dimension.
    `size_multiplier` scales position notional, used to probe capacity decay.
    `alt_by_symbol` maps symbol → feature → {bar.ts.isoformat(): value}: the point-in-time alt-data join
    (funding_rate, etc.) so leading-signal strategies are actually evaluable, not just price/TA ones. The
    values are keyed by bar timestamp, so the validation/holdout slice carries the right value automatically.
    None → price/TA only (alt features read None), i.e. exactly the prior behaviour.

    `size_series` is an OPTIONAL per-bar, market-wide position-size multiplier keyed by bar.ts.isoformat()
    (same shape/PIT semantics as the alt-data join — it travels with the bar through the validation/holdout
    slice and never leaks the future). It lets a slow market-wide regime TILT exposure WITHOUT adding or
    removing any trade (the entry/exit logic is untouched; only the entry notional is scaled). None → the
    per-run scalar `size_multiplier` is used on every bar, so every existing spec is byte-identical.

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
    per_symbol: dict[str, dict[str, float]] = {}
    val_price_returns: list[float] = []  # T1: pooled price returns from ALL validation windows
    for symbol, bars in market.items():
        if len(bars) < 80:
            continue
        # Per-venue fee: cross-asset backtests supply a fee_schedule (symbol → bps) so equity symbols are
        # charged IBKR's 0.5 bps and crypto symbols Binance's 10 bps — never a single blended rate.
        sym_fee = fee_schedule.get(symbol, fee_bps) if fee_schedule else fee_bps
        alt = (alt_by_symbol or {}).get(symbol)
        val_bars, holdout_bars = _purged_embargoed_split(spec, params, bars)
        # T1: collect price returns PIT to the validation window (NOT holdout — the gate never touches holdout).
        val_price_returns.extend(
            float(val_bars[i].close) / float(val_bars[i - 1].close) - 1.0
            for i in range(1, len(val_bars))
            if float(val_bars[i - 1].close) > 0
        )
        v_run = _run_symbol(spec, params, val_bars, sym_fee, slippage_bps, impact_bps, size_multiplier, alt, size_series)
        validation_runs.append(v_run)
        symbol_trades[symbol] = len(v_run.trades)
        # the SAME strategy's standalone validation result on THIS symbol (pre-pool) — un-collapses the metric.
        per_symbol[symbol] = {
            "return": round(v_run.total_return, 8),
            "sharpe": round(v_run.sharpe, 6),
            "max_drawdown": round(v_run.max_drawdown, 6),
            "trades": float(len(v_run.trades)),
        }
        if holdout_bars and include_holdout:
            holdout_runs.append(_run_symbol(spec, params, holdout_bars, sym_fee, slippage_bps, impact_bps, size_multiplier, alt, size_series))

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
    # KNOWN LIMITATION (cross-asset pools): _avg_cross_correlation aligns return streams POSITIONALLY (by index,
    # tail-trimmed), which is only valid when every symbol shares a calendar. A pooled equity (≈252 td/yr) +
    # crypto/HL-perp (365 td/yr) spec mixes calendars, so a positionally-aligned correlation is meaningless and
    # tends to read ≈0 → UNDER-deflates n_obs_eff → an optimistic (too-lenient) DSR for that spec. This is latent:
    # the current finder only authors single-asset-class specs (the seed is crypto-only), so no live gate decision
    # is affected today. The fix (carry per-bar timestamps out of _run_symbol and inner-join streams on common
    # dates before Pearson) lands WITH the deferred cross-asset/ML phase, where it can be tested against real
    # mixed-calendar specs. Tracked in the cross-asset stats follow-up. Same caveat applies to the 365-day
    # annualization in _symbol_metrics (equity daily bars should annualize at ≈252).
    rho_sym = _avg_cross_correlation([r.bar_returns for r in validation_runs])
    n_obs_eff = _effective_obs(n_obs, len(validation_runs), rho_sym)
    h_sr, h_skew, h_kurt, h_n = sample_moments(holdout.bar_returns)
    holdout_dsr = probabilistic_sharpe(h_sr, h_n, h_skew, h_kurt, 0.0) - 0.5  # > 0 ⇔ holdout Sharpe significantly positive

    # Validation-slice buy-and-hold benchmark: what just HOLDING the same basket over bars[:split] returns, net of
    # the round-trip fee. Computed on the SAME validation window as `val.total_return` (never the holdout, which
    # the gate keeps untouched) so the promotion gate's "beat buy-and-hold" check compares like with like.
    buy_and_hold = _buy_and_hold_return(market, fee_bps, fee_schedule)

    metrics = BacktestMetrics(
        oos_return=Decimal(str(round(val.total_return, 8))),
        buy_and_hold_return=Decimal(str(round(buy_and_hold, 8))),
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
        per_symbol=per_symbol,
        target_vol=compute_target_vol(val_price_returns),
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


def _buy_and_hold_return(
    market: dict[str, list[Bar]], fee_bps: Decimal, fee_schedule: dict[str, Decimal] | None = None
) -> float:
    """Net-of-fee buy-and-hold return over the VALIDATION slice (bars[:split], the same window the strategy is
    scored on — never the holdout). For each symbol with enough bars, buy at the slice's first close and sell at
    its last, charged one round-trip fee, then average across the basket. Mirrors research/gate.py's `_buy_and_hold`
    but uses the single venue fee passed to the backtest. Empty market / no usable symbol → 0.0 (no benchmark to
    beat). The split matches `_purged_embargoed_split`, so the benchmark window equals the strategy's exactly."""
    rets: list[float] = []
    for symbol, bars in market.items():
        if len(bars) < 80:
            continue
        sym_fee = float(fee_schedule.get(symbol, fee_bps)) / 10000.0 if fee_schedule else float(fee_bps) / 10000.0
        split = max(40, int(len(bars) * 0.8))
        window = bars[:split]
        first, last = float(window[0].close), float(window[-1].close)
        if first:
            rets.append(last / first - 1.0 - 2.0 * sym_fee)  # entry + exit fee = one round trip
    return statistics.fmean(rets) if rets else 0.0


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
    size_series: dict[str, float] | None = None,
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

    def _size_at(idx_now: int) -> float:
        """Per-bar position-size multiplier. `size_series` (when supplied) is a point-in-time market-wide tilt
        keyed by bar.ts.isoformat() — the SAME shape as an alt-data join, so it travels with the bar through the
        validation/holdout slice unchanged and never leaks the future. A bar with no series entry falls back to
        the per-run scalar `size_multiplier`, so a None series is byte-identical to the prior scalar behaviour."""
        if size_series is None:
            return size_multiplier
        return size_series.get(bars[idx_now].ts.isoformat(), size_multiplier)

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
    # Triple-barrier meta-label gate. None (no meta_label) => meta_gate is None and every line below collapses to
    # the prior primary-book behaviour (take=True, multiplier=1.0), so a spot/long spec is byte-identical.
    meta = getattr(spec, "meta_label", None)
    meta_refs = _meta_feature_refs(spec)
    meta_gate = _build_meta_gate(
        meta, meta_refs, spec, params, features, setup_ok, highs, lows, closes,
        d=d, start=start, stop_pct=stop_pct, take_pct=take_pct, max_hold_bars=max_hold_bars,
        roundtrip_cost=2.0 * fee + 2.0 * base_slip,
    )
    meta_threshold = max(0.0, min(1.0, float(params[meta.prob_threshold.param]))) if meta is not None else 0.0
    meta_proportional = bool(meta is not None and meta.sizing == "proportional")
    for idx in range(start, len(bars)):
        bar = bars[idx]
        slip = _slippage(base_slip, impact, _entry_notional(cash, spec, _size_at(idx)), bar)
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
            # Secondary meta-label gate: SIZE/SKIP only (direction is untouched). meta_gate is None for the
            # primary book, so take stays True and the multiplier stays 1.0 — the notional is unchanged.
            take, meta_mult = True, 1.0
            if meta_gate is not None:
                take, meta_mult = meta_gate.decide(
                    idx, _meta_featvec(meta_refs, features, idx - 1), meta_threshold, meta_proportional
                )
            notional = _entry_notional(cash, spec, _size_at(idx)) * meta_mult if take else 0.0
            if take and notional > 0:
                # Entry crosses the spread the adverse way: long buys up (1+slip), short sells down (1-slip).
                fill = float(bar.open) * (1 + d * slip)
                if d == 1:
                    # Long (the EXACT original): the entry fee comes out of the bought qty —
                    # qty = notional*(1-fee)/fill — and the full notional leaves cash.
                    position = (notional * (1 - fee)) / fill
                    cash -= notional
                else:
                    # Short: we SELL `notional` worth — the liability is the FULL qty and the entry fee
                    # comes out of the sale proceeds. The previous `d`-mirrored form (qty*(1-fee), full
                    # proceeds) shrank the liability instead of the proceeds, booking the entry fee as a
                    # GAIN — every short equity curve was near fee-free while pnl_pct charged fees, so
                    # curve-derived gate metrics (return/Sharpe/DSR/folds) were gross-of-fee for shorts.
                    position = notional / fill
                    cash += notional * (1 - fee)
                entry_qty = position
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

    # NOTE: 365-day annualization is exact for 24/7 crypto/HL perps. Equity daily bars trade ≈252 days/yr, so a
    # pooled cross-asset spec slightly OVER-annualizes the equity leg's Sharpe (~1.2×). Latent — no mixed-calendar
    # spec exists yet (see the cross-asset stats limitation note at the n_obs_eff site); made asset-class-aware
    # with the deferred cross-asset phase.
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
    alt = alt or {}
    # Prefer the per-bar SUMMED carry series (every settlement in the bar interval — correct total regardless of
    # how the bar size relates to the per-symbol settlement interval; built by the alt-join via
    # `sum_funding_per_bar`). Fall back to the feature's level series for callers that build `alt` by hand
    # (sign-only fixtures with one value per bar — accrued once per bar, the prior behaviour).
    series = alt.get(FUNDING_ACCRUAL_KEY)
    if series is None:
        series = alt.get(name, {})
    return [series.get(bar.ts.isoformat()) for bar in bars]


def _meta_feature_refs(spec: StrategySpec) -> list[FeatureRef]:
    """The secondary meta-label model's feature refs (empty when the spec has no meta_label)."""
    meta = getattr(spec, "meta_label", None)
    return list(meta.features) if meta is not None else []


def _meta_featvec(
    refs: list[FeatureRef], features: dict[str, list[float | None]], idx: int
) -> list[float] | None:
    """The secondary model's point-in-time feature vector at bar `idx`, in the meta_label feature order. Returns
    None if ANY feature is unavailable at that bar (the gate then stays out of the way — it cannot honestly score
    a partial row, and a None never silently becomes a 0)."""
    vec: list[float] = []
    for ref in refs:
        series = features.get(ref.name, [])
        if idx < 0 or idx >= len(series):
            return None
        value = series[idx]
        if value is None:
            return None
        vec.append(float(value))
    return vec


def _build_meta_gate(
    meta: MetaLabel | None,
    meta_refs: list[FeatureRef],
    spec: StrategySpec,
    params: dict[str, float],
    features: dict[str, list[float | None]],
    setup_ok: list[bool],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    *,
    d: int,
    start: int,
    stop_pct: float,
    take_pct: float,
    max_hold_bars: int,
    roundtrip_cost: float,
) -> MetaGate | None:
    """Pre-scan this symbol's primary-signal events and label each by its triple-barrier outcome, returning the
    MetaGate the entry loop consults. None when the spec has no meta_label (no gate at all).

    Events are collected on EVERY bar the primary signal fires (independent of position) so the secondary model
    learns the signal's true hit-rate, not just the subset that happened to be flat. The event's feature row is
    read at the signal bar (j-1) — the SAME point the live decision reads — and a bar whose row is incomplete is
    skipped (it cannot be labeled honestly). The barrier is the spec's own stop/take/time, so the meta-label
    measures exactly the trade the primary book would have taken."""
    if meta is None:
        return None
    from cosmu.ml.metalabel import MetaEvent, MetaGate, triple_barrier_outcome

    events: list[MetaEvent] = []
    for j in range(start, len(closes)):
        if not (setup_ok[j - 1] and _entry_signal(spec, params, features, j - 1)):
            continue
        featvec = _meta_featvec(meta_refs, features, j - 1)
        if featvec is None:
            continue
        label, resolve_idx = triple_barrier_outcome(
            j, highs, lows, closes,
            stop_pct=stop_pct, take_pct=take_pct, max_hold_bars=max_hold_bars, d=d, roundtrip_cost=roundtrip_cost,
        )
        events.append(MetaEvent(signal_idx=j, resolve_idx=resolve_idx, features=featvec, label=label))
    return MetaGate(events=events)


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
    # size_fraction(spec) is the SHARED fraction — identical to what paper_step/live deploy (audit #7 parity).
    # size_multiplier is a backtest-only capacity/meta tilt (1.0 in the production gate path).
    from cosmu.master.sizing import size_fraction
    return max(0.0, min(cash, cash * size_fraction(spec) * max(0.0, size_multiplier)))


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


# Reserved alt-dict key carrying the per-bar SUMMED funding cash-flow series (every settlement in the bar's
# interval), kept SEPARATE from the funding feature's level series so a funding-as-CONDITION read (e.g.
# "funding_rate < ceiling") still sees the point-in-time LEVEL while the carry leg accrues the correct TOTAL.
# Dunder so it can never collide with a registry feature name (feature_names()/the route guard never see it).
FUNDING_ACCRUAL_KEY = "__funding_accrual__"


def sum_funding_per_bar(points: list[AltDataPoint], bars: list[Bar]) -> dict[str, float]:
    """Funding-ONLY point-in-time join for CARRY ACCRUAL: SUM every funding settlement whose timestamp falls in
    a bar's interval, so the carry accrued over a hold equals the actual sum of settlements — regardless of how
    the bar size relates to the per-symbol settlement interval (8h on Binance/OKX, 1h on Kraken Futures, …). The
    interval is READ FROM THE DATA (we sum whatever real settlements land in the bar), never hardcoded to a
    "3/day" assumption.

    This is the funding-correct counterpart to `align_asof`. align_asof carries the LAST value forward — right
    for a level/condition read, but for a CASH FLOW it is 2–8x off: on a sub-interval grid (e.g. 1h bars, 8h
    funding) it carries ONE 8h print across every bar and accrues it on each (over-count); on a super-interval
    grid (e.g. 1d bars, 8h funding) it collapses the day's three 8h prints to the last one (under-count). Summing
    per bar accrues each settlement exactly once, on the bar whose interval (prev_bar.ts, bar.ts] contains it.

    The first bar opens one cadence earlier (bars[1].ts - bars[0].ts) so a settlement landing on it is captured
    without dumping deep prior history into bar 0. available_at == ts for funding (the exchange publishes the
    realized rate at the settlement instant), so a settlement in (·, bar.ts] is known by that bar's close — no
    look-ahead. Keyed by bar.ts.isoformat() so the summed value travels with the bar through any later slice.
    Bars with no settlement get no entry (the funding series reads None → accrues nothing — honest, never 0-fab)."""
    if not points or not bars:
        return {}
    bars_sorted = sorted(bars, key=lambda b: b.ts)
    pts = sorted(points, key=lambda p: p.ts)
    cadence = (bars_sorted[1].ts - bars_sorted[0].ts) if len(bars_sorted) >= 2 else timedelta(0)
    out: dict[str, float] = {}
    j, n = 0, len(pts)
    lo = bars_sorted[0].ts - cadence  # bar 0's lower bound (one cadence back), so pre-window funding is dropped
    for bar in bars_sorted:
        total = 0.0
        hit = False
        while j < n and pts[j].ts <= bar.ts:
            if pts[j].ts > lo:  # inside (lo, bar.ts]; the guard only ever excludes deep pre-history at bar 0
                total += float(pts[j].value)
                hit = True
            j += 1
        if hit:
            out[bar.ts.isoformat()] = total
        lo = bar.ts
    return out


# TA features computed directly, per-symbol, from the bar series in `_feature_matrix` below.
_BAR_TA_FEATURES = frozenset({"ret_Nd", "rsi", "bb_z", "vol_realized", "atr", "adx", "bb_width", "range_position"})

# COHORT-COMPUTED features: real, point-in-time features that are NOT ingested into the alt store and NOT
# bar-TA either — they are COMPUTED by a research cohort and handed to the backtest via the caller's `alt`
# dict (read through `_feature_matrix`'s else-branch), never store-joined. The cross-sectional momentum rank
# (research.carry_ablation._xsec_rank_alt, derived from the whole universe's bars), the normalized LunarCrush
# derivations (research.social_norm.derive_social_alt), and the social-authority signals
# (mind.authority.AuthorityProvider). They belong with the computed features (not the store-joined universe),
# so the registry↔route guard recognises them as "computed, not dead", and `alt_feature_universe` correctly
# excludes them from the store alt-join it attempts (there is no store data to fetch — only the cohort computes
# them). If one of these is later persisted to the store, move it to `_STORE_PROVIDER_OF` instead.
_COHORT_COMPUTED_FEATURES = frozenset({
    "xsec_momentum_rank",
    "social_volume_accel", "social_attention_z", "social_excess_attention_z", "galaxy_score_z", "btc_social_accel",
    "authority_weighted_claim_signal", "author_authority",
})

# Public union (the single source of truth): every feature the backtest does NOT alt-join from the store
# because it is COMPUTED (bar-TA above, or cohort-computed) and supplied directly. The evolution loop derives
# the leading-signal / store-joined universe as `feature_registry.feature_names() - PRICE_FEATURES`, so the two
# stay in lockstep with no duplicated key list. (Name kept for back-compat with importers, incl. the
# registry↔route guard test; it now means "computed / not-store-joined", a superset of the bar-TA features.)
PRICE_FEATURES = _BAR_TA_FEATURES | _COHORT_COMPUTED_FEATURES


def _feature_matrix(
    spec: StrategySpec,
    params: dict[str, float],
    bars: list[Bar],
    alt: dict[str, dict[str, float]] | None = None,
) -> dict[str, list[float | None]]:
    # Compute/join every feature the entry, signal-exits AND the secondary meta-label model read. The meta
    # features (e.g. funding_rate, rsi, vol) must be materialized too so the gate can score on them point-in-time.
    wanted = {condition.feature.name for condition in [*spec.entry, *spec.exit.signal_exits]}
    wanted |= {ref.name for ref in _meta_feature_refs(spec)}
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
        elif name == "bb_width":
            out[name] = _bb_width(closes, lookback)
        elif name == "vol_realized":
            out[name] = _realized_vol(closes, lookback)
        elif name == "atr":
            out[name] = _atr(highs, lows, closes, lookback)
        elif name == "adx":
            out[name] = _adx(highs, lows, closes, lookback)
        elif name == "range_position":
            out[name] = _range_position(highs, lows, closes, lookback)
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
    # Entry/exit condition refs first, then the secondary meta-label refs, so a meta feature carries its OWN
    # fitted lookback (a meta-only feature like rsi/vol resolves its window, not the bare 14 default).
    refs = [condition.feature for condition in [*spec.entry, *spec.exit.signal_exits]] + _meta_feature_refs(spec)
    for ref in refs:
        if ref.name != name:
            continue
        lookback = ref.lookback
        if isinstance(lookback, ParamRef):
            return max(2, int(round(params[lookback.param])))
        if isinstance(lookback, int):
            return max(2, lookback)
    return 14


def _warmup_bars(spec: StrategySpec, params: dict[str, float]) -> int:
    feature_refs = [condition.feature for condition in [*spec.entry, *spec.exit.signal_exits]] + _meta_feature_refs(spec)
    lookbacks = [_lookback_for(ref.name, spec, params) for ref in feature_refs]
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
    """Wilder's RSI: seed the average gain/loss with the mean of the first `lookback` deltas, then smooth each
    with a 1/lookback running average (the SMMA/RMA recursion that ta.rsi and every charting package use). The
    prior flat window mean over-reacted at the extremes and matched no imported signal (Pine, TradingView)."""
    out: list[float | None] = [None] * len(values)
    if len(values) <= lookback:
        return out
    gains = [max(values[i] - values[i - 1], 0.0) for i in range(1, len(values))]
    losses = [max(values[i - 1] - values[i], 0.0) for i in range(1, len(values))]
    avg_gain = statistics.fmean(gains[:lookback])
    avg_loss = statistics.fmean(losses[:lookback])
    out[lookback] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    for idx in range(lookback + 1, len(values)):
        avg_gain = (avg_gain * (lookback - 1) + gains[idx - 1]) / lookback
        avg_loss = (avg_loss * (lookback - 1) + losses[idx - 1]) / lookback
        out[idx] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return out


def _bb_z(values: list[float], lookback: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    for idx in range(lookback, len(values)):
        window = values[idx - lookback + 1 : idx + 1]
        mean = statistics.fmean(window)
        std = statistics.pstdev(window)
        out[idx] = (values[idx] - mean) / std if std else 0.0
    return out


def _bb_width(values: list[float], lookback: int) -> list[float | None]:
    """Bollinger Bandwidth: the ±2σ band width normalized by the basis — (upper - lower) / mid = 4·σ / mean
    (the textbook ta.bbw / TradingView Bollinger Bandwidth). LOW = a compressed, coiled range (the squeeze a
    reversion edge wants); a rising value = the range expanding into a trend. Dimensionless, so it compares
    across assets and time. Same rolling window as `_bb_z`; None until `lookback` bars exist, 0.0 on a flat
    basis (no width)."""
    out: list[float | None] = [None] * len(values)
    for idx in range(lookback, len(values)):
        window = values[idx - lookback + 1 : idx + 1]
        mean = statistics.fmean(window)
        std = statistics.pstdev(window)
        out[idx] = (4.0 * std / mean) if mean else 0.0
    return out


def _range_position(highs: list[float], lows: list[float], closes: list[float], lookback: int) -> list[float | None]:
    """Donchian / stochastic channel position: (close − rolling_low) / (rolling_high − rolling_low) over the
    trailing `lookback` bars, bounded in [0, 1]. 0 = sitting on the FLOOR of the recent range (the grid-bot's
    accumulation zone — buy the dip toward the low), 1 = at the CEILING (fade the bounce). Distinct from `_bb_z`,
    which is mean-relative and σ-normalized: this is EXTREME-relative and bounded, the literal 'where in the
    range is price' read, so its thresholds are interpretable deciles of the channel. Uses intrabar high/low
    (same as `_atr`/`_adx`). None until `lookback` bars exist; 0.5 on a flat channel (zero width)."""
    out: list[float | None] = [None] * len(closes)
    for idx in range(lookback, len(closes)):
        window_high = max(highs[idx - lookback + 1 : idx + 1])
        window_low = min(lows[idx - lookback + 1 : idx + 1])
        width = window_high - window_low
        out[idx] = (closes[idx] - window_low) / width if width else 0.5
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
    """Wilder's ADX: +DM/-DM/TR are smoothed with a 1/lookback running average, the directional indices build
    DX, and ADX is the running average of DX (the textbook / ta.adx construction). The prior flat rolling-sum
    ran hot in trends and matched no standard ADX, so imported trend filters mis-fired on it."""
    n = len(closes)
    out: list[float | None] = [None] * n
    if n <= lookback * 2:
        return out
    plus_dm = [0.0] * n
    minus_dm = [0.0] * n
    tr = [0.0] * n
    for idx in range(1, n):
        up = highs[idx] - highs[idx - 1]
        down = lows[idx - 1] - lows[idx]
        plus_dm[idx] = up if up > down and up > 0 else 0.0
        minus_dm[idx] = down if down > up and down > 0 else 0.0
        tr[idx] = max(
            highs[idx] - lows[idx], abs(highs[idx] - closes[idx - 1]), abs(lows[idx] - closes[idx - 1])
        )
    # Wilder-smoothed running sums seeded on the first `lookback` bars (indices 1..lookback), then RMA-updated.
    atr = sum(tr[1 : lookback + 1])
    sum_plus = sum(plus_dm[1 : lookback + 1])
    sum_minus = sum(minus_dm[1 : lookback + 1])
    dx: list[float | None] = [None] * n
    for idx in range(lookback, n):
        if idx > lookback:
            atr = atr - atr / lookback + tr[idx]
            sum_plus = sum_plus - sum_plus / lookback + plus_dm[idx]
            sum_minus = sum_minus - sum_minus / lookback + minus_dm[idx]
        if atr <= 0:
            continue
        plus_di = 100.0 * sum_plus / atr
        minus_di = 100.0 * sum_minus / atr
        denom = plus_di + minus_di
        dx[idx] = 0.0 if denom == 0 else 100.0 * abs(plus_di - minus_di) / denom
    # ADX seeds on the mean of the first `lookback` DX values, then smooths with the same 1/lookback RMA.
    seed = [dx[i] for i in range(lookback, lookback * 2) if dx[i] is not None]
    if not seed:
        return out
    adx = statistics.fmean(seed)
    out[lookback * 2 - 1] = adx
    for idx in range(lookback * 2, n):
        value = dx[idx]
        if value is None:
            out[idx] = adx
            continue
        adx = (adx * (lookback - 1) + value) / lookback
        out[idx] = adx
    return out
