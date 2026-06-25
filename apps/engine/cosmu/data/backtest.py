# intent: run an honest deterministic bar backtest for StrategySpec screens; inputs: exchange OHLCV bars, fitted params, venue + capacity costs; outputs: BacktestMetrics; invariants: fills use prior-bar signals, next-bar prices, venue fees, size-aware slippage, regime-tagged trades, and no synthetic return generation.

from __future__ import annotations

import logging
import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

_log = logging.getLogger("cosmu.data.backtest")

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
    # ISO bar timestamps PARALLEL to bar_returns (bar_ts[i] labels bar_returns[i]). Carried so the pooled
    # cross-symbol correlation can inner-join streams on common DATES instead of aligning by position — the
    # only honest alignment once a spec mixes calendars (equity ≈252 sessions/yr vs crypto/HL 365, 24/7).
    bar_ts: list[str]
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
    # PER-SYMBOL validation RUNS — the full SymbolRun per symbol (its OWN bar_returns + fold_returns + trades +
    # moments), the streams the BRUT per-combo gate scores ON: each cell's own DSR from its bar_returns AND its own
    # PBO from its fold_returns, never the cross-symbol pool (val.bar_returns/fold_returns). Additive + default-empty
    # (existing callers + the empty-result paths untouched). The scalar `per_symbol` above stays for display; this
    # carries what's needed to judge a triplet on its OWN data. NEVER re-pool by reusing val.* per cell.
    per_symbol_runs: dict[str, SymbolRun] = field(default_factory=dict)
    # PER-SYMBOL HOLDOUT RUNS — each cell's OWN untouched holdout SymbolRun (empty when include_holdout=False, the
    # screen path). metrics_for_run takes the cell's holdout_run so the brut per-combo gate confirms a champion on
    # ITS OWN holdout, never the pooled basket holdout. Additive + default-empty.
    per_symbol_holdout_runs: dict[str, SymbolRun] = field(default_factory=dict)
    # PER-SYMBOL BUY-AND-HOLD — each cell's OWN net-of-fee buy-and-hold over its validation window, so the brut
    # gate's beat-buy-and-hold check compares a cell against ITS OWN benchmark (not the pooled basket average).
    per_symbol_buy_and_hold: dict[str, float] = field(default_factory=dict)

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
    depth_schedule: dict[str, tuple[Decimal, Decimal]] | None = None,
    size_multiplier: float = 1.0,
    alt_by_symbol: dict[str, dict[str, dict[str, float]]] | None = None,
    size_series: dict[str, float] | None = None,
    include_holdout: bool = True,
    asset_class_by_symbol: dict[str, str] | None = None,
    vol_target_sizing: bool = True,
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
        depth_schedule=depth_schedule,
        size_multiplier=size_multiplier,
        alt_by_symbol=alt_by_symbol,
        size_series=size_series,
        include_holdout=include_holdout,
        asset_class_by_symbol=asset_class_by_symbol,
        vol_target_sizing=vol_target_sizing,
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
    depth_schedule: dict[str, tuple[Decimal, Decimal]] | None = None,
    size_multiplier: float = 1.0,
    alt_by_symbol: dict[str, dict[str, dict[str, float]]] | None = None,
    size_series: dict[str, float] | None = None,
    include_holdout: bool = True,
    asset_class_by_symbol: dict[str, str] | None = None,
    vol_target_sizing: bool = True,
) -> BacktestResult:
    """Backtest a strategy over real bars, reserving the last fifth as a PURGED + EMBARGOED holdout.

    `vol_target_sizing` (default True) sizes each symbol's equity curve with the SAME T1 vol-target envelope the
    paper/live executor runs (master/sizing.size_fraction), so the brut per-combo gate scores the physics the
    track will actually trade instead of a static T0 fraction (backtest≠live realism fix). It is strictly
    PER-COMBO: each symbol is sized on ITS OWN validation-window vol anchor (compute_target_vol on that symbol's
    own price returns) — NO sibling/pooled vol enters any one cell's curve. Set False to score the legacy
    static-fraction physics (used for the before/after pass-rate comparison, and for any track that trades T0).

    `include_holdout=False` SKIPS the holdout simulation entirely — holdout metrics read the same no-evidence
    sentinel an empty holdout stream produces (holdout_deflated_sharpe = PSR(∅) − 0.5 = −0.5). The
    grid-screening lane uses it so non-champion variants never touch the exam — the holdout is a CONFIRMATION
    set for the one selected champion (evaluated once, via the HoldoutLedger), never a selection filter a
    256-variant grid gets to retry against.

    `slippage_bps` is the fixed half-spread; `impact_bps` scales market impact with participation
    (order notional / bar quote-volume), so larger size erodes the edge — the capacity dimension.
    `depth_schedule` maps symbol -> (slippage_bps, impact_bps): the per-venue MARKET DEPTH, a mirror of
    `fee_schedule` so a cross-asset backtest charges each leg the depth of the venue it would ACTUALLY trade on
    (equity at IBKR's 2/25, HL perps at 6/60) instead of the spec's primary-venue depth applied uniformly. A
    symbol absent from the map (or `depth_schedule=None`) falls back to the scalar `slippage_bps`/`impact_bps`,
    so the crypto-only path is byte-identical.
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

    `asset_class_by_symbol` maps symbol → asset class ("crypto" | "equity" | "fx" | "prediction"). It drives the
    per-symbol annualization calendar (equity/fx ≈252 sessions/yr, crypto/HL-perp/prediction 365, 24/7) so a
    pooled cross-asset spec annualizes each leg on its OWN calendar instead of over-stating the equity leg's
    Sharpe ≈√(365/252) ≈ 1.2×. None (or a symbol absent from the map) → the 365-session crypto default, so every
    single-asset-class crypto backtest is byte-identical.

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
    per_symbol_runs: dict[str, SymbolRun] = {}  # the full per-symbol run streams (for the brut per-combo gate)
    per_symbol_holdout_runs: dict[str, SymbolRun] = {}  # each cell's own holdout run (brut champion confirmation)
    per_symbol_buy_and_hold: dict[str, float] = {}      # each cell's own B&H benchmark (brut beat-B&H check)
    val_price_returns: list[float] = []  # T1: pooled price returns from ALL validation windows
    for symbol, bars in market.items():
        if len(bars) < 80:
            continue
        # Per-venue fee: cross-asset backtests supply a fee_schedule (symbol → bps) so equity symbols are
        # charged IBKR's 0.5 bps and crypto symbols Binance's 10 bps — never a single blended rate.
        sym_fee = fee_schedule.get(symbol, fee_bps) if fee_schedule else fee_bps
        # Per-venue MARKET DEPTH (the slippage/impact half of trading cost): the same cross-asset backtest
        # supplies a depth_schedule (symbol → (slippage_bps, impact_bps)) so an equity leg pays IBKR's 2/25 and
        # an HL leg 6/60 — not the spec's primary-venue depth applied uniformly. A symbol absent from the map
        # (or no map at all) falls back to the scalar slippage_bps/impact_bps, so crypto-only is byte-identical.
        sym_slip, sym_impact = (
            depth_schedule.get(symbol, (slippage_bps, impact_bps)) if depth_schedule else (slippage_bps, impact_bps)
        )
        alt = (alt_by_symbol or {}).get(symbol)
        # Annualize THIS symbol on its OWN calendar: equity/fx ≈252 sessions/yr, crypto/HL/prediction 365.
        # Default (no map / unknown class) is the 365-session crypto base, so single-asset crypto is unchanged.
        ppy = _periods_per_year(spec.horizon.bar_size, (asset_class_by_symbol or {}).get(symbol))
        val_bars, holdout_bars = _purged_embargoed_split(spec, params, bars)
        # T1: collect price returns PIT to the validation window (NOT holdout — the gate never touches holdout).
        sym_val_returns = [
            float(val_bars[i].close) / float(val_bars[i - 1].close) - 1.0
            for i in range(1, len(val_bars))
            if float(val_bars[i - 1].close) > 0
        ]
        val_price_returns.extend(sym_val_returns)
        # PER-COMBO T1 anchor: THIS symbol's own vol fingerprint, from ITS OWN validation window only — never a
        # pooled/sibling value. None disables T1 for this symbol (too few bars) → it sizes T0, as before. With
        # vol_target_sizing off, sym_tv stays None and every cell's curve is the legacy static-fraction physics.
        sym_tv = compute_target_vol(sym_val_returns) if vol_target_sizing else None
        v_run = _run_symbol(spec, params, val_bars, sym_fee, sym_slip, sym_impact, size_multiplier, alt, size_series, periods_per_year=ppy, target_vol=sym_tv)
        validation_runs.append(v_run)
        symbol_trades[symbol] = len(v_run.trades)
        # the SAME strategy's standalone validation result on THIS symbol (pre-pool) — un-collapses the metric.
        per_symbol[symbol] = {
            "return": round(v_run.total_return, 8),
            "sharpe": round(v_run.sharpe, 6),
            "max_drawdown": round(v_run.max_drawdown, 6),
            "trades": float(len(v_run.trades)),
        }
        per_symbol_runs[symbol] = v_run  # keep the full stream (bar_returns + fold_returns) for the brut gate
        # Each cell's OWN net-of-fee buy-and-hold over ITS validation slice (same window as v_run) — the brut gate
        # beats THIS symbol's benchmark, not the pooled basket average. Uses the cell's own per-venue fee.
        per_symbol_buy_and_hold[symbol] = _symbol_buy_and_hold(val_bars, sym_fee)
        if holdout_bars and include_holdout:
            # The holdout's T1 anchor is the SAME validation-window vol (frozen at funding, never re-fit on the
            # exam) — mirroring the live track, whose target_vol is fixed from validation and never recomputed.
            h_run = _run_symbol(spec, params, holdout_bars, sym_fee, sym_slip, sym_impact, size_multiplier, alt, size_series, periods_per_year=ppy, target_vol=sym_tv)
            holdout_runs.append(h_run)
            per_symbol_holdout_runs[symbol] = h_run  # this cell's OWN holdout (brut champion confirmation)

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
    # so significance can't be manufactured by adding more of the same beta. The correlation is measured by
    # inner-joining each symbol pair on their COMMON bar timestamps (NOT by index) so a pooled mixed-calendar
    # spec — equity (≈252 sessions/yr) + crypto/HL-perp (365, 24/7) — is haircut on the dates the legs actually
    # share, instead of a positional alignment that reads a spurious ≈0 and UNDER-deflates n_obs_eff into a
    # too-lenient DSR. Single-calendar crypto cohorts join on identical timestamps, so they are unchanged.
    rho_sym = _avg_cross_correlation(
        [r.bar_returns for r in validation_runs], [r.bar_ts for r in validation_runs]
    )
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
        per_symbol_runs=per_symbol_runs,
        per_symbol_holdout_runs=per_symbol_holdout_runs,
        per_symbol_buy_and_hold=per_symbol_buy_and_hold,
        target_vol=compute_target_vol(val_price_returns),
    )


def metrics_for_run(
    run: SymbolRun,
    *,
    trials: int,
    buy_and_hold: float,
    holdout_run: SymbolRun | None = None,
) -> BacktestMetrics:
    """Build a BacktestMetrics for ONE combo (algorithm × asset × venue) from its OWN validation run — the BRUT
    per-combo gate input. Identical formulas to the pooled path (sample_moments / _pbo_proxy / probabilistic_sharpe
    / win_rate / profit_factor), but on a SINGLE symbol's streams: no cross-symbol pool, and n_obs is this combo's
    OWN observation count (no cross-symbol effective-obs haircut — that haircut only exists to discount pooling
    correlated symbols, which the brut model doesn't do).

    `trials` deflates the combo's OWN param-search overfit (how many param variants were tried ON this combo) —
    this is the legitimate per-combo Deflated-Sharpe guard, NEVER a cross-combo/family count. `buy_and_hold` is THIS
    symbol's buy-and-hold over its validation window (caller computes it for the one symbol). `holdout_run` is this
    combo's untouched holdout run (None → the no-evidence sentinel, exactly like the pooled empty-holdout path)."""
    sr_obs, skew, kurt, n_obs = sample_moments(run.bar_returns)
    pbo = _pbo_proxy(run, trials)
    win_rate = _win_rate(run.trades)
    profit_factor = _profit_factor(run.trades)
    folds_positive = sum(1 for value in run.fold_returns if value > 0)
    folds_pct = folds_positive / len(run.fold_returns) if run.fold_returns else 0.0
    hr = holdout_run if holdout_run is not None else _empty_symbol_run()
    h_sr, h_skew, h_kurt, h_n = sample_moments(hr.bar_returns)
    holdout_dsr = probabilistic_sharpe(h_sr, h_n, h_skew, h_kurt, 0.0) - 0.5
    return BacktestMetrics(
        oos_return=Decimal(str(round(run.total_return, 8))),
        buy_and_hold_return=Decimal(str(round(buy_and_hold, 8))),
        sharpe=Decimal(str(round(run.sharpe, 6))),
        sortino=Decimal(str(round(run.sortino, 6))),
        max_drawdown=Decimal(str(round(run.max_drawdown, 6))),
        win_rate=Decimal(str(round(win_rate, 6))),
        num_trades=len(run.trades),
        sharpe_per_obs=Decimal(str(round(sr_obs, 8))),
        skew=Decimal(str(round(skew, 6))),
        kurtosis=Decimal(str(round(kurt, 6))),
        n_obs=n_obs,
        pbo=pbo,
        trials_counted=trials,
        folds_positive_pct=Decimal(str(round(folds_pct, 6))),
        holdout_deflated_sharpe=Decimal(str(round(holdout_dsr, 6))),
        regime_returns={k: round(v, 8) for k, v in run.regime_pnl.items()},
        profit_factor=Decimal(str(round(profit_factor, 6))),
    )


def equity_curve_points(run: SymbolRun, *, base: float = 100_000.0) -> list[dict[str, object]]:
    """Reconstruct ONE cell's NET-of-fee equity curve from its SymbolRun — the SAME per-bar stream the cell's
    metrics score on. Cumulates (1 + bar_returns[i]) from `base` (the sim capital) and pairs each point with its
    bar timestamp (bar_ts[i]), so point i is the marked, net-of-fee equity AT that bar. This is exactly the
    mark-to-market equity the backtest derived `bar_returns` from — fees + slippage + funding already charged on
    every fill — never a gross/pre-cost reconstruction. Returns a list of {"ts", "net"} points (the shape the
    strat sheet's per-cell Backtest curve renders), empty when the run carries no timestamped returns (a degenerate
    cell that never traded). Pure display/serialization helper: it READS a SymbolRun and is no gate input, so the
    locked scorer/FDR/cohort math is byte-unchanged."""
    n = min(len(run.bar_returns), len(run.bar_ts))
    points: list[dict[str, object]] = []
    equity = base
    for i in range(n):
        equity *= 1.0 + run.bar_returns[i]
        points.append({"ts": run.bar_ts[i], "net": round(equity, 4)})
    return points


def _parse_ts(ts: object) -> datetime | None:
    """A bar timestamp (ISO string or datetime) → datetime, or None when unparseable. Tolerant of a trailing 'Z'
    (treated as +00:00, the UTC offset Python's fromisoformat rejected before 3.11)."""
    if isinstance(ts, datetime):
        return ts
    if not ts:
        return None
    s = str(ts).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def cell_window_days(run: SymbolRun) -> float | None:
    """The CALENDAR-day span of ONE cell's OWN validation window — the elapsed days between its first and last bar
    timestamp (SymbolRun.bar_ts IS the validation stream). The read layer annualizes THIS cell's standalone return
    over THIS window, so a recently-listed coin (150 bars) is no longer annualized over a sibling's 800-bar window
    (the cross-window non-comparability the brut model forbids). Returns None when the run has < 2 parseable
    timestamps (nothing to span) — an honest unknown the screener renders as '—'. Pure display/persistence helper:
    it READS a SymbolRun and is NO gate input, so the locked scorer/FDR/cohort math is byte-unchanged."""
    ts = [t for t in (_parse_ts(t) for t in (run.bar_ts or [])) if t is not None]
    if len(ts) < 2:
        return None
    span = (max(ts) - min(ts)).total_seconds() / 86400.0
    return span if span > 0 else None


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


# Minimum overlapping bars before a symbol pair's cross-correlation is trusted. Below this, two streams from
# different calendars share too few dates to estimate Pearson honestly, so the pair is DROPPED from the average
# rather than fabricating a haircut from a handful of coincidental timestamps.
_MIN_CORR_OVERLAP = 30


def _pearson_on_common(
    a: list[float], a_ts: list[str], b: list[float], b_ts: list[str]
) -> float | None:
    """Pearson correlation of two return streams aligned on their COMMON bar timestamps (an INNER JOIN on dates,
    not a positional one). Returns None when fewer than `_MIN_CORR_OVERLAP` timestamps overlap — the join is too
    thin to trust, so the caller drops the pair. This is what keeps a mixed-calendar pool honest: equity sessions
    are a subset of crypto's 24/7 grid, so the legs are correlated on the days they SHARE, never by raw index."""
    by_ts_a = dict(zip(a_ts, a, strict=False))
    by_ts_b = dict(zip(b_ts, b, strict=False))
    common = sorted(by_ts_a.keys() & by_ts_b.keys())
    if len(common) < _MIN_CORR_OVERLAP:
        return None
    return _pearson([by_ts_a[t] for t in common], [by_ts_b[t] for t in common])


def _avg_cross_correlation(
    series: list[list[float]], timestamps: list[list[str]] | None = None
) -> float:
    """Average pairwise Pearson correlation across symbol return streams. 0 when fewer than two usable streams.
    The diversification haircut on the pooled observation count uses this.

    With `timestamps` (per-stream ISO bar labels, parallel to each return stream) each pair is inner-joined on
    its COMMON timestamps before correlating, and a pair with fewer than `_MIN_CORR_OVERLAP` shared bars is
    dropped. This is mandatory once calendars are mixed: a pooled equity (≈252 sessions/yr) + crypto/HL (365)
    spec has streams that DON'T line up by index, so a positional alignment reads a spurious ≈0 and under-deflates
    n_obs. Without `timestamps` it falls back to the legacy common-tail positional alignment, so single-calendar
    crypto cohorts (and any direct caller passing bare streams) stay byte-identical."""
    usable = [(i, s) for i, s in enumerate(series) if len(s) >= 2]
    if len(usable) < 2:
        return 0.0
    corrs: list[float] = []
    for a in range(len(usable)):
        for b in range(a + 1, len(usable)):
            ia, sa = usable[a]
            ib, sb = usable[b]
            if timestamps is not None:
                c = _pearson_on_common(sa, timestamps[ia], sb, timestamps[ib])
            else:
                c = _pearson(sa, sb)
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


def _symbol_buy_and_hold(val_bars: list[Bar], fee_bps: float | Decimal) -> float:
    """Net-of-fee buy-and-hold over ONE symbol's VALIDATION slice (already-split val_bars) — buy at the first
    close, sell at the last, charged one round-trip fee. The brut per-combo gate beats THIS cell's own benchmark
    (not the pooled basket average). 0.0 when there is no usable price. Same formula as `_buy_and_hold_return`'s
    per-symbol step, given the already-split window so the benchmark matches the cell's val_run exactly."""
    if not val_bars:
        return 0.0
    fee = float(fee_bps) / 10000.0
    first, last = float(val_bars[0].close), float(val_bars[-1].close)
    if not first:
        return 0.0
    return last / first - 1.0 - 2.0 * fee


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
    *,
    periods_per_year: float | None = None,
    target_vol: float | None = None,
) -> SymbolRun:
    # `periods_per_year` annualizes this symbol's Sharpe/Sortino on its OWN calendar (set by the caller from the
    # symbol's asset class). None → the 365-session crypto default for `bar_size`, so a direct caller (or any
    # single-asset crypto path) is byte-identical to before the cross-asset calendar fix.
    if periods_per_year is None:
        periods_per_year = _periods_per_year(spec.horizon.bar_size, None)
    # direction: +1 long (the spot/upside-only default), -1 short (perp/short leg). 0 is reserved (no per-bar
    # direction signal yet) and is treated as long so existing condition-only specs are unchanged. `d` is the
    # signed multiplier used to mirror every long inequality into its short counterpart.
    d = -1 if getattr(spec, "direction", 1) == -1 else 1
    closes = [float(bar.close) for bar in bars]
    highs = [float(bar.high) for bar in bars]
    lows = [float(bar.low) for bar in bars]
    features = _feature_matrix(spec, params, bars, alt)
    # ATR-multiple stop (ExitRules.atr_mult): the entry-bar stop distance is `atr_mult × ATR` (ATR as a fraction
    # of price). Compute the ATR series here when the spec uses it, with the same default-14 lookback as the
    # registry feature; None on a bar (warm-up / no data) → the entry falls back to the fixed stop fraction.
    atr_mult = (
        max(0.0, float(params[spec.exit.atr_mult.param])) if spec.exit.atr_mult is not None else None
    )
    atr_series = (
        _atr(highs, lows, closes, _lookback_for("atr", spec, params)) if atr_mult is not None else None
    )
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
    equity_ts: list[str] = []  # bar timestamp parallel to each equity point — carried out for calendar-aware pooling
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
    # STANDALONE trailing stop (ExitRules.trailing_stop) — armed at entry (or after `arm_after_profit` of profit),
    # independent of the multi-TP runner. `trail_dist` is the trail fraction; `trail_arm` is the profit cushion
    # required before it starts trailing (None → arm immediately). Both None when the spec has no trailing_stop,
    # so every existing spec is byte-identical.
    ts_rule = spec.exit.trailing_stop
    trail_dist = max(0.0, float(params[ts_rule.distance.param])) if ts_rule is not None else None
    trail_arm = (
        max(0.0, float(params[ts_rule.arm_after_profit.param]))
        if ts_rule is not None and ts_rule.arm_after_profit is not None
        else None
    )
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

    def _notional_at(idx_now: int) -> float:
        """The entry notional this combo would deploy at bar `idx_now`, sized through the SHARED size_fraction.
        T1 (target_vol set) passes the trailing POINT-IN-TIME closes `closes[:idx_now + 1]` (the decision bar's
        close is known when the entry is taken — the SAME window the live executor reads) so the backtest's
        realized-vol scaling matches the paper/live path. target_vol is THIS combo's own anchor (no sibling
        mixing). The size_series/size_multiplier tilt is applied as before — vol is NOT routed through it (that
        seam multiplies → the double-count trap the sizing roadmap warns against). T0 (target_vol None) passes
        no closes → byte-identical to the prior path."""
        trailing = closes[: idx_now + 1] if target_vol is not None else None
        return _entry_notional(cash, spec, _size_at(idx_now), closes=trailing, target_vol=target_vol)

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
        slip = _slippage(base_slip, impact, _notional_at(idx), bar)
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
            if trail_dist is not None:
                # STANDALONE trailing stop: arm once profit (favourable move from entry) clears `trail_arm`
                # (or immediately when trail_arm is None), then trail behind the favourable extreme. It only ever
                # RAISES the stop (max for a long, min for a short) — never loosens it past the fixed stop.
                profit = d * (extreme_since_entry - entry_price) / entry_price if entry_price else 0.0
                if trail_arm is None or profit >= trail_arm:
                    trail = extreme_since_entry * (1 - d * trail_dist)
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
            notional = _notional_at(idx) * meta_mult if take else 0.0
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
                # The initial stop DISTANCE (fraction of entry): `atr_mult × ATR` when the spec uses an
                # ATR-multiple stop AND the ATR is available at the SIGNAL bar (idx-1, point-in-time — the same
                # bar the entry decision reads), else the fixed `stop_pct`. ATR is already a fraction of price,
                # so `atr_mult × atr` is directly a stop fraction. Warm-up / no ATR → fixed stop (never unprotected).
                entry_stop_pct = stop_pct
                if atr_mult is not None and atr_series is not None:
                    atr_at = atr_series[idx - 1] if 0 <= idx - 1 < len(atr_series) else None
                    if atr_at is not None and atr_at > 0:
                        entry_stop_pct = atr_mult * float(atr_at)
                # Stop sits the adverse side of entry: below for a long, above for a short.
                stop_price = entry_price * (1 - d * entry_stop_pct)
                tp1_filled = False
                legs_filled = set()
                extreme_since_entry = float(bar.high) if d == 1 else float(bar.low)
                funding_accrued = 0.0

        # Mark-to-market. For a long this is the EXACT original `cash + position*close`. For a short, cash
        # already holds the sale proceeds (+notional) so the open leg is marked as a liability `-position*close`.
        equity = cash + d * position * closes[idx]
        high_water = max(high_water, equity)
        equity_points.append(equity)
        equity_ts.append(bar.ts.isoformat())

    if position > 0:
        slip = _slippage(base_slip, impact, position * closes[-1], bars[-1])
        _book(position, closes[-1] * (1 - d * slip), len(bars) - 1)
        position = 0.0
        equity_points.append(cash)
        equity_ts.append(bars[-1].ts.isoformat())  # final liquidation marks at the last bar

    return _symbol_metrics(equity_points, trades, periods_per_year=periods_per_year, equity_ts=equity_ts)


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


