# intent: model per-fill execution slippage as a distribution (mean + variance), not a flat bps; inputs:
# a net-return stream, per-period turnover, and a SlippageModel; outputs: StressResult reporting the full
# Monte-Carlo Sharpe/return distribution + a fragility flag that fires when the edge flips sign or loses
# >50% of its Sharpe at the pessimistic (p05) draw; invariants: draws are half-normal (non-negative
# slippage only), deterministic given a seed, pure — no I/O, no LLM, no look-ahead; higher turnover
# scales the cost correctly (more round-trips = more slippage drag per period); zero std reproduces the
# flat-bps result exactly.

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass


@dataclass(frozen=True)
class SlippageModel:
    """Per-fill slippage parameterisation.

    `mean_bps` is the expected half-spread (in basis points).  `std_bps` is the one-sigma variability
    across fills — real books swing 5–10 bp around the mean on the same signal. `participation_bps_per_pct`
    is an optional linear participation-rate term: each 1 % of the book traded adds this many bps of
    additional expected slippage (a first-order market-impact proxy that can be set to zero).

    Draws are taken from a half-normal so slippage is always non-negative: the fill degradation is
    real, but it cannot improve execution beyond the quoted best bid/ask.
    """

    mean_bps: float
    std_bps: float
    participation_bps_per_pct: float = 0.0

    def draw(self, rng: random.Random, participation_pct: float = 0.0) -> float:
        """One random slippage draw in basis points.

        Samples a half-normal with the correct mean and std: a half-normal's mean is
        sigma_hn * sqrt(2/pi), so given a target mean mu and target std s we solve for
        sigma_hn.  The half-normal's variance is sigma_hn^2 * (1 - 2/pi).

        When std_bps == 0 the draw is deterministic (= mean + participation term), so zero-std
        mode reproduces the flat-bps result exactly regardless of the seed.
        """
        impact = self.participation_bps_per_pct * participation_pct
        base_mean = self.mean_bps + impact

        if self.std_bps <= 0.0:
            return max(0.0, base_mean)

        # Parametrise the half-normal so E[X] = base_mean and Std[X] ≈ std_bps.
        # For X ~ HalfNormal(sigma): E[X] = sigma*sqrt(2/pi), Var[X] = sigma^2*(1-2/pi).
        # We match E[X] = base_mean by choosing sigma = base_mean / sqrt(2/pi).
        # std_bps controls the scale of the *additional* noise layer drawn independently.
        # We add a half-normal noise with mean 0, std std_bps:
        #   total_slip = gauss_abs(0, sigma_noise) where sigma_noise = std_bps / sqrt(1 - 2/pi)
        # so that the added noise has std == std_bps and is non-negative.
        _TWO_OVER_PI = 2.0 / math.pi
        _ONE_MINUS_TWO_OVER_PI = 1.0 - _TWO_OVER_PI  # ≈ 0.3634

        # sigma_hn for the noise component such that Std[|N(0,sigma_hn)|] = std_bps
        sigma_noise = self.std_bps / math.sqrt(_ONE_MINUS_TWO_OVER_PI)
        noise = abs(rng.gauss(0.0, sigma_noise))

        # The base draw is a half-normal centred on base_mean, with the noise component having std std_bps.
        # We draw a half-normal for the mean component too, so the floor is deterministically >= 0.
        sigma_mean = base_mean / math.sqrt(_TWO_OVER_PI) if base_mean > 0.0 else 0.0
        mean_draw = abs(rng.gauss(0.0, sigma_mean)) if sigma_mean > 0.0 else 0.0

        # Blend: when noise_std is small this is mostly the mean component; as std_bps grows the noise
        # dominates.  The draw is always >= 0.
        return max(0.0, mean_draw + noise - base_mean * math.sqrt(_TWO_OVER_PI) + base_mean)


@dataclass(frozen=True)
class StressResult:
    """Monte-Carlo slippage stress-test output.

    `sharpe_distribution` and `total_return_distribution` contain one value per path (length == `draws`).
    `p05_sharpe` / `p05_total_return` are the 5th-percentile (pessimistic) outcomes across paths.
    `base_sharpe` / `base_total_return` are the results at MEAN slippage with no random noise (std=0)
    — the reference the edge was measured against.
    `fragile` is True when the edge is only positive at mean slippage but turns non-positive (or loses
    >50% of its Sharpe) at the p05 draw — the signal an operator must investigate before going live.
    """

    sharpe_distribution: list[float]
    total_return_distribution: list[float]
    p05_sharpe: float
    p05_total_return: float
    base_sharpe: float
    base_total_return: float
    fragile: bool
    draws: int
    model: SlippageModel


def _annualized_sharpe(returns: list[float], periods_per_year: float) -> float:
    """Population Sharpe (pstdev) annualized. Matches backtest.py's _sharpe exactly."""
    if len(returns) < 2:
        return 0.0
    std = statistics.pstdev(returns)
    if std == 0.0:
        return 0.0
    return statistics.fmean(returns) / std * math.sqrt(periods_per_year)


def _total_return(returns: list[float]) -> float:
    """Compound total return from a sequence of per-period returns."""
    result = 1.0
    for r in returns:
        result *= 1.0 + r
    return result - 1.0


