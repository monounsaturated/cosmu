# intent: the edge-existence gate — run a small, attempt-capped set of hand-built social-momentum signals through the deterministic wall and a pre-registered pass bar, to answer "does an exploitable edge exist on Binance spot after costs?" before any factory is built; inputs: bars + alt-data + store; outputs: a PASS/STOP GateVerdict; invariants: signals computed directly (no indicator-lib path), every attempt counted in the global trial ledger, the pass bar is pre-registered and the gate cannot be silently p-hacked.

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from cosmu.data.altdata import AltDataProvider, rolling_zscore
from cosmu.data.market import Bar
from cosmu.knowledge.store import Store
from cosmu.master.scorer import (
    BacktestMetrics,
    ScoreVerdict,
    TrialStats,
    cscv_pbo,
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


def _main() -> int:
    """Offline demonstration run on synthetic data. Real runs inject live bars + LunarCrush."""
    import tempfile

    from cosmu.config.settings import Settings
    from cosmu.research.fixtures import synthetic_gate_inputs

    # Fresh store per demo run so the global trial ledger starts empty and the run is reproducible.
    tmp = tempfile.mkdtemp(prefix="cosmu-gate-")
    store = Store(Settings(database_url=f"sqlite:///{tmp}/gate_demo.sqlite3"))
    market, provider = synthetic_gate_inputs()
    verdict = evaluate_gate(market, provider, store)
    print("EDGE GATE —", verdict.decision)
    print(f"  best signal:        {verdict.best_signal}")
    print(f"  deflated Sharpe P:  {verdict.deflated_sharpe_prob}  (bar ≥ {PREREGISTERED_BAR['min_deflated_sharpe_prob']})")
    print(f"  CSCV PBO:           {verdict.cscv_pbo}  (bar < {PREREGISTERED_BAR['max_cscv_pbo']})")
    print(f"  return vs buy&hold: {verdict.best_return} vs {verdict.buy_and_hold_return}")
    print(f"  regimes positive:   {verdict.regimes_positive}  (bar ≥ {PREREGISTERED_BAR['min_regimes_positive']})")
    print(f"  trades / maxDD:     {verdict.num_trades} / {verdict.max_drawdown}")
    print(f"  attempts:           {verdict.attempts} (budget {PREREGISTERED_BAR['attempt_budget']})")
    if verdict.reasons:
        print(f"  failed checks:      {', '.join(verdict.reasons)}")
    print("\n" + ("PASS — an edge cleared the wall; proceed to Phase 2." if verdict.passed else "STOP — no edge cleared the wall. That is a real result; do not build the factory."))
    return 0 if verdict.passed else 1


if __name__ == "__main__":
    raise SystemExit(_main())
