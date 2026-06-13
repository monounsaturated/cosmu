# intent: score strategy evidence deterministically; inputs: backtest metrics, configured gates, and cumulative trial statistics; outputs: ScoreVerdict; invariants: the agent cannot alter ranking metrics or promotion gates, and significance is deflated for non-normality and the number of trials ever run.

from __future__ import annotations

import math
from decimal import Decimal
from itertools import combinations
from statistics import NormalDist, fmean, pstdev

from pydantic import BaseModel, Field

from cosmu.config.settings import GateSettings

# Euler–Mascheroni constant, used in the expected-maximum-Sharpe (DSR) estimator.
_EULER_GAMMA = 0.5772156649015329
_NORMAL = NormalDist()


class BacktestMetrics(BaseModel):
    oos_return: Decimal
    # Validation-slice buy-and-hold NET return (fees in) over the SAME bars[:split] window as `oos_return`, so the
    # two are directly comparable. The promotion gate requires a strategy to BEAT just holding the basket (a
    # bull-regime momentum can clear DSR/PBO/holdout/FDR yet still underperform BTC). Computed in data/backtest.py;
    # 0 by default so a directly-constructed metrics row (or one with no market) imposes no buy-and-hold hurdle.
    buy_and_hold_return: Decimal = Decimal("0")
    sharpe: Decimal  # annualized — for display/ranking only
    sortino: Decimal
    max_drawdown: Decimal
    win_rate: Decimal
    num_trades: int
    # Inputs to the Probabilistic / Deflated Sharpe (per-observation, NOT annualized):
    sharpe_per_obs: Decimal = Decimal("0")
    skew: Decimal = Decimal("0")
    kurtosis: Decimal = Decimal("3")  # full kurtosis; normal == 3
    n_obs: int = 0
    pbo: Decimal = Decimal("0")  # single-strategy overfit proxy; true PBO is CSCV across configs
    trials_counted: int = 1
    folds_positive_pct: Decimal = Decimal("0")
    holdout_deflated_sharpe: Decimal = Decimal("0")
    regime_returns: dict[str, float] = Field(default_factory=dict)
    # profit_factor = gross wins / gross losses across trades. DISPLAYED secondary metric ONLY — the ranking
    # metric stays the deflated Sharpe. It never enters score()'s pass/fail or ranking_scalar.
    profit_factor: Decimal = Decimal("0")
    # cost_ratio = net_edge / gross_edge in [0, 1]: the fraction of gross alpha surviving after fees +
    # slippage.  1.0 = costs are zero (hypothetical); 0.0 = all edge is eaten.  Healthy edges keep this
    # well above 0.5; edges within a slippage-doubling of breakeven (cost_ratio ≈ 0) are fragile.
    # DISPLAYED and used for routing/fragility flagging — never enters the gate's pass/fail thresholds.
    cost_ratio: Decimal = Decimal("0")

    @property
    def recovery_factor(self) -> float:
        """Total net (in-sample) return per unit of max drawdown — a drawdown-aware quality number the Sharpe
        is blind to. DISPLAYED only (never a gate threshold). inf when there was no drawdown and it's up."""
        from cosmu.master.risk_metrics import recovery_factor

        return recovery_factor(float(self.oos_return), float(self.max_drawdown))


class TrialStats(BaseModel):
    """Cumulative multiple-testing context across every hypothesis ever run."""

    count: int = 1
    sr_variance: float | None = None  # cross-sectional variance of per-obs trial Sharpes; analytic if None
    # Average pairwise correlation (rho_bar) of the trial population's return streams. A correlated grid of
    # near-duplicate variants is NOT `count` independent tests, so the multiple-testing penalty is applied to
    # the EFFECTIVE count N/(1+(N-1)*rho_bar), not the raw count (see `effective_trials`). None = unknown ⇒
    # no haircut ⇒ the pre-registered gate (which never supplies one) is byte-identical to before.
    sr_correlation: float | None = None


class ScoreVerdict(BaseModel):
    ranking_scalar: Decimal  # deflated Sharpe probability in [0,1] — what we rank by
    deflated_sharpe_prob: Decimal
    passed: bool
    reasons: list[str]


