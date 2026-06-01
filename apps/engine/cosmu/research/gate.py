# intent: the edge-existence gate — run a small, attempt-capped set of hand-built social-momentum signals through the deterministic wall and a pre-registered pass bar, to answer "does an exploitable edge exist on Binance spot after costs?" before any factory is built; inputs: bars + alt-data + store; outputs: a PASS/STOP GateVerdict; invariants: signals computed directly (no indicator-lib path), every attempt counted in the global trial ledger, the pass bar is pre-registered and the gate cannot be silently p-hacked.

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from cosmu.data.altdata import AltDataProvider, NewsProvider, rolling_zscore
from cosmu.data.market import Bar
from cosmu.ingest.standardize import standardize_news
from cosmu.knowledge.store import Store
from cosmu.master.scorer import (
    BacktestMetrics,
    ScoreVerdict,
    TrialStats,
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
_FEE = 0.001  # Binance spot taker
_SLIP = 0.0005
_STOP = 0.08
_TAKE = 0.16


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
        metrics, val_return, val_returns = _run_variant(aligned, params)
        record_trial(store, float(metrics.sharpe_per_obs), source="edge_gate", label=params.name)
        verdict = score(metrics, _gate_gates(store), trials=trial_stats(store))
        results.append(VariantResult(params, metrics, verdict, val_return, val_returns))

    pbo = cscv_pbo([r.val_returns for r in results if r.val_returns]) if results else 1.0
    buy_hold = _buy_and_hold(market)
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


def _run_variant(aligned: dict[str, tuple[list[Bar], list[float | None]]], params: SignalParams) -> tuple[BacktestMetrics, float, list[float]]:
    val_returns: list[float] = []
    val_total: list[float] = []
    regime_pnl: dict[str, float] = {}
    trades_all = 0
    wins = 0
    max_dd = 0.0
    fold_returns: list[float] = []
    h_returns: list[float] = []

    for bars, alt in aligned.values():
        if len(bars) < 80:
            continue
        split = max(40, int(len(bars) * 0.8))
        z = rolling_zscore(alt, params.lookback)
        signal = [v is not None and v > params.z_threshold for v in z]
        v_eq, v_trades = _simulate(bars[:split], signal[:split], params)
        h_eq, _ = _simulate(bars[split:], signal[split:], params)
        val_returns.extend(_bar_returns(v_eq))
        h_returns.extend(_bar_returns(h_eq))
        if v_eq:
            val_total.append(v_eq[-1] / 100000.0 - 1.0)
            max_dd = max(max_dd, _max_dd(v_eq))
            fold_returns.extend(_folds(v_eq))
        for pnl, regime in v_trades:
            regime_pnl[regime] = regime_pnl.get(regime, 0.0) + pnl
            trades_all += 1
            wins += 1 if pnl > 0 else 0

    sr, skew, kurt, n = sample_moments(val_returns)
    from cosmu.master.scorer import probabilistic_sharpe

    h_sr, h_skew, h_kurt, h_n = sample_moments(h_returns)
    holdout_dsr = probabilistic_sharpe(h_sr, h_n, h_skew, h_kurt, 0.0) - 0.5
    folds_pos = sum(1 for x in fold_returns if x > 0)
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
    )
    val_return = statistics.fmean(val_total) if val_total else 0.0
    return metrics, val_return, val_returns


