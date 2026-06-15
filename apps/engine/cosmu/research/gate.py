# intent: the edge-existence gate — run a small, attempt-capped set of hand-built social-momentum signals through the deterministic wall and a pre-registered pass bar, to answer "does an exploitable edge exist on Binance spot after costs?" before any factory is built; inputs: bars + alt-data + store; outputs: a PASS/STOP GateVerdict; invariants: signals computed directly (no indicator-lib path), every attempt counted in the global trial ledger, the pass bar is pre-registered and the gate cannot be silently p-hacked.

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from cosmu.data.altdata import AltDataProvider, NewsProvider, read_pit_fee, read_pit_fee_resolver, rolling_zscore
from cosmu.data.backtest import DEFAULT_IMPACT_BPS, DEFAULT_SLIPPAGE_BPS
from cosmu.data.market import Bar
from cosmu.data.sources.multiasset import MULTIASSET_METRICS
from cosmu.experiments import ExperimentRecord, data_version, log_experiments
from cosmu.spine.venue import default_catalog
from cosmu.ingest.standardize import standardize_news
from cosmu.knowledge.store import Store
from cosmu.master.scorer import (
    BacktestMetrics,
    ScoreVerdict,
    cscv_pbo,
    probabilistic_sharpe,
    sample_moments,
    score,
)
from cosmu.master.trials import record_trial, trial_stats

# Pre-registered pass bar — fixed BEFORE looking. Changing it after a run is itself a new trial.
PREREGISTERED_BAR = {
    "min_trades": 30,
    "min_deflated_sharpe_prob": 0.95,
    "max_cscv_pbo": 0.50,
    "min_regimes_positive": 2,
    "max_drawdown": 0.25,
    "must_beat_buy_and_hold": True,
    "attempt_budget": 12,
}

# The capped variant grid (= 12 attempts), all long-only social-momentum on a rolling z-score.
_LOOKBACKS = (14, 30)
_Z_THRESHOLDS = (0.5, 1.0, 1.5)
_HOLD_BARS = (5, 10)
# Static catalog fallback fee (bps → fraction) used when no PIT fee snapshot is available.
# A per-bar PIT read (read_pit_fee) is preferred; this is only the offline/pre-first-ingest default.
_FEE_FALLBACK_BPS: float = float(default_catalog().venue("binance").taker_fee_bps)
# Cost model: the Gate's `_simulate` shares the EXACT slippage + market-impact curve and bps defaults that
# `data/backtest.py::run_strategy_backtest` uses (DEFAULT_SLIPPAGE_BPS half-spread + DEFAULT_IMPACT_BPS
# participation-scaled impact via `_slippage`). The old flat 5bps-no-impact model is gone, so a single-signal
# Gate can no longer bless a fill the StrategySpec backtest could not trade.
_BASE_SLIP: float = float(DEFAULT_SLIPPAGE_BPS) / 10000.0
_IMPACT: float = float(DEFAULT_IMPACT_BPS) / 10000.0
_STOP = 0.08
_TAKE = 0.16


def _pit_fee(store: Store, venue_id: str, symbol: str, as_of: "datetime") -> float:
    """PIT taker fee fraction for a gate simulation bar.  Falls back to the static catalog
    so the gate never crashes without a fee snapshot."""
    bps = read_pit_fee(store, venue_id, symbol, "venue_fees_taker", as_of, fallback_bps=_FEE_FALLBACK_BPS)
    return (bps if bps is not None else _FEE_FALLBACK_BPS) / 10000.0


def _pit_fee_fn(store: "Store | None", venue_id: str, symbol: str):
    """A per-bar taker-fee FRACTION resolver that reads the venue_fees series ONCE (not per bar) — PIT-IDENTICAL
    to calling `_pit_fee(store, venue_id, symbol, ts)` for each bar's ts, but without a DB round-trip per bar.
    The per-bar `_pit_fee` opened a fresh SQLite/PG connection for every bar of every simulation, which made the
    cross-asset ablation open thousands of connections and hang the engine suite under parallel I/O. Build this
    ONCE before a per-bar loop; the resolved fee values are unchanged (the gate's cost model is untouched)."""
    if store is None:
        frac = _FEE_FALLBACK_BPS / 10000.0
        return lambda _ts: frac
    resolve_bps = read_pit_fee_resolver(store, venue_id, symbol, "venue_fees_taker", fallback_bps=_FEE_FALLBACK_BPS)

    def fee(ts: "datetime") -> float:
        bps = resolve_bps(ts)
        return (bps if bps is not None else _FEE_FALLBACK_BPS) / 10000.0

    return fee


@dataclass(frozen=True)
class SignalParams:
    lookback: int
    z_threshold: float
    hold_bars: int

    @property
    def name(self) -> str:
        return f"social_z>{self.z_threshold}@{self.lookback}/{self.hold_bars}"


@dataclass
class VariantResult:
    params: SignalParams
    metrics: BacktestMetrics
    verdict: ScoreVerdict
    val_return: float
    val_returns: list[float]


@dataclass
class GateVerdict:
    decision: str  # "PASS" | "STOP"
    passed: bool
    best_signal: str
    deflated_sharpe_prob: float
    cscv_pbo: float
    buy_and_hold_return: float
    best_return: float
    regimes_positive: int
    num_trades: int
    max_drawdown: float
    attempts: int
    bar: dict = field(default_factory=lambda: dict(PREREGISTERED_BAR))
    reasons: list[str] = field(default_factory=list)