def _entry_notional(
    cash: float,
    spec: StrategySpec,
    size_multiplier: float,
    *,
    closes: list[float] | None = None,
    target_vol: float | None = None,
) -> float:
    # size_fraction(spec) is the SHARED fraction — identical to what paper_step/live deploy (audit #7 parity).
    # size_multiplier is a backtest-only capacity/meta tilt (1.0 in the production gate path).
    #
    # T1 PARITY (realism, per-combo): when this combo is sized with the vol-target envelope (closes AND
    # target_vol supplied), the backtest deploys the SAME notional the paper/live executor will — the brut
    # per-combo gate then scores the physics the track actually trades, not a static T0 fraction. `closes` is
    # the trailing POINT-IN-TIME price level series up to the decision bar (NOT the future), and `target_vol`
    # is THIS combo's OWN frozen vol anchor (from its OWN validation window — no sibling mixing). When either is
    # absent, size_fraction falls back to T0 and the result is byte-identical to before (the audit #7 parity
    # invariant in test_backtest_paper_live_parity).
    from cosmu.master.sizing import size_fraction
    frac = size_fraction(spec, closes=closes, target_vol=target_vol)
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


def align_asof(
    points: list[AltDataPoint], bars: list[Bar], *, max_age: timedelta | None = None
) -> dict[str, float]:
    """Point-in-time join of an alt-data series onto a bar series. Each bar gets the LATEST alt value whose
    `available_at` is <= that bar's timestamp — i.e. what we would actually have known at the bar. A point
    published after the bar is NEVER used (no look-ahead). Keyed by bar.ts.isoformat() so the value travels
    with the bar through any later slice (validation / holdout). Bars before the first available point get no
    entry (the feature reads None there, exactly as if the data did not exist yet).

    `max_age` (B5 staleness guard): an upper bound on how OLD a carried-forward value may be relative to the bar.
    A real point-in-time read of a daily feed at a bar 60 days after the last publish would be 60 days stale — a
    leakage-adjacent footgun (the gate treats a dead feed as a live, constant signal). When set, a bar whose
    newest known point is older than `max_age` gets NO entry (the feature reads None — honest "we'd have had no
    fresh data"), and the clamp is LOGGED. None (default) preserves the original carry-forever behaviour."""
    if not points or not bars:
        return {}
    pts = sorted(points, key=lambda p: p.available_at)
    out: dict[str, float] = {}
    i = 0
    current: float | None = None
    current_at = None  # available_at of the value currently carried forward (for the staleness clamp)
    clamped = 0
    for bar in sorted(bars, key=lambda b: b.ts):
        while i < len(pts) and pts[i].available_at <= bar.ts:
            current = pts[i].value
            current_at = pts[i].available_at
            i += 1
        if current is None:
            continue
        if max_age is not None and current_at is not None and (bar.ts - current_at) > max_age:
            clamped += 1  # the freshest known value is staler than the feed's tolerated age → read None here
            continue
        out[bar.ts.isoformat()] = current
    if clamped:
        _log.info("align_asof clamped %d stale bars (max_age=%s) — dead-feed values not carried forward", clamped, max_age)
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
    # ATR-multiple stop needs the ATR series warm before the first entry so the entry-bar stop is real (not the
    # fixed fallback). Add its lookback so the warm-up band covers it. No atr_mult → unchanged.
    if spec.exit.atr_mult is not None:
        lookbacks.append(_lookback_for("atr", spec, params))
    return max([20, *lookbacks]) + 2


