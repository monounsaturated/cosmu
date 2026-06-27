# intent: a PURE, deterministic funded-track BOOK simulator to prove the portfolio-axis crowding clamp — run a book
# of standalone cells WITH vs WITHOUT the signal-crowding clamp and report total return + max drawdown for each.
# It answers exactly the playbook's WITH-vs-WITHOUT question (bridge #7): does scaling DOWN a crowded cluster keep
# return ~similar while cutting max drawdown?
#
# NO POOLED WALLET — the COSMU model is N standalone equal-capital slices, never a shared pot. Each cell gets the
# SAME base slice; its portfolio-axis factor only decides how much of ITS OWN slice it deploys (the undeployed part
# sits in cash, it is NOT handed to another cell — that would be the removed pooled allocator). The book equity is
# the SUM of the slices each bar. This is a measurement instrument, not money movement: it takes per-cell realized
# return streams (e.g. from data/backtest.run_strategy_backtest_detailed, or a disclosed fixture) and the factors
# from master/signal_crowding, and reports book-level stats. PURE: no I/O, no DB, deterministic.

from __future__ import annotations

from dataclasses import dataclass

from cosmu.master.signal_crowding import PortfolioCell, portfolio_exposure_factors


@dataclass(frozen=True)
class BookResult:
    total_return: float       # book final/initial − 1 over the window
    max_drawdown: float       # worst peak-to-trough on the book equity curve, as a positive fraction
    equity_curve: list[float]  # book equity per bar, starting at 1.0 × n_cells (one slice each)

    @property
    def recovery_factor(self) -> float:
        """Total return per unit of max drawdown — the drawdown-aware quality number. inf when no drawdown."""
        return self.total_return / self.max_drawdown if self.max_drawdown > 0 else float("inf")


@dataclass(frozen=True)
class ClampComparison:
    without_clamp: BookResult   # cells sized by fractional Kelly only (no signal-crowding de-weight)
    with_clamp: BookResult      # cells sized by Kelly × signal-crowding factor
    return_delta: float         # with − without (absolute return difference)
    return_relative_change: float  # (with − without) / |without|  (≈0 ⇒ "similar return")
    drawdown_delta: float       # with − without (negative ⇒ the clamp REDUCED max drawdown)
    n_capped: int               # cells the clamp scaled down
    n_clusters: int             # signal-crowding clusters found


def _max_drawdown(equity: list[float]) -> float:
    """Worst peak-to-trough decline on an equity curve, as a positive fraction (0.0 when monotone up/flat)."""
    peak = float("-inf")
    worst = 0.0
    for v in equity:
        peak = max(peak, v)
        if peak > 0:
            worst = max(worst, (peak - v) / peak)
    return worst


def simulate_book(
    returns_by_cell: dict[str, list[float]],
    factors_by_cell: dict[str, float],
    *,
    slice_capital: float = 1.0,
) -> BookResult:
    """Aggregate standalone equal-capital slices into a book equity curve.

    Each cell gets the SAME `slice_capital`. Its factor `f` deploys `f × slice_capital` (compounding at the cell's
    per-bar net returns); the remaining `(1 − f) × slice_capital` stays in cash (flat) — NOT redeployed to other
    cells. The book equity each bar is the sum across cells. Streams are trailing-aligned to the shortest length so
    cells that started at different times still sum honestly (the same alignment master/strategy_correlation uses).

    Returns the book total return + max drawdown over the common window. PURE + deterministic."""
    ids = sorted(returns_by_cell)
    if not ids:
        return BookResult(total_return=0.0, max_drawdown=0.0, equity_curve=[])
    n = min(len(returns_by_cell[i]) for i in ids)
    if n == 0:
        base = slice_capital * len(ids)
        return BookResult(total_return=0.0, max_drawdown=0.0, equity_curve=[base])

    # Per-cell deployed/cash split (frozen for the window — the factor is a funding-time scalar).
    deployed = {i: max(0.0, float(factors_by_cell.get(i, 1.0))) * slice_capital for i in ids}
    cash = {i: slice_capital - deployed[i] for i in ids}
    grown = dict(deployed)  # running compounded value of each cell's deployed sleeve

    book0 = slice_capital * len(ids)
    equity = [book0]
    for bar in range(n):
        total = 0.0
        for i in ids:
            r = returns_by_cell[i][-n:][bar]
            grown[i] *= (1.0 + r)
            total += grown[i] + cash[i]
        equity.append(total)

    total_return = equity[-1] / equity[0] - 1.0 if equity[0] > 0 else 0.0
    return BookResult(total_return=total_return, max_drawdown=_max_drawdown(equity), equity_curve=equity)


def compare_clamp(
    cells: list[PortfolioCell],
    returns_by_cell: dict[str, list[float]],
    *,
    corr_cap: float | None = None,
    kelly_scale: float | None = None,
) -> ClampComparison:
    """Run the funded-track book WITH vs WITHOUT the portfolio-axis signal-crowding clamp.

    BOTH arms apply fractional-Kelly self-sizing (build item 1) — the only thing that differs is the clamp:
      • WITHOUT clamp — factor = kelly_size_multiplier(deflated_edge)            (no signal-crowding de-weight)
      • WITH clamp    — factor = kelly_size_multiplier(deflated_edge) × crowding (redundant cluster members scaled down)
    so the comparison ISOLATES the clamp. Expectation (playbook bridge #7): with-clamp ≈ same total return, lower
    max drawdown — the clamp sheds redundant, synchronised exposure that drives the book's worst peak-to-trough
    without shedding much UNIQUE return (the cluster's edge is kept via its representative). PURE + deterministic."""
    kw = {} if corr_cap is None else {"corr_cap": corr_cap}
    report = portfolio_exposure_factors(cells, kelly_scale=kelly_scale, **kw)

    # WITHOUT clamp: Kelly only (crowding forced to 1.0). WITH clamp: the combined Kelly × crowding.
    kelly_only = {cid: cf.kelly for cid, cf in report.factors.items()}
    combined = report.combined()

    without = simulate_book(returns_by_cell, kelly_only)
    with_clamp = simulate_book(returns_by_cell, combined)

    rel = (with_clamp.total_return - without.total_return) / abs(without.total_return) if without.total_return else 0.0
    return ClampComparison(
        without_clamp=without,
        with_clamp=with_clamp,
        return_delta=with_clamp.total_return - without.total_return,
        return_relative_change=rel,
        drawdown_delta=with_clamp.max_drawdown - without.max_drawdown,
        n_capped=report.n_capped,
        n_clusters=report.n_clusters,
    )