def evaluate_gate(
    market: dict[str, list[Bar]],
    altdata: AltDataProvider,
    store: Store,
    *,
    metric: str = "galaxy_score",
) -> GateVerdict:
    """Run the variant grid through the wall, deflate against the global trial count, apply the
    pre-registered bar, and emit PASS/STOP. Every variant is recorded as a trial."""
    aligned = _aligned_market(market, altdata, metric)
    variants = [SignalParams(lb, z, hb) for lb in _LOOKBACKS for z in _Z_THRESHOLDS for hb in _HOLD_BARS]
    variants = variants[: PREREGISTERED_BAR["attempt_budget"]]

    results: list[VariantResult] = []
    for params in variants:
        metrics, val_return, val_returns = _run_variant(aligned, params, store=store)
        record_trial(store, float(metrics.sharpe_per_obs), source="edge_gate", label=params.name)
        verdict = score(metrics, _gate_gates(store), trials=trial_stats(store))
        results.append(VariantResult(params, metrics, verdict, val_return, val_returns))

    pbo = cscv_pbo([r.val_returns for r in results if r.val_returns]) if results else 1.0
    buy_hold = _buy_and_hold(market, store=store)
    best = max(results, key=lambda r: r.verdict.deflated_sharpe_prob) if results else None

    if best is None:
        return GateVerdict("STOP", False, "none", 0.0, pbo, buy_hold, 0.0, 0, 0, 1.0, 0, reasons=["no_variants"])

    regimes_positive = sum(1 for v in best.metrics.regime_returns.values() if v > 0)
    dsr = float(best.verdict.deflated_sharpe_prob)
    reasons: list[str] = []
    if best.metrics.num_trades < PREREGISTERED_BAR["min_trades"]:
        reasons.append("min_trades")
    if dsr < PREREGISTERED_BAR["min_deflated_sharpe_prob"]:
        reasons.append("deflated_sharpe")
    if pbo >= PREREGISTERED_BAR["max_cscv_pbo"]:
        reasons.append("cscv_pbo")
    if regimes_positive < PREREGISTERED_BAR["min_regimes_positive"]:
        reasons.append("regimes")
    if float(best.metrics.max_drawdown) >= PREREGISTERED_BAR["max_drawdown"]:
        reasons.append("max_drawdown")
    if PREREGISTERED_BAR["must_beat_buy_and_hold"] and best.val_return <= buy_hold:
        reasons.append("buy_and_hold")

    passed = not reasons
    # Experiment-tracking hook: every variant logged with its forward-P&L soft-label (gradient for the ranker).
    _log_gate_experiments(
        store, kind="edge_gate", source="edge_gate", market=market,
        items=[
            (r.params.name,
             {"lookback": r.params.lookback, "z_threshold": r.params.z_threshold, "hold_bars": r.params.hold_bars},
             r.metrics, r.val_return, None)
            for r in results
        ],
    )
    return GateVerdict(
        decision="PASS" if passed else "STOP",
        passed=passed,
        best_signal=best.params.name,
        deflated_sharpe_prob=round(dsr, 6),
        cscv_pbo=round(pbo, 6),
        buy_and_hold_return=round(buy_hold, 6),
        best_return=round(best.val_return, 6),
        regimes_positive=regimes_positive,
        num_trades=best.metrics.num_trades,
        max_drawdown=round(float(best.metrics.max_drawdown), 6),
        attempts=len(results),
        reasons=reasons,
    )


def _gate_gates(store: Store):  # noqa: ANN202 - returns GateSettings
    from cosmu.config.settings import get_settings

    return get_settings().gates


def _log_gate_experiments(store: Store, *, kind: str, source: str, market: dict, items: list) -> None:
    """Thin, best-effort experiment-tracking hook for the gate engines. `items` is a list of
    (label, config, metrics, forward_pnl, gate_passed|None): each variant/arm becomes one registry row carrying
    its exact config + the run seed + the input data_version (comparable + regenerable) and its continuous
    forward-P&L SOFT-LABEL (the ML ranker's gradient before any gate-pass exists). Never raises into the gate."""
    from cosmu.config.settings import get_settings

    dv = data_version(market)
    seed = int(get_settings().evolution.default_seed)
    records = [
        ExperimentRecord(
            kind=kind, source=source, label=label, config=config,
            metrics=metrics.model_dump(mode="json"), seed=seed, data_version=dv,
            soft_label=forward_pnl, gate_passed=passed,
        )
        for label, config, metrics, forward_pnl, passed in items
    ]
    log_experiments(store, records)


def _aligned_market(market: dict[str, list[Bar]], altdata: AltDataProvider, metric: str) -> dict[str, tuple[list[Bar], list[float | None]]]:
    out: dict[str, tuple[list[Bar], list[float | None]]] = {}
    for symbol, bars in market.items():
        points = altdata.fetch_series(symbol, metric, limit=len(bars) + 10)
        out[symbol] = (bars, _align(bars, [(p.available_at, p.value) for p in points]))
    return out


def _align(bars: list[Bar], points: list[tuple[datetime, float]]) -> list[float | None]:
    """Per-bar latest value whose availability time is <= the bar time (point-in-time)."""
    pts = sorted(points, key=lambda x: x[0])
    out: list[float | None] = []
    j = 0
    last: float | None = None
    for bar in bars:
        while j < len(pts) and pts[j][0] <= bar.ts:
            last = pts[j][1]
            j += 1
        out.append(last)
    return out