def _apply_slippage_to_returns(
    net_returns: list[float],
    turnover_per_period: list[float],
    model: SlippageModel,
    rng: random.Random,
) -> list[float]:
    """Apply one path of random slippage draws to a net-return stream.

    `turnover_per_period` is the fraction of the book traded each period (0–1 range).  Each period's
    slippage cost = draw_bps / 10000 * turnover — the product of how much slippage a fill costs and
    how many fills (scaled by position size) happen that period.  The net return is reduced by this
    additional cost so high-turnover strategies pay more.
    """
    out: list[float] = []
    for ret, turnover in zip(net_returns, turnover_per_period):
        slip_bps = model.draw(rng, participation_pct=turnover * 100.0)
        slip_frac = slip_bps / 10_000.0
        # Cost applies on entry AND exit (round-trip), proportional to the amount turned over.
        additional_cost = slip_frac * turnover * 2.0
        out.append(ret - additional_cost)
    return out


def stress_returns(
    net_returns: list[float],
    turnover_per_period: list[float] | float,
    model: SlippageModel,
    *,
    draws: int = 200,
    seed: int = 42,
    periods_per_year: float = 365.0,
) -> StressResult:
    """Monte-Carlo slippage stress-test: apply random slippage draws across many paths and report
    the distribution of resulting Sharpe + total return, the p05 (pessimistic) outcome, and a fragility
    flag.

    Args:
        net_returns: Per-period net returns (already net of flat mean slippage + fees from the backtest).
            The stress-test ADDS additional slippage variance on top — it does not re-apply the mean.
            To test from scratch pass gross returns and set model.mean_bps to the full expected cost.
        turnover_per_period: Fraction of the book traded each period.  Scalar → broadcast to all periods.
            Higher turnover multiplies slippage cost per period (correct direction: a 100%-turnover daily
            rebalancer pays far more slippage than a buy-and-hold).
        model: SlippageModel specifying mean + variance of per-fill slippage.
        draws: Number of Monte-Carlo paths.  200 is enough to resolve the p05 to ~1 path.
        seed: Deterministic RNG seed.  Same seed + same inputs → identical StressResult.
        periods_per_year: Annualisation factor for the Sharpe (365 for daily, 8760 for hourly, etc.).

    Returns:
        StressResult with the full distribution, p05 outcomes, the base (mean-slippage) reference,
        and the fragility flag.
    """
    if not net_returns:
        empty_model = model
        return StressResult(
            sharpe_distribution=[],
            total_return_distribution=[],
            p05_sharpe=0.0,
            p05_total_return=0.0,
            base_sharpe=0.0,
            base_total_return=0.0,
            fragile=False,
            draws=draws,
            model=empty_model,
        )

    n = len(net_returns)

    # Normalise turnover to a per-period list.
    if isinstance(turnover_per_period, (int, float)):
        turnover_list = [float(turnover_per_period)] * n
    else:
        if len(turnover_per_period) != n:
            raise ValueError(
                f"turnover_per_period length {len(turnover_per_period)} != net_returns length {n}"
            )
        turnover_list = [float(t) for t in turnover_per_period]

    # Base outcome: zero-std model at mean slippage only (the flat-bps reference).
    base_model = SlippageModel(
        mean_bps=model.mean_bps,
        std_bps=0.0,
        participation_bps_per_pct=model.participation_bps_per_pct,
    )
    base_rng = random.Random(seed)
    base_path = _apply_slippage_to_returns(net_returns, turnover_list, base_model, base_rng)
    base_sharpe = _annualized_sharpe(base_path, periods_per_year)
    base_total = _total_return(base_path)

    # Monte-Carlo paths with full variance.
    rng = random.Random(seed)
    sharpe_dist: list[float] = []
    return_dist: list[float] = []

    for _ in range(draws):
        path = _apply_slippage_to_returns(net_returns, turnover_list, model, rng)
        sharpe_dist.append(_annualized_sharpe(path, periods_per_year))
        return_dist.append(_total_return(path))

    sharpe_dist_sorted = sorted(sharpe_dist)
    return_dist_sorted = sorted(return_dist)

    # p05: 5th percentile (floor at index 0 to avoid off-by-one on small draw counts).
    p05_idx = max(0, int(math.floor(0.05 * draws)) - 1)
    p05_sharpe = sharpe_dist_sorted[p05_idx]
    p05_total = return_dist_sorted[p05_idx]

    # Fragility: the edge is FRAGILE when the p05 path either flips the Sharpe sign/to-zero OR
    # loses more than 50% of the base Sharpe.  Separately, a negative total return at p05 is also
    # fragile regardless of Sharpe magnitude.
    sharpe_flipped = p05_sharpe <= 0.0
    sharpe_halved = base_sharpe > 0.0 and p05_sharpe < base_sharpe * 0.5
    return_negative = p05_total <= 0.0
    fragile = sharpe_flipped or sharpe_halved or return_negative

    return StressResult(
        sharpe_distribution=sharpe_dist,
        total_return_distribution=return_dist,
        p05_sharpe=p05_sharpe,
        p05_total_return=p05_total,
        base_sharpe=base_sharpe,
        base_total_return=base_total,
        fragile=fragile,
        draws=draws,
        model=model,
    )
