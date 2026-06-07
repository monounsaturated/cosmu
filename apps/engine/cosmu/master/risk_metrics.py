# intent: drawdown-aware performance metrics the Sharpe is blind to. Sharpe rewards smooth per-bar returns but
# ignores TAIL DEPTH: two books with the same Sharpe but 20% vs 55% max-drawdown are NOT equally deployable.
# Calmar (annualized return / max drawdown) and Recovery Factor (total net profit / max drawdown) rank candidates
# by return-per-unit-drawdown — exactly the dimension the maxDD gate cares about, and the practitioner's
# "risk-management-IS-the-edge" lens. Pure, deterministic, no LLM, no look-ahead (operates on a realized stream).

from __future__ import annotations

import math


def max_drawdown(returns: list[float]) -> float:
    """Peak-to-trough fractional drawdown of the compounded equity curve (0.0 = none, 0.55 = a 55% drop)."""
    peak = equity = 1.0
    mdd = 0.0
    for r in returns:
        equity *= 1.0 + r
        peak = max(peak, equity)
        if peak > 0:
            mdd = max(mdd, (peak - equity) / peak)
    return mdd


def annualized_return(returns: list[float], periods_per_year: int) -> float:
    """Geometric (compound) annualized return of a per-period net-return stream."""
    if not returns:
        return 0.0
    growth = 1.0
    for r in returns:
        growth *= 1.0 + r
    if growth <= 0:
        return -1.0  # wiped out
    return growth ** (periods_per_year / len(returns)) - 1.0


def recovery_factor(total_return: float, max_dd: float) -> float:
    """Total net profit per unit of max drawdown. Higher = more return earned per unit of pain. inf when the
    book never drew down (a clean win); 0.0 when it lost money (no recovery to speak of)."""
    if max_dd <= 0:
        return math.inf if total_return > 0 else 0.0
    return total_return / max_dd


def calmar_ratio(returns: list[float], periods_per_year: int) -> float:
    """Annualized return / max drawdown — the canonical drawdown-adjusted return. inf when there is no drawdown
    and the book is up; 0.0 when flat/negative with no drawdown."""
    mdd = max_drawdown(returns)
    ann = annualized_return(returns, periods_per_year)
    if mdd <= 0:
        return math.inf if ann > 0 else 0.0
    return ann / mdd