def _run_variant(
    aligned: dict[str, tuple[list[Bar], list[float | None]]],
    params: SignalParams,
    *,
    store: Store | None = None,
) -> tuple[BacktestMetrics, float, list[float]]:
    val_returns: list[float] = []
    val_total: list[float] = []
    regime_pnl: dict[str, float] = {}
    trades_all = 0
    wins = 0
    max_dd = 0.0
    fold_returns: list[float] = []
    h_returns: list[float] = []

    total_net_pnl = 0.0
    total_gross_pnl = 0.0
    for symbol, (bars, alt) in aligned.items():
        if len(bars) < 80:
            continue
        split = max(40, int(len(bars) * 0.8))
        z = rolling_zscore(alt, params.lookback)
        signal = [v is not None and v > params.z_threshold for v in z]
        v_eq, v_trades = _simulate(bars[:split], signal[:split], params, store=store, symbol=symbol)
        h_eq, _ = _simulate(bars[split:], signal[split:], params, store=store, symbol=symbol)
        val_returns.extend(_bar_returns(v_eq))
        h_returns.extend(_bar_returns(h_eq))
        if v_eq:
            val_total.append(v_eq[-1] / 100000.0 - 1.0)
            max_dd = max(max_dd, _max_dd(v_eq))
            fold_returns.extend(_folds(v_eq))
        for net_pnl, regime, gross_pnl in v_trades:
            regime_pnl[regime] = regime_pnl.get(regime, 0.0) + net_pnl
            trades_all += 1
            wins += 1 if net_pnl > 0 else 0
            total_net_pnl += net_pnl
            total_gross_pnl += gross_pnl

    sr, skew, kurt, n = sample_moments(val_returns)
    from cosmu.master.scorer import probabilistic_sharpe

    h_sr, h_skew, h_kurt, h_n = sample_moments(h_returns)
    holdout_dsr = probabilistic_sharpe(h_sr, h_n, h_skew, h_kurt, 0.0) - 0.5
    folds_pos = sum(1 for x in fold_returns if x > 0)
    # cost_ratio = net_edge / gross_edge (fraction of alpha that survives fees + slippage).
    cost_ratio = (total_net_pnl / total_gross_pnl) if total_gross_pnl != 0.0 else Decimal("0")
    metrics = BacktestMetrics(
        oos_return=Decimal(str(round(statistics.fmean(val_total) if val_total else 0.0, 8))),
        sharpe=Decimal(str(round(sr * math.sqrt(365), 6))),
        sortino=Decimal("0"),
        max_drawdown=Decimal(str(round(max_dd, 6))),
        win_rate=Decimal(str(round(wins / trades_all if trades_all else 0.0, 6))),
        num_trades=trades_all,
        sharpe_per_obs=Decimal(str(round(sr, 8))),
        skew=Decimal(str(round(skew, 6))),
        kurtosis=Decimal(str(round(kurt, 6))),
        n_obs=n,
        pbo=Decimal("0"),
        trials_counted=len(_LOOKBACKS) * len(_Z_THRESHOLDS) * len(_HOLD_BARS),
        folds_positive_pct=Decimal(str(round(folds_pos / len(fold_returns) if fold_returns else 0.0, 6))),
        holdout_deflated_sharpe=Decimal(str(round(holdout_dsr, 6))),
        regime_returns={k: round(v, 8) for k, v in regime_pnl.items()},
        cost_ratio=Decimal(str(round(float(cost_ratio), 6))),
    )
    val_return = statistics.fmean(val_total) if val_total else 0.0
    return metrics, val_return, val_returns


def _simulate(
    bars: list[Bar],
    signal: list[bool],
    params: SignalParams,
    *,
    store: Store | None = None,
    venue_id: str = "binance",
    symbol: str = "BTCUSDT",
) -> tuple[list[float], list[tuple[float, str, float]]]:
    """Simulate a signal on a bar sequence with PIT fees.

    When `store` is provided, each bar reads the fee that was in effect at that
    bar's timestamp (no look-ahead).  Without a store, falls back to the static
    catalog taker fee — matches the pre-P0.4 behaviour so existing tests are
    unaffected.

    Returns (equity_curve, trades).  Each trade is (net_pnl, regime, gross_pnl) where
    gross_pnl is the price-only return (slippage only, no fees) — used to compute cost_ratio.

    Cost model: slippage is the SHARED participation-scaled curve from `data/backtest.py::_slippage`
    (half-spread `_BASE_SLIP` + `_IMPACT * sqrt(notional/bar_quote_volume)`), with the SAME bps defaults
    the StrategySpec backtest uses. There is no separate softer Gate cost model: a fill the Gate prices is
    priced identically by `run_strategy_backtest`, so the two cannot disagree on net-of-fee profit.
    """
    from cosmu.data.backtest import _regime_labels, _slippage

    closes = [float(b.close) for b in bars]
    regimes = _regime_labels(closes)
    cash = 100000.0
    pos = 0.0
    entry = 0.0
    entry_fee = 0.0  # taker fee fraction at entry bar
    entry_idx = 0
    equity: list[float] = []
    trades: list[tuple[float, str, float]] = []
    # Read the PIT fee series ONCE (not per bar): per-bar `_pit_fee` opened a DB connection every bar — thousands
    # per ablation — which hung the suite. `fee_fn(ts)` is PIT-identical to `_pit_fee(store,…,ts)`, in memory.
    fee_fn = _pit_fee_fn(store, venue_id, symbol)
    for i in range(1, len(bars)):
        b = bars[i]
        fee = fee_fn(b.ts)
        # Per-bar slippage on the SAME participation basis the backtest uses: the prospective entry notional
        # (cash * 0.2) against this bar's quote-volume. Applied to entry AND any exit on this bar, exactly as
        # `_run_symbol` computes one `slip` per bar from `_entry_notional`.
        slip = _slippage(_BASE_SLIP, _IMPACT, cash * 0.2, b)
        if pos > 0:
            stop_p = entry * (1 - _STOP)
            take_p = entry * (1 + _TAKE)
            xp: float | None = None
            if float(b.low) <= stop_p:
                xp = stop_p * (1 - slip)
            elif float(b.high) >= take_p:
                xp = take_p * (1 - slip)
            elif i - entry_idx >= params.hold_bars:
                xp = float(b.open) * (1 - slip)
            if xp is not None:
                cash += pos * xp * (1 - fee)
                net_pnl = (xp * (1 - fee) - entry * (1 + entry_fee)) / entry
                # gross pnl = price move only (entry slippage applied, no fees)
                gross_pnl = (xp - entry) / entry
                trades.append((net_pnl, regimes[entry_idx], gross_pnl))
                pos = 0.0
                entry = 0.0
                entry_fee = 0.0
        if pos == 0 and i - 1 < len(signal) and signal[i - 1]:
            notional = cash * 0.2
            fill = float(b.open) * (1 + slip)
            pos = notional * (1 - fee) / fill
            cash -= notional
            entry = fill
            entry_fee = fee
            entry_idx = i
        equity.append(cash + pos * closes[i])
    if pos > 0:
        b = bars[-1]
        fee = fee_fn(b.ts)
        # Forced final close: slip on the actual open-leg notional vs the last bar, mirroring `_run_symbol`'s
        # closing `_slippage(base_slip, impact, position*closes[-1], bars[-1])`.
        slip = _slippage(_BASE_SLIP, _IMPACT, pos * closes[-1], b)
        xp = closes[-1] * (1 - slip)
        cash += pos * xp * (1 - fee)
        net_pnl = (xp * (1 - fee) - entry * (1 + entry_fee)) / entry
        gross_pnl = (xp - entry) / entry
        trades.append((net_pnl, regimes[entry_idx], gross_pnl))
        equity.append(cash)
    return equity, trades


