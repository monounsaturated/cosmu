# intent: the per-combo TRADE FLOOR — the single source of truth for the minimum number of trades a tradeable
# cell (algorithm × asset × venue) must book on its OWN data before it can be judged at all. Below this a cell is
# too thin to score honestly, so the brut gate kills it pre-paper.
#
# This module USED to also carry a cross-sibling "verdict" (robust/fragile/thin/negative) that compared a cell
# against its siblings to flag best-of-N artefacts and STEER which symbol the funder deployed on. The BRUT
# per-combo model deletes that entirely: a combo is judged on its OWN data, NEVER pooled across symbols, never
# deflated by siblings, never compared to siblings. The forward/paper test is the safeguard against flukes (and
# live stays human-only), so the sibling-comparison verdict — which both ranked deploys AND fail-open-promoted —
# is gone. What remains is the one honest pre-paper intake filter: a per-cell trade-count minimum.

from __future__ import annotations

# The per-cell validation trade floor — the SINGLE source of truth, imported by the finder sweep (lab/finder.py)
# and the autonomous loop (evolution/loop.py). Below this a cell has too few fills to judge: scoring a cell on a
# handful of its own trades is statistically meaningless, so a per-cell minimum is the honest intake bar. (The
# pooled gate's min_trades=30 is a SEPARATE, larger floor on the single combo's own trades inside score(); this 5
# is the legacy breadth-era minimum kept as a cheap pre-screen — the BRUT min-trades floor of 30 is enforced via
# the gate's min_trades path on each cell's OWN num_trades.)
MIN_TRADES_PER_SYMBOL = 5


__all__ = ["MIN_TRADES_PER_SYMBOL"]
