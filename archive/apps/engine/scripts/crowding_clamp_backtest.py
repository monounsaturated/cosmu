#!/usr/bin/env python3
# intent: run the funded-track BOOK backtest WITH vs WITHOUT the portfolio-axis signal-crowding clamp and emit the
# report numbers (playbook bridge #7). BOUNDED compute (M2/Modal-friendly: a few hundred bars × a handful of cells,
# no network, no DB).
#
# DATA HONESTY: this builds a DETERMINISTIC, fully-disclosed methodology book — NOT live trading P&L and NEVER shown
# in the app. The COSMU honest-loop rule keeps synthetic, edge-bearing constructions to CI/tests/methodology only.
# The construction is chosen to embody the exact structure the clamp targets: a crowded crypto-beta momentum CLUSTER
# (several cells whose SIGNALS move together → they ride the bull together AND get caught in the same crash) plus a
# few genuinely DECORRELATED cells that carry steady return. That is the realistic Khandani-Lo setup. The pure book
# simulator (cosmu.master.crowding_backtest.simulate_book) is data-source-agnostic: point `returns_by_cell` at real
# bars from cosmu.data.backtest.run_strategy_backtest_detailed in a session WITH exchange network and the SAME
# WITH-vs-WITHOUT comparison runs unchanged — see the report's "Reproduce on real bars" section.

from __future__ import annotations

import math
import random

from cosmu.master.crowding_backtest import ClampComparison, compare_clamp
from cosmu.master.signal_crowding import PortfolioCell, capacity_score, portfolio_exposure_factors

# ── deterministic book parameters (a trading year of daily bars) ──────────────────────────────────────────────
# The common crypto-beta factor is tuned to ROUND-TRIP: a bull that the synchronised crash gives back. That is the
# crux of the demonstration — a crowd of long-biased beta cells nets ~little over the full cycle (gains handed back
# in the crash) but shares a DEEP mid-cycle drawdown. So clamping the redundant copies costs ~no return while
# shedding the synchronised tail. (A crowd that kept its gains would be a different story — clamping would cost
# return; that is the honest boundary of the claim, stated in the report.)
N_BARS = 252
_BULL_END = 150          # bars 0..149: bull drift
_CRASH_END = 190         # bars 150..189: synchronised 40-bar crash (the crowding pain)
_BULL_DRIFT = 0.0050     # per-bar crypto-beta bull drift  → (1.005)^150 ≈ ×2.1
_CRASH_DRIFT = -0.0200   # per-bar crash decline           → (0.98)^40  ≈ ×0.45  (≈ round-trip)
_CHOP_DRIFT = 0.0010     # per-bar choppy partial recovery
_BETA_NOISE = 0.010      # idiosyncratic noise on the common beta factor
_IDIO_NOISE = 0.003      # per-cell idiosyncratic return noise
_MOM_SHORT = 5           # trend fast MA (bars) — the desired-exposure SIGNAL
_MOM_LONG = 20           # trend slow MA (bars)
_SEED = 20260627


def _beta_factor() -> list[float]:
    """The common crypto-beta per-bar return path: bull → synchronised crash → choppy recovery. The crash is what
    a crowd of correlated momentum cells eats TOGETHER (the whole point of the demonstration)."""
    rng = random.Random(_SEED)
    out: list[float] = []
    for t in range(N_BARS):
        if t < _BULL_END:
            drift = _BULL_DRIFT
        elif t < _CRASH_END:
            drift = _CRASH_DRIFT
        else:
            drift = _CHOP_DRIFT
        out.append(drift + rng.gauss(0.0, _BETA_NOISE))
    return out


def _prices(returns: list[float], base: float = 100.0) -> list[float]:
    px = [base]
    for r in returns:
        px.append(px[-1] * (1.0 + r))
    return px[1:]


def _sma(values: list[float], n: int) -> list[float]:
    out: list[float] = []
    for i in range(len(values)):
        lo = max(0, i - n + 1)
        window = values[lo : i + 1]
        out.append(sum(window) / len(window))
    return out


def _momentum_signal(returns: list[float]) -> list[float]:
    """Continuous desired-exposure signal = fast MA − slow MA of the price level (a classic MA-crossover momentum).
    Positive ⇒ the cell WANTS to be long. This is the SIGNAL stream the crowding instrument correlates — what the
    cell wants to hold, not what it earned."""
    px = _prices(returns)
    fast = _sma(px, _MOM_SHORT)
    slow = _sma(px, _MOM_LONG)
    return [f - s for f, s in zip(fast, slow)]


def _long_beta_returns(beta: list[float], seed: int) -> list[float]:
    """A long-BIASED crypto-beta cell: structurally long the factor (slow to de-risk, like real crowded momentum),
    so its realized return ≈ the beta factor + small per-cell idiosyncratic noise. Round-trips with the factor (deep
    synchronised crash), which is exactly why a crowd of these is one trade under stress."""
    rng = random.Random(seed)
    return [r + rng.gauss(0.0, _IDIO_NOISE) for r in beta]


def _independent_cell(seed: int, drift: float) -> tuple[list[float], list[float]]:
    """A genuinely decorrelated cell: an independent random-walk return stream with a steady positive drift and its
    OWN trend signal. Uncorrelated to the beta factor → it carries return THROUGH the crowd's crash and is not
    clustered with it. Returns (signal, returns)."""
    rng = random.Random(seed)
    rets = [drift + rng.gauss(0.0, 0.011) for _ in range(N_BARS)]
    sig = _momentum_signal(rets)
    return sig, rets