def _bar_returns(equity: list[float]) -> list[float]:
    return [(equity[i] / equity[i - 1] - 1.0) if equity[i - 1] else 0.0 for i in range(1, len(equity))]


def _max_dd(equity: list[float]) -> float:
    high = equity[0] if equity else 0.0
    dd = 0.0
    for v in equity:
        high = max(high, v)
        if high:
            dd = max(dd, (high - v) / high)
    return dd


def _folds(equity: list[float], folds: int = 4) -> list[float]:
    if len(equity) < folds * 2:
        return []
    size = len(equity) // folds
    out = []
    for idx in range(folds):
        chunk = equity[idx * size : (idx + 1) * size if idx < folds - 1 else len(equity)]
        if len(chunk) > 1 and chunk[0]:
            out.append(chunk[-1] / chunk[0] - 1.0)
    return out


def _buy_and_hold(market: dict[str, list[Bar]], *, store: Store | None = None, venue_id: str = "binance") -> float:
    refs = [s for s in ("BTCUSDT", "ETHUSDT") if s in market] or list(market)
    rets = []
    for symbol in refs:
        bars = market[symbol]
        if len(bars) < 80:
            continue
        split = max(40, int(len(bars) * 0.8))
        window = bars[:split]
        first, last = float(window[0].close), float(window[-1].close)
        if first:
            entry_fee = _pit_fee(store, venue_id, symbol, window[0].ts) if store is not None else _FEE_FALLBACK_BPS / 10000.0
            exit_fee = _pit_fee(store, venue_id, symbol, window[-1].ts) if store is not None else _FEE_FALLBACK_BPS / 10000.0
            rets.append(last / first - 1.0 - entry_fee - exit_fee)
    return statistics.fmean(rets) if rets else 0.0


# ============================================================================================
# Phase 1.5 — the aggregation-edge ablation gate.
# Three arms on the same universe/costs/wall: price-only vs +alt-data vs buy-and-hold, with a
# drop-one report so the owner learns WHICH source pays. Answers: does aggregating + standardizing
# multiple sources beat price alone, after costs, point-in-time? Runs fully offline on fixtures.
# ============================================================================================

ABLATION_BAR = {
    "min_trades": 30,
    "min_deflated_sharpe_prob": 0.95,
    "max_cscv_pbo": 0.50,
    "min_regimes_positive": 2,
    "max_drawdown": 0.25,
    "attempt_budget": 12,
}
_ARM = SignalParams(lookback=20, z_threshold=0.5, hold_bars=7)


@dataclass
class ArmResult:
    name: str
    metrics: BacktestMetrics
    verdict: ScoreVerdict
    val_return: float
    val_returns: list[float]


@dataclass
class DropOne:
    source: str
    sharpe_without: float  # alt arm's annualized Sharpe with this source removed
    delta: float  # full-alt Sharpe minus that — the source's marginal contribution (non-saturating)


@dataclass
class AblationVerdict:
    decision: str  # "PASS" | "STOP"
    passed: bool
    price_only_dsr: float
    alt_dsr: float
    price_only_return: float
    alt_return: float
    buy_and_hold_return: float
    cscv_pbo: float
    regimes_positive: int
    num_trades: int
    max_drawdown: float
    attempts: int
    drop_one: list[DropOne] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    bar: dict = field(default_factory=lambda: dict(ABLATION_BAR))
    data_source: str = "synthetic"


def _ablation_features(market, alt_provider, news_provider, lookback):  # noqa: ANN001
    cache: dict = {}
    counter: dict = {}
    feats: dict = {}
    for symbol, bars in market.items():
        closes = [float(b.close) for b in bars]
        price_z = rolling_zscore(closes, lookback)
        news_pts = standardize_news(news_provider.fetch_news(symbol, limit=len(bars) + 10), cache=cache, counter=counter)
        news_z = rolling_zscore(_align(bars, [(p.available_at, p.value) for p in news_pts]), lookback)
        fund_aligned = _align(bars, [(p.available_at, p.value) for p in alt_provider.fetch_series(symbol, "funding_rate", limit=len(bars) + 10)])
        fund_z = rolling_zscore(fund_aligned, lookback)
        fg_aligned = _align(bars, [(p.available_at, p.value) for p in alt_provider.fetch_series(symbol, "fear_greed", limit=len(bars) + 10)])
        feats[symbol] = (bars, {"price_z": price_z, "news_z": news_z, "funding_z": fund_z, "fg": fg_aligned})
    return feats, counter


def _p_price(f, i):  # noqa: ANN001
    v = f["price_z"][i]
    return v is not None and v > 0.5


def _p_news(f, i):  # noqa: ANN001
    v = f["news_z"][i]
    return v is not None and v > 0.0


def _p_fund(f, i):  # noqa: ANN001
    v = f["funding_z"][i]
    return v is None or v < 1.0  # skip only when funding is extremely high (crowded long)


def _p_fg(f, i):  # noqa: ANN001
    v = f["fg"][i]
    return v is None or v < 65.0  # buy fear/neutral, avoid extreme greed


_PREDICATES = {
    "price_only": lambda f, i: _p_price(f, i),
    "alt_full": lambda f, i: _p_price(f, i) and _p_news(f, i) and _p_fund(f, i) and _p_fg(f, i),
    "news": lambda f, i: _p_price(f, i) and _p_fund(f, i) and _p_fg(f, i),
    "funding": lambda f, i: _p_price(f, i) and _p_news(f, i) and _p_fg(f, i),
    "fear_greed": lambda f, i: _p_price(f, i) and _p_news(f, i) and _p_fund(f, i),
}


def _alt_predicate(price_thr: float):  # noqa: ANN201
    """Full alt arm with a tunable price-momentum threshold — used to build a diverse CSCV grid."""

    def pred(f, i):  # noqa: ANN001
        v = f["price_z"][i]
        return (v is not None and v > price_thr) and _p_news(f, i) and _p_fund(f, i) and _p_fg(f, i)

    return pred


def _build_signal(feats, predicate):  # noqa: ANN001
    return {symbol: (bars, [predicate(f, i) for i in range(len(bars))]) for symbol, (bars, f) in feats.items()}