def probabilistic_sharpe(sr_hat: float, n_obs: int, skew: float, kurtosis: float, sr_benchmark: float) -> float:
    """PSR (Bailey & López de Prado): P(true per-obs Sharpe > benchmark), adjusted for skew/kurtosis."""
    if n_obs < 2:
        return 0.0
    variance_term = 1.0 - skew * sr_hat + ((kurtosis - 1.0) / 4.0) * sr_hat * sr_hat
    if variance_term <= 0:
        return 0.0
    z = (sr_hat - sr_benchmark) * math.sqrt(n_obs - 1) / math.sqrt(variance_term)
    return _NORMAL.cdf(z)


def expected_max_sharpe(sr_variance: float, n_trials: float) -> float:
    """SR0: expected maximum of n_trials i.i.d. per-obs Sharpes drawn from N(0, sr_variance).

    `n_trials` may be FRACTIONAL — the effective independent-trial count after a correlation haircut
    (`effective_trials`). Floored at 0 so a sub-2 effective count can never produce a NEGATIVE benchmark
    (which would perversely make the Deflated Sharpe EASIER to clear). For integer n_trials >= 2 this is
    byte-identical to the prior implementation, so the pre-registered gate is unchanged.
    """
    if n_trials <= 1.0 or sr_variance <= 0:
        return 0.0
    sigma = math.sqrt(sr_variance)
    a = _NORMAL.inv_cdf(1.0 - 1.0 / n_trials)
    b = _NORMAL.inv_cdf(1.0 - 1.0 / (n_trials * math.e))
    return max(0.0, sigma * ((1.0 - _EULER_GAMMA) * a + _EULER_GAMMA * b))


def effective_trials(n_trials: float, sr_correlation: float | None) -> float:
    """Effective number of INDEPENDENT trials given the average pairwise correlation `rho_bar` of the trial
    population: N_eff = N / (1 + (N - 1) * rho_bar). At rho_bar = 0 (independent) this is N; as rho_bar → 1
    (a grid of near-duplicates) it collapses toward 1/rho_bar — so densifying a CORRELATED grid stops
    inflating the trial count, and SR0 no longer collapses (the leak). `None` ⇒ no measured correlation ⇒
    a no-op returning N, so the honest reference gate is untouched."""
    if sr_correlation is None:
        return n_trials
    rho = min(1.0, max(0.0, sr_correlation))
    if n_trials <= 1.0 or rho <= 0.0:
        return n_trials
    return n_trials / (1.0 + (n_trials - 1.0) * rho)


def _trial_sr_variance(trials: TrialStats, sr_hat: float, n_obs: int) -> float:
    """Observed cross-sectional variance of trial Sharpes if known; else the analytic
    sampling variance of a Sharpe estimate under the null (Lo, 2002)."""
    if trials.sr_variance is not None:
        return max(trials.sr_variance, 0.0)
    if n_obs < 2:
        return 0.0
    return (1.0 + 0.5 * sr_hat * sr_hat) / (n_obs - 1)


def deflated_sharpe_prob(metrics: BacktestMetrics, trials: TrialStats) -> float:
    """DSR = PSR evaluated against the trial-count-inflated benchmark SR0, where the trial count is the
    EFFECTIVE number of independent trials (a correlation haircut on the raw count — see `effective_trials`)."""
    sr_hat = float(metrics.sharpe_per_obs)
    sr_variance = _trial_sr_variance(trials, sr_hat, metrics.n_obs)
    n_trials = max(trials.count, metrics.trials_counted, 1)
    n_eff = effective_trials(float(n_trials), trials.sr_correlation)
    sr0 = expected_max_sharpe(sr_variance, n_eff)
    return probabilistic_sharpe(sr_hat, metrics.n_obs, float(metrics.skew), float(metrics.kurtosis), sr0)


