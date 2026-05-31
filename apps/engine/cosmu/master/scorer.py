# intent: score strategy evidence deterministically; inputs: backtest metrics and configured gates; outputs: ScoreVerdict; invariants: the agent cannot alter ranking metrics or promotion gates.

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel

from cosmu.config.settings import GateSettings


class BacktestMetrics(BaseModel):
    oos_return: Decimal
    sharpe: Decimal
    sortino: Decimal
    max_drawdown: Decimal
    win_rate: Decimal
    num_trades: int
    pbo: Decimal
    trials_counted: int
    folds_positive_pct: Decimal
    holdout_deflated_sharpe: Decimal


class ScoreVerdict(BaseModel):
    ranking_scalar: Decimal
    passed: bool
    reasons: list[str]


def deflate_sharpe(sharpe: Decimal, trials_counted: int, pbo: Decimal) -> Decimal:
    penalty = Decimal(max(trials_counted - 1, 0)).sqrt() * Decimal("0.03")
    return sharpe - penalty - (pbo * Decimal("0.40"))


def score(metrics: BacktestMetrics, gates: GateSettings) -> ScoreVerdict:
    dsharpe = deflate_sharpe(metrics.sharpe, metrics.trials_counted, metrics.pbo)
    reasons: list[str] = []
    if metrics.num_trades < gates.min_trades:
        reasons.append("min_trades")
    if metrics.max_drawdown > gates.max_drawdown_pct:
        reasons.append("max_drawdown")
    if metrics.folds_positive_pct < gates.min_folds_positive_pct:
        reasons.append("folds_positive")
    if metrics.pbo > gates.max_pbo:
        reasons.append("pbo")
    if metrics.holdout_deflated_sharpe <= gates.holdout_min_deflated_sharpe:
        reasons.append("holdout")
    return ScoreVerdict(ranking_scalar=dsharpe, passed=not reasons, reasons=reasons)