def _arm_metrics(signal_market, store, label):  # noqa: ANN001
    val_returns: list[float] = []
    val_total: list[float] = []
    regime_pnl: dict[str, float] = {}
    trades = 0
    wins = 0
    max_dd = 0.0
    fold_returns: list[float] = []
    h_returns: list[float] = []
    total_net_pnl = 0.0
    total_gross_pnl = 0.0
    for symbol, (bars, signal) in signal_market.items():
        if len(bars) < 80:
            continue
        split = max(40, int(len(bars) * 0.8))
        v_eq, v_tr = _simulate(bars[:split], signal[:split], _ARM, store=store, symbol=symbol)
        h_eq, _ = _simulate(bars[split:], signal[split:], _ARM, store=store, symbol=symbol)
        val_returns.extend(_bar_returns(v_eq))
        h_returns.extend(_bar_returns(h_eq))
        if v_eq:
            val_total.append(v_eq[-1] / 100000.0 - 1.0)
            max_dd = max(max_dd, _max_dd(v_eq))
            fold_returns.extend(_folds(v_eq))
        for net_pnl, regime, gross_pnl in v_tr:
            regime_pnl[regime] = regime_pnl.get(regime, 0.0) + net_pnl
            trades += 1
            wins += 1 if net_pnl > 0 else 0
            total_net_pnl += net_pnl
            total_gross_pnl += gross_pnl

    sr, skew, kurt, n = sample_moments(val_returns)
    h_sr, h_skew, h_kurt, h_n = sample_moments(h_returns)
    holdout = probabilistic_sharpe(h_sr, h_n, h_skew, h_kurt, 0.0) - 0.5
    folds_pos = sum(1 for x in fold_returns if x > 0)
    cost_ratio = (total_net_pnl / total_gross_pnl) if total_gross_pnl != 0.0 else 0.0
    metrics = BacktestMetrics(
        oos_return=Decimal(str(round(statistics.fmean(val_total) if val_total else 0.0, 8))),
        sharpe=Decimal(str(round(sr * math.sqrt(365), 6))),
        sortino=Decimal("0"),
        max_drawdown=Decimal(str(round(max_dd, 6))),
        win_rate=Decimal(str(round(wins / trades if trades else 0.0, 6))),
        num_trades=trades,
        sharpe_per_obs=Decimal(str(round(sr, 8))),
        skew=Decimal(str(round(skew, 6))),
        kurtosis=Decimal(str(round(kurt, 6))),
        n_obs=n,
        pbo=Decimal("0"),
        trials_counted=5,
        folds_positive_pct=Decimal(str(round(folds_pos / len(fold_returns) if fold_returns else 0.0, 6))),
        holdout_deflated_sharpe=Decimal(str(round(holdout, 6))),
        regime_returns={k: round(v, 8) for k, v in regime_pnl.items()},
        cost_ratio=Decimal(str(round(cost_ratio, 6))),
    )
    record_trial(store, float(metrics.sharpe_per_obs), source="ablation", label=label)
    verdict = score(metrics, _gate_gates(store), trials=trial_stats(store))
    return ArmResult(label, metrics, verdict, statistics.fmean(val_total) if val_total else 0.0, val_returns)


def evaluate_ablation(
    market: dict[str, list[Bar]],
    alt_provider: AltDataProvider,
    news_provider: NewsProvider,
    store: Store,
    *,
    lookback: int = 20,
) -> AblationVerdict:
    """Three arms + drop-one, all through the same wall. Every arm is a counted trial."""
    feats, _ = _ablation_features(market, alt_provider, news_provider, lookback)
    price = _arm_metrics(_build_signal(feats, _PREDICATES["price_only"]), store, "price_only")
    alt = _arm_metrics(_build_signal(feats, _PREDICATES["alt_full"]), store, "alt_full")
    drops = {src: _arm_metrics(_build_signal(feats, _PREDICATES[src]), store, f"alt_drop_{src}") for src in ("news", "funding", "fear_greed")}

    buy_hold = _buy_and_hold(market, store=store)
    # Overfit guard via CSCV over a diverse alt-arm grid (lookback × momentum threshold) — a
    # legitimate config population. Nested ablation arms are correlated and would inflate PBO.
    variant_returns: list[list[float]] = []
    for lb in (14, 20, 30):
        feats_lb = feats if lb == lookback else _ablation_features(market, alt_provider, news_provider, lb)[0]
        for thr in (0.3, 0.8):
            variant_returns.append(_arm_metrics(_build_signal(feats_lb, _alt_predicate(thr)), store, f"alt_lb{lb}_z{thr}").val_returns)
    usable = [r for r in variant_returns if r]
    pbo = cscv_pbo(usable) if len(usable) >= 2 else 1.0
    alt_dsr = float(alt.verdict.deflated_sharpe_prob)
    alt_sharpe = float(alt.metrics.sharpe)
    drop_one = sorted(
        [DropOne(src, round(float(r.metrics.sharpe), 4), round(alt_sharpe - float(r.metrics.sharpe), 4)) for src, r in drops.items()],
        key=lambda d: d.delta,
        reverse=True,
    )
    regimes_positive = sum(1 for v in alt.metrics.regime_returns.values() if v > 0)

    reasons: list[str] = []
    if alt.val_return <= price.val_return:
        reasons.append("not_beating_price_only")
    if alt.val_return <= buy_hold:
        reasons.append("not_beating_buy_and_hold")
    if alt.metrics.num_trades < ABLATION_BAR["min_trades"]:
        reasons.append("min_trades")
    if alt_dsr < ABLATION_BAR["min_deflated_sharpe_prob"]:
        reasons.append("deflated_sharpe")
    if pbo >= ABLATION_BAR["max_cscv_pbo"]:
        reasons.append("cscv_pbo")
    if regimes_positive < ABLATION_BAR["min_regimes_positive"]:
        reasons.append("regimes")
    if float(alt.metrics.max_drawdown) >= ABLATION_BAR["max_drawdown"]:
        reasons.append("max_drawdown")

    passed = not reasons
    # Experiment-tracking hook: each ablation arm logged with its forward-P&L soft-label.
    _log_gate_experiments(
        store, kind="ablation", source="ablation", market=market,
        items=[
            (arm.name, {"arm": arm.name, "lookback": lookback}, arm.metrics, arm.val_return,
             passed if arm is alt else None)
            for arm in (price, alt, *drops.values())
        ],
    )
    return AblationVerdict(
        decision="PASS" if passed else "STOP",
        passed=passed,
        price_only_dsr=round(float(price.verdict.deflated_sharpe_prob), 6),
        alt_dsr=round(alt_dsr, 6),
        price_only_return=round(price.val_return, 6),
        alt_return=round(alt.val_return, 6),
        buy_and_hold_return=round(buy_hold, 6),
        cscv_pbo=round(pbo, 6),
        regimes_positive=regimes_positive,
        num_trades=alt.metrics.num_trades,
        max_drawdown=round(float(alt.metrics.max_drawdown), 6),
        attempts=2 + len(drops) + len(variant_returns),  # price + alt + drop-one + CSCV grid
        drop_one=drop_one,
        reasons=reasons,
    )