def cscv_pbo(config_block_returns: list[list[float]], s_blocks: int = 8) -> float:
    """Probability of Backtest Overfitting via Combinatorially-Symmetric Cross-Validation.

    `config_block_returns[i]` is config i's per-bar return series (all equal length). We split the
    timeline into S blocks, take every balanced split into in-sample / out-of-sample halves, pick the
    IS-best config, and measure how often it lands below the OOS median (logit ≤ 0). PBO is that rate.
    Needs ≥2 configs; returns 1.0 (maximally overfit) if it cannot be computed.
    """
    n_configs = len(config_block_returns)
    if n_configs < 2:
        return 1.0
    length = min(len(series) for series in config_block_returns)
    s = max(2, min(s_blocks, length))
    if s % 2:
        s -= 1
    if s < 2:
        return 1.0
    block_size = length // s
    if block_size < 1:
        return 1.0

    # Per-config mean return within each of the S blocks.
    block_means: list[list[float]] = []
    for series in config_block_returns:
        means = [fmean(series[b * block_size : (b + 1) * block_size]) for b in range(s)]
        block_means.append(means)

    block_ids = list(range(s))
    overfit = 0
    total = 0
    for is_blocks in combinations(block_ids, s // 2):
        is_set = set(is_blocks)
        oos_blocks = [b for b in block_ids if b not in is_set]
        is_perf = [fmean([block_means[c][b] for b in is_blocks]) for c in range(n_configs)]
        oos_perf = [fmean([block_means[c][b] for b in oos_blocks]) for c in range(n_configs)]
        best = max(range(n_configs), key=lambda c: is_perf[c])
        # OOS rank of the IS-best config: 1 (worst) .. n_configs (best).
        rank = 1 + sum(1 for c in range(n_configs) if oos_perf[c] < oos_perf[best])
        omega = rank / (n_configs + 1)
        logit = math.log(omega / (1.0 - omega)) if 0.0 < omega < 1.0 else (-math.inf if omega <= 0 else math.inf)
        if logit <= 0.0:
            overfit += 1
        total += 1
    return overfit / total if total else 1.0


def sample_moments(returns: list[float]) -> tuple[float, float, float, int]:
    """Per-observation Sharpe, skew, full kurtosis (normal=3), and n — for PSR/DSR."""
    n = len(returns)
    if n < 2:
        return 0.0, 0.0, 3.0, n
    mean = fmean(returns)
    sd = pstdev(returns)
    if sd == 0:
        return 0.0, 0.0, 3.0, n
    sr = mean / sd
    skew = fmean([((x - mean) / sd) ** 3 for x in returns])
    kurt = fmean([((x - mean) / sd) ** 4 for x in returns])
    return sr, skew, kurt, n


def score(metrics: BacktestMetrics, gates: GateSettings, *, trials: TrialStats | None = None, check_holdout: bool = True) -> ScoreVerdict:
    """`check_holdout=False` is the SCREENING-lane mode: variant selection must see only validation evidence —
    the untouched holdout is a one-shot CONFIRMATION the caller applies to its selected champion afterwards
    (the finder's champion-only holdout step). Leaving it True (the default, every other caller) keeps the
    holdout floor inside the verdict, which is correct only when the scored metrics ARE a champion's."""
    trials = trials or TrialStats(count=max(metrics.trials_counted, 1))
    dsr = deflated_sharpe_prob(metrics, trials)
    reasons: list[str] = []
    if metrics.num_trades < gates.min_trades:
        reasons.append("min_trades")
    if metrics.max_drawdown > gates.max_drawdown_pct:
        reasons.append("max_drawdown")
    if metrics.folds_positive_pct < gates.min_folds_positive_pct:
        reasons.append("folds_positive")
    if metrics.pbo > gates.max_pbo:
        reasons.append("pbo")
    if Decimal(str(dsr)) < gates.min_deflated_sharpe_prob:
        reasons.append("deflated_sharpe")
    if check_holdout and metrics.holdout_deflated_sharpe <= gates.holdout_min_deflated_sharpe:
        reasons.append("holdout")
    # Beat-buy-and-hold: a promotable edge must out-return simply holding the same validation-slice basket, net of
    # fees. Without this a bull-regime long can pass every statistical gate yet underperform BTC and still get
    # funded. Mirrors research/gate.py's pre-registered `must_beat_buy_and_hold` bar. Opt-out via GateSettings so a
    # caller that has not populated `buy_and_hold_return` (default 0) is unaffected when the flag is off.
    if gates.require_beat_buy_and_hold and metrics.oos_return <= metrics.buy_and_hold_return:
        reasons.append("buy_and_hold")
    return ScoreVerdict(
        ranking_scalar=Decimal(str(round(dsr, 6))),
        deflated_sharpe_prob=Decimal(str(round(dsr, 6))),
        passed=not reasons,
        reasons=reasons,
    )