def _simulate(bars: list[Bar], signal: list[bool], params: SignalParams) -> tuple[list[float], list[tuple[float, str]]]:
    from cosmu.data.backtest import _regime_labels

    closes = [float(b.close) for b in bars]
    regimes = _regime_labels(closes)
    cash = 100000.0
    pos = 0.0
    entry = 0.0
    entry_idx = 0
    equity: list[float] = []
    trades: list[tuple[float, str]] = []
    for i in range(1, len(bars)):
        b = bars[i]
        if pos > 0:
            stop_p = entry * (1 - _STOP)
            take_p = entry * (1 + _TAKE)
            xp: float | None = None
            if float(b.low) <= stop_p:
                xp = stop_p * (1 - _SLIP)
            elif float(b.high) >= take_p:
                xp = take_p * (1 - _SLIP)
            elif i - entry_idx >= params.hold_bars:
                xp = float(b.open) * (1 - _SLIP)
            if xp is not None:
                cash += pos * xp * (1 - _FEE)
                pnl = (xp * (1 - _FEE) - entry * (1 + _FEE)) / entry
                trades.append((pnl, regimes[entry_idx]))
                pos = 0.0
                entry = 0.0
        if pos == 0 and i - 1 < len(signal) and signal[i - 1]:
            notional = cash * 0.2
            fill = float(b.open) * (1 + _SLIP)
            pos = notional * (1 - _FEE) / fill
            cash -= notional
            entry = fill
            entry_idx = i
        equity.append(cash + pos * closes[i])
    if pos > 0:
        xp = closes[-1] * (1 - _SLIP)
        cash += pos * xp * (1 - _FEE)
        pnl = (xp * (1 - _FEE) - entry * (1 + _FEE)) / entry
        trades.append((pnl, regimes[entry_idx]))
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


def _buy_and_hold(market: dict[str, list[Bar]]) -> float:
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
            rets.append(last / first - 1.0 - 2 * _FEE)
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
    for bars, signal in signal_market.values():
        if len(bars) < 80:
            continue
        split = max(40, int(len(bars) * 0.8))
        v_eq, v_tr = _simulate(bars[:split], signal[:split], _ARM)
        h_eq, _ = _simulate(bars[split:], signal[split:], _ARM)
        val_returns.extend(_bar_returns(v_eq))
        h_returns.extend(_bar_returns(h_eq))
        if v_eq:
            val_total.append(v_eq[-1] / 100000.0 - 1.0)
            max_dd = max(max_dd, _max_dd(v_eq))
            fold_returns.extend(_folds(v_eq))
        for pnl, regime in v_tr:
            regime_pnl[regime] = regime_pnl.get(regime, 0.0) + pnl
            trades += 1
            wins += 1 if pnl > 0 else 0

    sr, skew, kurt, n = sample_moments(val_returns)
    h_sr, h_skew, h_kurt, h_n = sample_moments(h_returns)
    holdout = probabilistic_sharpe(h_sr, h_n, h_skew, h_kurt, 0.0) - 0.5
    folds_pos = sum(1 for x in fold_returns if x > 0)
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

    buy_hold = _buy_and_hold(market)
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


def _main() -> int:
    """Offline three-arm ablation on synthetic fixtures. Real runs inject live bars + free providers."""
    import tempfile

    from cosmu.config.settings import Settings
    from cosmu.research.fixtures import synthetic_ablation_inputs

    tmp = tempfile.mkdtemp(prefix="cosmu-gate-")
    store = Store(Settings(database_url=f"sqlite:///{tmp}/gate_demo.sqlite3"))
    market, alt_provider, news_provider = synthetic_ablation_inputs()
    v = evaluate_ablation(market, alt_provider, news_provider, store)

    print("AGGREGATION GATE —", v.decision)
    print(f"  alt-data arm:   return {v.alt_return:+.3f} · deflated Sharpe {v.alt_dsr}")
    print(f"  price-only arm: return {v.price_only_return:+.3f} · deflated Sharpe {v.price_only_dsr}")
    print(f"  buy & hold:     return {v.buy_and_hold_return:+.3f}")
    print(f"  CSCV PBO {v.cscv_pbo} (< {ABLATION_BAR['max_cscv_pbo']}) · regimes {v.regimes_positive} (≥ {ABLATION_BAR['min_regimes_positive']}) · trades {v.num_trades} · maxDD {v.max_drawdown}")
    print("  which data paid (drop-one Δ deflated Sharpe):")
    for d in v.drop_one:
        print(f"    {d.source:<11} Δ {d.delta:+.3f}")
    if v.reasons:
        print(f"  failed checks:  {', '.join(v.reasons)}")
    print(
        "\n"
        + (
            "PASS — aggregating + standardizing data beats price-only and buy-and-hold. Proceed to Phase 2."
            if v.passed
            else "STOP — aggregation did not beat price alone. Keep only the sources with positive drop-one Δ."
        )
    )
    return 0 if v.passed else 1


if __name__ == "__main__":
    raise SystemExit(_main())