# ============================================================================================
# Phase 1.6 — the FOUR-arm cross-asset ablation. Same wall, same costs, one extra arm: does
# COMBINING asset classes (crypto + equity) with cross-asset transfer features beat the best
# single-asset arm AND buy-and-hold? Built on the proven 1.5 primitives (_build_signal, _arm_metrics,
# _simulate, _folds, sample_moments, score). The cross-asset transfer features (prediction-market
# risk_on + FRED macro_regime) are market-wide; the single-asset arms never see them.
# ============================================================================================

CROSS_ASSET_BAR = dict(ABLATION_BAR)  # identical statistical bar; the new check is arm-(3) dominance


@dataclass
class ClassDrop:
    asset_class: str
    sharpe_without: float  # cross-asset arm's annualized Sharpe with this whole class dropped from the universe
    delta: float           # full cross-asset Sharpe minus that — the class's marginal contribution


@dataclass
class CrossAssetVerdict:
    decision: str  # "PASS" | "STOP-narrow"
    passed: bool
    price_only_return: float
    single_alt_return: float
    xasset_return: float
    buy_and_hold_return: float
    xasset_dsr: float
    single_alt_dsr: float
    cscv_pbo: float
    regimes_positive: int
    num_trades: int
    max_drawdown: float
    attempts: int
    drop_one_source: list[DropOne] = field(default_factory=list)
    drop_one_class: list[ClassDrop] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    bar: dict = field(default_factory=lambda: dict(CROSS_ASSET_BAR))
    data_source: str = "synthetic"


def _xp_price(f, i, thr=0.5):  # noqa: ANN001
    v = f["price_z"][i]
    return v is not None and v > thr


def _xp_news(f, i):  # noqa: ANN001
    z = f.get("news_z")
    v = z[i] if z else None
    return v is None or v > 0.0


def _xp_fund(f, i):  # noqa: ANN001
    z = f.get("funding_z")
    v = z[i] if z else None
    return v is None or v < 1.0  # crypto-only; absent for equity → pass-through


def _xp_fg(f, i):  # noqa: ANN001
    z = f.get("fg")
    v = z[i] if z else None
    return v is None or v < 65.0


def _xp_riskon(f, i):  # noqa: ANN001
    v = f["risk_on"][i]
    return v is None or v > 0.5  # prediction-market risk-on tag (cross-asset transfer)


def _xp_macro(f, i):  # noqa: ANN001
    v = f["macro"][i]
    return v is None or v > 0.0  # FRED macro regime (cross-asset transfer)


def _xp_xmarket(f, i, drop=None):  # noqa: ANN001
    """Cross-market transfer backdrop: the equal-weight, sign-neutral mean of the multiasset price-level
    z-scores at bar i (metals/commodities/equity indexes/FX, read market-wide). It's STATIONARY by
    construction — each input is a causal rolling z-score, never a raw level, so no absolute threshold can
    overfit the sample (the PR #87 cross-market failure). Trades when the composite is non-negative
    (cross-market risk backdrop not deteriorating); pass-through when no data lands on the bar. `drop`
    excludes ONE metric from the composite so the per-source drop-one report can attribute each market's
    marginal contribution without removing the whole transfer term."""
    xm = f.get("xmarket")
    if not xm:
        return True
    zs = [s[i] for m, s in xm.items() if m != drop and i < len(s) and s[i] is not None]
    if not zs:
        return True
    return (sum(zs) / len(zs)) >= 0.0


def _xa_single_alt(thr):  # noqa: ANN001
    return lambda f, i: _xp_price(f, i, thr) and _xp_news(f, i) and _xp_fund(f, i) and _xp_fg(f, i)


def _xa_full(thr, *, drop=None):  # noqa: ANN001
    """The cross-asset arm: single-asset alt + the transfer features. `drop` excludes one source term so the
    drop-one report can attribute each source's marginal contribution (a diagnostic, not a counted trial)."""
    def pred(f, i):  # noqa: ANN001
        ok = _xp_price(f, i, thr)
        if drop != "news":
            ok = ok and _xp_news(f, i)
        if drop != "funding":
            ok = ok and _xp_fund(f, i)
        if drop != "fear_greed":
            ok = ok and _xp_fg(f, i)
        if drop != "risk_on":
            ok = ok and _xp_riskon(f, i)
        if drop != "macro_regime":
            ok = ok and _xp_macro(f, i)
        # Cross-market transfer term is always present; a multiasset `drop` only thins the composite
        # (a no-op for the non-multiasset source drops, whose keys never match a metric name).
        ok = ok and _xp_xmarket(f, i, drop=drop)
        return ok
    return pred


