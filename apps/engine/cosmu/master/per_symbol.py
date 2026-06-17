# intent: the HONEST per-symbol verdict — a VISIBILITY label over one strategy version's per-(symbol,venue) backtest
# cells, NEVER a funding gate. The pooled deflated Gate (master/scorer.py + cohort.py, correlation-aware via
# cluster_representatives + a REAL cohort CSCV-PBO) is the SOLE funding authority and is untouched by this module.
# This only LABELS which per-symbol cells look like a real, GENERALIZING edge versus a best-of-N artefact, so the
# /lab front can let the operator SNIPE outliers ("pas de moyennes bêtes") without being fooled by the multiple-
# testing trap: with N symbols tested, the single best one is inflated by selection. A lone winner among many is
# the trap; a winner corroborated across the tested universe is not.
#
# Pure: operates on the stored summary stats (return + trade count per symbol) — no return streams, no DB, no
# settings, no I/O. Deterministic. The verdict is advisory metadata for display + the rejects/eval lanes; it can
# only ever ADD caution, never promote anything the deterministic Gate disposed.
#
# KNOWN REFINEMENT (documented, not yet wired): generalization is counted treating symbols as INDEPENDENT, but
# crypto majors are highly correlated (BTC~ETH), so "2 winners of 5" can be ~1 independent confirmation. The
# correlation-aware version uses cluster_representatives over the per-symbol return STREAMS (the same primitive the
# Gate uses) once those are persisted, or an asset-class correlation prior. v1 is the transparent count-based label.

from __future__ import annotations

from dataclasses import dataclass

# The per-symbol validation trade floor — the SINGLE source of truth, imported by the finder sweep (lab/finder.py)
# and the autonomous loop (evolution/loop.py). Below this a cell has too few fills to judge: the pooled gate's
# min_trades=30 can be met by ~6 trades on each of 5 symbols, so a per-symbol minimum is the honest breadth test.
MIN_TRADES_PER_SYMBOL = 5

# The fraction of judgeable (non-thin) symbols that must be winners for the edge to count as GENERALIZING. At/above
# this, every winning cell is ROBUST; below it, a winning cell is FRAGILE (a minority winner = best-of-N caution).
# The one tunable knob — kept explicit so the methodology is a localized change, never a scattered constant.
GENERALIZE_FRACTION = 0.5

# The verdict vocabulary (small + single-source, mirroring knowledge/lifecycle_status discipline). A cell carries
# exactly one of these; NULL in the DB means "persisted but not yet classified" (legacy rows / pre-classifier).
THIN = "thin"          # below the per-symbol trade floor — not enough fills to judge (excluded from generalization)
NEGATIVE = "negative"  # cleared the floor but is net non-positive on this symbol
FRAGILE = "fragile"    # net-positive on THIS symbol, but the edge does NOT generalize across the tested universe —
#                        a lone / minority winner: exactly the best-of-N artefact. Investigate; never trust as proven.
ROBUST = "robust"      # net-positive here AND the edge generalizes (>= GENERALIZE_FRACTION of judgeable cells win)

VERDICTS = frozenset({THIN, NEGATIVE, FRAGILE, ROBUST})


@dataclass(frozen=True)
class PerSymbolCell:
    """One strategy version's standalone backtest result on one symbol — the minimal inputs the honest label needs."""

    symbol: str
    return_pct: float
    trades: int


def _cells_from_per_symbol(per_symbol: dict[str, dict[str, float]] | None) -> list[PerSymbolCell]:
    """Adapt a BacktestResult.per_symbol dict ({symbol: {return, sharpe, max_drawdown, trades}}) to cells. The SAME
    shape the finder + loop already hold at persist time, so neither writer hand-rolls the conversion."""
    return [
        PerSymbolCell(symbol=s, return_pct=float(pm.get("return", 0.0)), trades=int(pm.get("trades", 0)))
        for s, pm in (per_symbol or {}).items()
    ]


def edge_generalizes(cells: list[PerSymbolCell], *, min_trades: int = MIN_TRADES_PER_SYMBOL,
                     generalize_fraction: float = GENERALIZE_FRACTION) -> bool:
    """True when a fraction >= generalize_fraction of the JUDGEABLE (>= min_trades) cells are net-positive winners.
    Thin cells are excluded from the denominator (you can't judge what didn't trade). No judgeable cell → False
    (nothing to generalize). This is the cross-asset corroboration signal the best-of-N trap lacks."""
    judgeable = [c for c in cells if c.trades >= min_trades]
    if not judgeable:
        return False
    winners = sum(1 for c in judgeable if c.return_pct > 0.0)
    return (winners / len(judgeable)) >= generalize_fraction


def classify_per_symbol(per_symbol: dict[str, dict[str, float]] | None, *,
                        min_trades: int = MIN_TRADES_PER_SYMBOL,
                        generalize_fraction: float = GENERALIZE_FRACTION) -> dict[str, str]:
    """Label every symbol cell of ONE strategy version. Returns {symbol: verdict in VERDICTS}.

    A cell below the trade floor is THIN. A judgeable cell that is net non-positive is NEGATIVE. A judgeable winner
    is ROBUST when the edge GENERALIZES across the tested universe, else FRAGILE — so a lone strong symbol amid
    losers (the best-of-N artefact the operator flagged) is surfaced with caution, not celebrated as proven. The
    generalization test is computed ONCE over the whole set, then applied per winning cell."""
    cells = _cells_from_per_symbol(per_symbol)
    generalizes = edge_generalizes(cells, min_trades=min_trades, generalize_fraction=generalize_fraction)
    out: dict[str, str] = {}
    for c in cells:
        if c.trades < min_trades:
            out[c.symbol] = THIN
        elif c.return_pct <= 0.0:
            out[c.symbol] = NEGATIVE
        else:
            out[c.symbol] = ROBUST if generalizes else FRAGILE
    return out


__all__ = [
    "GENERALIZE_FRACTION",
    "MIN_TRADES_PER_SYMBOL",
    "VERDICTS",
    "FRAGILE",
    "NEGATIVE",
    "ROBUST",
    "THIN",
    "PerSymbolCell",
    "classify_per_symbol",
    "edge_generalizes",
]