def _bars_per_day(bar_size: str) -> float:
    return {"1h": 24.0, "4h": 6.0, "1d": 1.0}[bar_size]


# Trading SESSIONS per year by asset class — the annualization base for Sharpe/Sortino. Crypto/HL perps and
# prediction markets trade 24/7 (365 sessions); equities and FX follow a ~252-session exchange-weekday year
# (mirrors the calendars in cosmu.core.calendars). A pooled cross-asset spec MUST annualize each leg on its OWN
# calendar, or the equity leg's Sharpe is over-stated by √(365/252) ≈ 1.2× (Sharpe scales with √periods).
_SESSIONS_PER_YEAR: dict[str, float] = {"crypto": 365.0, "prediction": 365.0, "equity": 252.0, "fx": 252.0}
_DEFAULT_SESSIONS_PER_YEAR = 365.0  # crypto-native default → single-asset crypto specs stay byte-identical


def _periods_per_year(bar_size: str, asset_class: str | None) -> float:
    """Annualization factor: trading sessions/yr for the symbol's asset class × bars/session for the bar size.
    `asset_class` None or unknown → the 365-session crypto default, so an unlabelled (crypto) backtest is
    byte-identical to before the cross-asset calendar fix."""
    sessions = _SESSIONS_PER_YEAR.get(asset_class, _DEFAULT_SESSIONS_PER_YEAR) if asset_class else _DEFAULT_SESSIONS_PER_YEAR
    return sessions * _bars_per_day(bar_size)