def _xa_features(market, class_of, alt_provider, news_provider, lookback):  # noqa: ANN001
    cache: dict = {}
    counter: dict = {}
    big = 10**9
    # Query the CANONICAL stored metric name. Ingest banks the prediction-market risk transfer series under
    # "pm_risk_on" (cosmu/ingest/run.py); requesting the old "risk_on" relied on a store-side request alias and
    # returned [] for any provider without it (the P0 integrity bug: the live cross-asset feature was silently
    # empty). The feature key f["risk_on"], the _xp_riskon predicate, and the drop-one label stay "risk_on" —
    # only the store-query name is the canonical one.
    risk_on_pts = alt_provider.fetch_series("MARKET", "pm_risk_on", limit=big)
    macro_pts = alt_provider.fetch_series("MARKET", "macro_regime", limit=big)
    # Cross-market transfer sources: free, market-wide daily price LEVELS (metals/commodities/equity
    # indexes/FX) read once here, then turned STATIONARY per symbol via the causal rolling z-score below.
    xmarket_pts = {m: alt_provider.fetch_series("MARKET", m, limit=big) for m in MULTIASSET_METRICS}
    feats: dict = {}
    for symbol, bars in market.items():
        klass = class_of[symbol]
        closes = [float(b.close) for b in bars]
        f: dict = {"_class": klass, "price_z": rolling_zscore(closes, lookback)}
        if news_provider is None:
            # Real/store path: news was LLM-standardized ONCE at ingest → read the numeric series. Zero LLM here.
            news_aligned = _align(bars, [(p.available_at, p.value) for p in alt_provider.fetch_series(symbol, "news_sentiment", limit=len(bars) + 10)])
        else:
            # Fixture path: raw headlines standardized via the deterministic offline lexicon (no LLM, cached).
            news_pts = standardize_news(news_provider.fetch_news(symbol, limit=len(bars) + 10), cache=cache, counter=counter)
            news_aligned = _align(bars, [(p.available_at, p.value) for p in news_pts])
        f["news_z"] = rolling_zscore(news_aligned, lookback)
        if klass == "crypto":
            fund = _align(bars, [(p.available_at, p.value) for p in alt_provider.fetch_series(symbol, "funding_rate", limit=len(bars) + 10)])
            f["funding_z"] = rolling_zscore(fund, lookback)
            f["fg"] = _align(bars, [(p.available_at, p.value) for p in alt_provider.fetch_series(symbol, "fear_greed", limit=len(bars) + 10)])
        f["risk_on"] = _align(bars, [(p.available_at, p.value) for p in risk_on_pts])
        f["macro"] = _align(bars, [(p.available_at, p.value) for p in macro_pts])
        # Each multiasset level series → a causal rolling z-score aligned to THIS symbol's bars (stationary,
        # no look-ahead). Absent series align to all-None → the z-score is all-None → pass-through.
        f["xmarket"] = {
            m: rolling_zscore(_align(bars, [(p.available_at, p.value) for p in pts]), lookback)
            for m, pts in xmarket_pts.items()
        }
        feats[symbol] = (bars, f)
    return feats


def _xa_sharpe(signal_market, store=None) -> tuple[float, float]:  # noqa: ANN001
    """Annualized Sharpe + validation return for a signal — the cheap diagnostic used for drop-one
    attribution. It does NOT record a trial or call the scorer (it isn't a competing hypothesis)."""
    val_returns: list[float] = []
    val_total: list[float] = []
    for symbol, (bars, signal) in signal_market.items():
        if len(bars) < 80:
            continue
        split = max(40, int(len(bars) * 0.8))
        v_eq, _ = _simulate(bars[:split], signal[:split], _ARM, store=store, symbol=symbol)
        val_returns.extend(_bar_returns(v_eq))
        if v_eq:
            val_total.append(v_eq[-1] / 100000.0 - 1.0)
    sr, *_ = sample_moments(val_returns)
    return sr * math.sqrt(365), (statistics.fmean(val_total) if val_total else 0.0)


def _xa_buy_and_hold(market: dict[str, list[Bar]], *, store: Store | None = None, venue_id: str = "binance") -> float:
    """Equal-weight buy-and-hold across the FULL cross-asset universe (not just BTC/ETH) — the honest
    multi-asset baseline arm (4)."""
    rets = []
    for symbol, bars in market.items():
        if len(bars) < 80:
            continue
        split = max(40, int(len(bars) * 0.8))
        first, last = float(bars[0].close), float(bars[split - 1].close)
        if first:
            entry_fee = _pit_fee(store, venue_id, symbol, bars[0].ts) if store is not None else _FEE_FALLBACK_BPS / 10000.0
            exit_fee = _pit_fee(store, venue_id, symbol, bars[split - 1].ts) if store is not None else _FEE_FALLBACK_BPS / 10000.0
            rets.append(last / first - 1.0 - entry_fee - exit_fee)
    return statistics.fmean(rets) if rets else 0.0