def build_demo_book() -> tuple[list[PortfolioCell], dict[str, list[float]]]:
    """Build the deterministic methodology book: a 4-cell crowded crypto-beta momentum cluster (high SIGNAL
    correlation) + 2 decorrelated cells. Returns (cells, returns_by_cell). Deterministic for a fixed seed.

    Capacity is set to demonstrate the RANKED feature: the crowd's members sit on progressively deeper/cheaper
    majors; one crowd member trades a NICHE pair (small daily volume → high capacity_score), so within the cluster
    the keep-decision is tilted by WHERE the cell plays, not by edge alone."""
    beta = _beta_factor()
    cells: list[PortfolioCell] = []
    returns_by_cell: dict[str, list[float]] = {}

    # The crowded cluster: 4 long-biased crypto-beta cells with near-identical trend SIGNALS (tiny per-cell jitter)
    # and near-equal edges — so the cluster keep-decision turns on CAPACITY, not edge. Each carries a real daily
    # quote-volume → capacity_score; the niche member (small but fillable volume) earns the highest capacity rank and
    # WINS the keep (game-selection: deploy the full slice WHERE the moat is).
    crowd = [
        # (id, deflated_edge, our_notional, daily_volume_usd)
        ("momo_btc", 0.962, 10_000.0, 9_000_000_000.0),   # deep major: fillable, no moat → capacity rank ≈ 0.50
        ("momo_eth", 0.960, 10_000.0, 4_000_000_000.0),
        ("momo_sol", 0.964, 10_000.0, 600_000_000.0),
        ("momo_niche", 0.958, 10_000.0, 8_000_000.0),     # NICHE alt: desk-invisible but fillable → high capacity
    ]
    sig_rng = random.Random(_SEED + 1)
    base_sig = _momentum_signal(beta)
    for k, (cid, edge, notional, vol) in enumerate(crowd):
        signal = [s + sig_rng.gauss(0.0, 0.05) for s in base_sig]  # tiny jitter — still corr > 0.70
        rets = _long_beta_returns(beta, seed=_SEED + 100 + k)
        cap = capacity_score(notional, vol)
        cells.append(PortfolioCell(id=cid, signal=signal, deflated_edge=edge, capacity=cap))
        returns_by_cell[cid] = rets

    # Decorrelated cells: independent processes, steady drift, their own signals. They carry book return through the
    # crowd's crash.
    for k, (cid, edge, drift, notional, vol) in enumerate([
        ("meanrev_a", 0.958, 0.0022, 10_000.0, 40_000_000.0),
        ("carry_b", 0.961, 0.0020, 10_000.0, 12_000_000.0),
    ]):
        sig, rets = _independent_cell(seed=_SEED + 500 + k, drift=drift)
        cells.append(PortfolioCell(id=cid, signal=sig, deflated_edge=edge, capacity=capacity_score(notional, vol)))
        returns_by_cell[cid] = rets

    return cells, returns_by_cell


def run() -> ClampComparison:
    cells, returns_by_cell = build_demo_book()
    return compare_clamp(cells, returns_by_cell)


def _fmt_pct(x: float) -> str:
    return f"{x * 100:+.2f}%"


def main() -> None:
    cells, returns_by_cell = build_demo_book()
    report = portfolio_exposure_factors(cells)
    cmp = compare_clamp(cells, returns_by_cell)

    print("=" * 84)
    print("PORTFOLIO-AXIS CROWDING CLAMP — funded-track book backtest (WITH vs WITHOUT)")
    print("=" * 84)
    print(f"\nCells: {report.n_cells}   signal-corr cap: {report.corr_cap}   "
          f"clusters: {report.n_clusters}   cells scaled down: {report.n_capped}")
    avg = report.avg_signal_correlation
    print(f"avg pairwise SIGNAL correlation: {avg:.3f}" if not math.isnan(avg) else "avg signal corr: n/a")
    print("\nPer-cell factors (combined = kelly × crowding):")
    print(f"  {'cell':<12} {'cluster':>7} {'edge→kelly':>11} {'crowd':>7} {'cap_rank':>8} {'combined':>9}  keep")
    edge_by = {c.id: c.deflated_edge for c in cells}
    for cf in sorted(report.factors.values(), key=lambda x: (x.cluster, -x.combined, x.cell_id)):
        keep = "★ KEEP" if cf.is_cluster_representative else ("· scaled" if cf.crowding < 1.0 else "")
        print(f"  {cf.cell_id:<12} {cf.cluster:>7} "
              f"{edge_by[cf.cell_id]:.3f}→{cf.kelly:.3f} {cf.crowding:>7.3f} {cf.capacity:>8.2f} "
              f"{cf.combined:>9.3f}  {keep}")

    print("\nBook backtest:")
    print(f"  {'arm':<16} {'total return':>14} {'max drawdown':>14} {'recovery (ret/DD)':>18}")
    for label, res in [("WITHOUT clamp", cmp.without_clamp), ("WITH clamp", cmp.with_clamp)]:
        rec = res.recovery_factor
        rec_s = f"{rec:.2f}" if math.isfinite(rec) else "inf"
        print(f"  {label:<16} {_fmt_pct(res.total_return):>14} {_fmt_pct(res.max_drawdown):>14} {rec_s:>18}")
    print(f"\n  Δ return:   {_fmt_pct(cmp.return_delta)}  (relative change {cmp.return_relative_change * 100:+.1f}%)")
    print(f"  Δ drawdown: {_fmt_pct(cmp.drawdown_delta)}  (negative = the clamp REDUCED max drawdown)")
    dd_red = (1 - cmp.with_clamp.max_drawdown / cmp.without_clamp.max_drawdown) * 100 if cmp.without_clamp.max_drawdown else 0.0
    print(f"  max-drawdown reduction: {dd_red:.1f}%")
    print("=" * 84)


if __name__ == "__main__":
    main()