def _symbol_metrics(
    equity: list[float],
    trades: list[Trade],
    *,
    periods_per_year: float,
    equity_ts: list[str] | None = None,
) -> SymbolRun:
    if len(equity) < 2:
        return _empty_symbol_run(trades)
    returns = [(equity[i] / equity[i - 1] - 1.0) if equity[i - 1] else 0.0 for i in range(1, len(equity))]
    # bar_ts[i] labels returns[i] — the transition INTO equity[i+1] — with that bar's timestamp, so the pooled
    # cross-symbol correlation can inner-join calendars. equity_ts is parallel to `equity`, so drop its first
    # entry (there is no return before the first equity point). Empty when no timestamps were carried.
    bar_ts = list(equity_ts[1:len(returns) + 1]) if equity_ts else []
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
        bar_ts=bar_ts,
        fold_returns=_fold_returns(equity),
        regime_pnl=regime_pnl,
        periods_per_year=periods_per_year,
    )


def _combine(runs: list[SymbolRun]) -> SymbolRun:
    if not runs:
        return _empty_symbol_run()
    trades = [trade for run in runs for trade in run.trades]
    bar_returns = [ret for run in runs for ret in run.bar_returns]
    bar_ts = [ts for run in runs for ts in run.bar_ts]
    fold_returns = [ret for run in runs for ret in run.fold_returns]
    # Bar-count-weighted annualization: the pooled stream is a concatenation, so each symbol contributes its OWN
    # calendar's periods/yr weighted by how many bars it supplies. A pooled equity(252)+crypto(365) book lands
    # between the two by bar share — never a flat 365 that over-states the equity leg. Single-asset or same-class
    # pools are unchanged: one run → its own value; all-equal periods/yr → the weighted mean equals that value.
    total_bars = sum(len(run.bar_returns) for run in runs)
    periods_per_year = (
        sum(len(run.bar_returns) * run.periods_per_year for run in runs) / total_bars
        if total_bars
        else statistics.fmean(run.periods_per_year for run in runs)
    )
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
        bar_ts=bar_ts,
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
    # Field order: total_return, sharpe, sortino, max_drawdown, trades, bar_returns, bar_ts, fold_returns,
    # regime_pnl, periods_per_year.
    return SymbolRun(0.0, 0.0, 0.0, 1.0, trades or [], [], [], [], {}, 365.0)


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