def evaluate_cross_asset_ablation(
    market_by_class: dict[str, dict[str, list[Bar]]],
    alt_provider: AltDataProvider,
    news_provider: NewsProvider | None,
    store: Store,
    *,
    lookback: int = 20,
) -> CrossAssetVerdict:
    """Four arms on the SAME windows/costs/wall: (1) single-asset price-only · (2) single-asset+alt ·
    (3) cross-asset+alt (new) · (4) buy-and-hold — plus per-source AND per-asset-class drop-one. Pre-registered
    pass: arm (3) net return > arm (1) AND > arm (2) AND > buy-and-hold, all net of the same costs, and it
    clears the statistical bar. Verdict PASS (multi-asset thesis real) / STOP-narrow (keep single-asset, cut
    the classes that didn't pay). Every counted attempt hits the global trial ledger."""
    market: dict[str, list[Bar]] = {}
    class_of: dict[str, str] = {}
    for klass, symbols in market_by_class.items():
        for symbol, bars in symbols.items():
            market[symbol] = bars
            class_of[symbol] = klass

    feats = _xa_features(market, class_of, alt_provider, news_provider, lookback)

    # --- the three counted arms (each registers a trial + is scored against the trial-inflated benchmark) ---
    price = _arm_metrics(_build_signal(feats, lambda f, i: _xp_price(f, i, 0.5)), store, "xa_price_only")
    single = _arm_metrics(_build_signal(feats, _xa_single_alt(0.5)), store, "xa_single_alt")
    xasset = _arm_metrics(_build_signal(feats, _xa_full(0.5)), store, "xa_cross_asset")

    # --- CSCV overfit guard over a diverse cross-asset config grid (also counted trials) ---
    variant_returns: list[list[float]] = []
    for lb in (14, 20, 30):
        feats_lb = feats if lb == lookback else _xa_features(market, class_of, alt_provider, news_provider, lb)
        for thr in (0.3, 0.8):
            variant_returns.append(_arm_metrics(_build_signal(feats_lb, _xa_full(thr)), store, f"xa_lb{lb}_z{thr}").val_returns)
    usable = [r for r in variant_returns if r]
    pbo = cscv_pbo(usable) if len(usable) >= 2 else 1.0

    xasset_sharpe = float(xasset.metrics.sharpe)
    # --- per-source drop-one (diagnostic — NOT a counted trial; attribution on the arm-(3) hypothesis) ---
    drop_one_source: list[DropOne] = []
    # The single-asset alt sources + the two original transfer features + each stationary cross-market
    # source (a multiasset drop thins the composite, attributing that one market's marginal contribution).
    for src in ("news", "funding", "fear_greed", "risk_on", "macro_regime", *MULTIASSET_METRICS):
        without = _xa_sharpe(_build_signal(feats, _xa_full(0.5, drop=src)), store)[0]
        drop_one_source.append(DropOne(src, round(without, 4), round(xasset_sharpe - without, 4)))
    drop_one_source.sort(key=lambda d: d.delta, reverse=True)
    # --- per-asset-class drop-one (diagnostic): drop a whole class from the traded universe ---
    drop_one_class: list[ClassDrop] = []
    for klass in market_by_class:
        sub = {s: bf for s, bf in feats.items() if bf[1]["_class"] != klass}
        without = _xa_sharpe(_build_signal(sub, _xa_full(0.5)), store)[0] if sub else 0.0
        drop_one_class.append(ClassDrop(klass, round(without, 4), round(xasset_sharpe - without, 4)))
    drop_one_class.sort(key=lambda d: d.delta, reverse=True)

    buy_hold = _xa_buy_and_hold(market, store=store)
    xasset_dsr = float(xasset.verdict.deflated_sharpe_prob)
    regimes_positive = sum(1 for v in xasset.metrics.regime_returns.values() if v > 0)

    reasons: list[str] = []
    if xasset.val_return <= price.val_return:
        reasons.append("not_beating_single_asset_price_only")
    if xasset.val_return <= single.val_return:
        reasons.append("not_beating_single_asset_alt")
    if xasset.val_return <= buy_hold:
        reasons.append("not_beating_buy_and_hold")
    if xasset.metrics.num_trades < CROSS_ASSET_BAR["min_trades"]:
        reasons.append("min_trades")
    if xasset_dsr < CROSS_ASSET_BAR["min_deflated_sharpe_prob"]:
        reasons.append("deflated_sharpe")
    if pbo >= CROSS_ASSET_BAR["max_cscv_pbo"]:
        reasons.append("cscv_pbo")
    if regimes_positive < CROSS_ASSET_BAR["min_regimes_positive"]:
        reasons.append("regimes")
    if float(xasset.metrics.max_drawdown) >= CROSS_ASSET_BAR["max_drawdown"]:
        reasons.append("max_drawdown")

    passed = not reasons
    # Experiment-tracking hook: each counted cross-asset arm logged with its forward-P&L soft-label. `market`
    # here is the flattened single-/cross-asset universe the arms actually traded.
    _log_gate_experiments(
        store, kind="cross_asset", source="cross_asset", market=market,
        items=[
            (arm.name, {"arm": arm.name, "lookback": lookback}, arm.metrics, arm.val_return,
             passed if arm is xasset else None)
            for arm in (price, single, xasset)
        ],
    )
    return CrossAssetVerdict(
        decision="PASS" if passed else "STOP-narrow",
        passed=passed,
        price_only_return=round(price.val_return, 6),
        single_alt_return=round(single.val_return, 6),
        xasset_return=round(xasset.val_return, 6),
        buy_and_hold_return=round(buy_hold, 6),
        xasset_dsr=round(xasset_dsr, 6),
        single_alt_dsr=round(float(single.verdict.deflated_sharpe_prob), 6),
        cscv_pbo=round(pbo, 6),
        regimes_positive=regimes_positive,
        num_trades=xasset.metrics.num_trades,
        max_drawdown=round(float(xasset.metrics.max_drawdown), 6),
        attempts=3 + len(variant_returns),  # 3 arms + CSCV grid; drop-one is diagnostic, not a trial
        drop_one_source=drop_one_source,
        drop_one_class=drop_one_class,
        reasons=reasons,
    )


def _main() -> int:
    """Offline four-arm cross-asset ablation on synthetic fixtures. Real runs inject live bars + free providers."""
    import tempfile

    from cosmu.config.settings import Settings
    from cosmu.research.fixtures import synthetic_cross_asset_inputs

    tmp = tempfile.mkdtemp(prefix="cosmu-gate-")
    store = Store(Settings(database_url=f"sqlite:///{tmp}/gate_demo.sqlite3"))
    market_by_class, alt_provider, news_provider = synthetic_cross_asset_inputs()
    xa = evaluate_cross_asset_ablation(market_by_class, alt_provider, news_provider, store)

    print("CROSS-ASSET GATE —", xa.decision)
    print(f"  cross-asset+alt arm:   return {xa.xasset_return:+.3f} · deflated Sharpe {xa.xasset_dsr}")
    print(f"  single-asset+alt arm:  return {xa.single_alt_return:+.3f} · deflated Sharpe {xa.single_alt_dsr}")
    print(f"  single-asset price arm:return {xa.price_only_return:+.3f}")
    print(f"  buy & hold (all):      return {xa.buy_and_hold_return:+.3f}")
    print(f"  CSCV PBO {xa.cscv_pbo} (< {CROSS_ASSET_BAR['max_cscv_pbo']}) · regimes {xa.regimes_positive} · trades {xa.num_trades} · maxDD {xa.max_drawdown} · attempts {xa.attempts}")
    print("  which DATA paid (drop-one Δ Sharpe):")
    for d in xa.drop_one_source:
        print(f"    {d.source:<13} Δ {d.delta:+.3f}")
    print("  which ASSET CLASS paid (drop-one Δ Sharpe):")
    for c in xa.drop_one_class:
        print(f"    {c.asset_class:<13} Δ {c.delta:+.3f}")
    if xa.reasons:
        print(f"  failed checks:  {', '.join(xa.reasons)}")
    print(
        "\n"
        + (
            "PASS — combining asset classes beats any single one. Proceed to Phase 2 with all classes."
            if xa.passed
            else "STOP-narrow — cross-asset did not beat single-asset. Keep single-asset; cut the classes with non-positive drop-one Δ."
        )
    )
    return 0 if xa.passed else 1


if __name__ == "__main__":
    raise SystemExit(_main())
