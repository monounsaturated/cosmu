# intent: the PORTFOLIO-AXIS crowding instrument (Khandani-Lo deleveraging risk) — the time-axis Gate judges each
# (algo × asset × venue) cell ALONE on its OWN data and is structurally BLIND to the fact that a book of separately-
# blessed cells can be the SAME trade. This module measures that, propose-only + PURE, on TWO axes the Gate cannot
# see:
#   (1) fractional-Kelly self-sizing per cell from the cell's DEFLATED edge (master/sizing.kelly_size_multiplier) —
#       bet proportional to honest, trial-deflated confidence, never the raw overfit-prone Sharpe;
#   (2) a pairwise SIGNAL-correlation matrix across live cells (not REALIZED returns — the positions the cells WANT,
#       which is what unwinds together under stress: Aug-2007 quant deleveraging, LTCM): any cluster whose signal
#       correlation exceeds a cap (default 0.70) is scaled DOWN to ~one cell's worth of exposure, so a crowd of K
#       near-identical bets is not K trades that collapse into one under stress.
# It pairs with — and is DISTINCT from — master/crowding.py (which clusters on REALIZED-return correlation and is
# already wired into the funder's tracks.exposure_factor). Realized-return crowding is ex-post (did they make money
# together?); SIGNAL crowding is ex-ante structural (do they hold the same positions?) and fires BEFORE a calm
# window can hide the redundancy. Both are propose-only overlays AFTER the per-combo gate; neither ever touches a
# gate verdict or moves money.
#
# CAPACITY is a first-class RANKED feature here (poker game-selection: "WHERE you play beats how well you play" — a
# solo's moat is small/niche/desk-invisible markets), NEVER a disqualifier: a low capacity score only lowers a
# cell's rank and tips WHICH member a crowded cluster keeps — it never kills a cell.
#
# NO POOLED WALLET: scaling a redundant member DOWN does NOT redeploy its capital to anyone (that would be the
# removed pooled allocator). The freed exposure is simply not deployed — the cluster deploys less, full stop. Each
# cell stays a standalone slice. HONEST NO-OP with < 2 cells, or when no cell has enough overlap to correlate.

from __future__ import annotations

import math
from dataclasses import dataclass

from cosmu.master.sizing import kelly_size_multiplier
from cosmu.master.strategy_correlation import pairwise_correlation

# Signal-correlation cap: a cluster of cells whose SIGNAL streams correlate at/above this is "one trade under
# stress" (red-team #6). 0.70 is deliberately TIGHTER than master/crowding's realized-return REDUNDANCY_THRESHOLD
# (0.85): signals reveal structural crowding that realized returns hide in a calm window, so the bar to flag it is
# lower. Named constant, tuneable in one place; NOT a param_space knob.
SIGNAL_CROWDING_CAP: float = 0.70

# A capped cluster member is scaled to its per-member share (1/cluster_size) but never below this floor — it must
# still deploy a real, scoreable stream. Mirrors master/crowding.MIN_EXPOSURE.
MIN_EXPOSURE: float = 0.10
FULL_EXPOSURE: float = 1.0

# ── Capacity ranking constants (game-selection, not a gate) ──────────────────────────────────────────────────
# Participation = our order notional / the market's daily quote volume. Past this fraction our own size starts to
# move the market and the edge erodes (capacity wall) — fillability falls linearly to 0 here. NOT a disqualifier:
# it only drives the [0,1] rank.
_MAX_PARTICIPATION: float = 0.02  # 2% of daily volume
# The rough daily quote-volume below which an institutional desk does not bother to compete — a solo's desk-invisible
# moat. A serious quant desk must deploy millions per trade without being more than a few % of volume, so markets
# doing roughly < $25M/day cannot absorb its size and it ignores them: that is exactly the solo's turf. Markets
# meaningfully below this earn the full niche bonus; markets far above it (BTC) are perfectly fillable but have NO
# moat, so they score the fillable BASE only. Order-of-magnitude judgment, tuneable in one place; not a gate.
_DESK_FLOOR_USD: float = 25_000_000.0
# A deep, liquid, no-moat market is still a fine place to trade (it just has no solo edge), so fillability alone
# floors the score here; the niche bonus lifts it toward 1.0 for desk-invisible markets.
_NICHE_BASE: float = 0.5
# Decades of log10 volume below the desk floor over which the niche bonus saturates (≈ one order of magnitude).
_NICHE_DECADES: float = 1.0


def capacity_score(
    order_notional_usd: float,
    daily_quote_volume_usd: float,
    *,
    max_participation: float = _MAX_PARTICIPATION,
    desk_floor_usd: float = _DESK_FLOOR_USD,
) -> float:
    """Ranked 'where to play' feature in [0, 1] — higher = better game-selection for a SOLO. NEVER a disqualifier:
    a low score lowers a cell's rank (and tips which member a crowded cluster keeps); it never kills a cell.

    Two forces (the poker game-selection insight, playbook meta-lesson #3):
    1. FILLABILITY — our size must actually fit. participation = order_notional / daily_quote_volume. At/above
       `max_participation` (default 2% of daily volume) we would move the market and the edge erodes, so fillability
       falls linearly to 0 there. A market too thin to fill our (already small) size scores low — not killed, just
       deprioritised.
    2. NICHE MOAT — a solo's edge lives in desk-invisible markets. Below `desk_floor_usd` (default $5M/day) the niche
       bonus is full; a deep market (e.g. BTC) is perfectly fillable but has NO moat, so it scores the fillable
       `_NICHE_BASE` only. score = fillability × (BASE + (1 − BASE) × niche).

    Degrades honestly: non-positive / unknown volume → 0.0 (we can't fill an unknown book); non-positive notional →
    treat as maximally fillable (0 participation). PURE + deterministic."""
    vol = float(daily_quote_volume_usd)
    if vol <= 0.0:
        return 0.0
    notional = max(0.0, float(order_notional_usd))
    cap = max(1e-12, float(max_participation))
    participation = notional / vol
    fillability = max(0.0, 1.0 - participation / cap)
    if fillability <= 0.0:
        return 0.0
    # Niche bonus: full when the market sits ~`_NICHE_DECADES` below the desk floor, 0 once it is at/above it.
    floor = max(1.0, float(desk_floor_usd))
    decades_below = (math.log10(floor) - math.log10(vol)) / max(1e-9, _NICHE_DECADES)
    niche = max(0.0, min(1.0, decades_below))
    return fillability * (_NICHE_BASE + (1.0 - _NICHE_BASE) * niche)


@dataclass(frozen=True)
class PortfolioCell:
    """One live (algo × asset × venue) cell as the portfolio-axis instrument sees it. `signal` is the per-bar SIGNAL
    stream — the position the cell WANTS each bar (desired exposure / direction), oldest-first — NOT its realized
    return: signal correlation is the Khandani-Lo crowding axis (same positions unwind together under stress).
    `deflated_edge` is the Gate's deflated-Sharpe probability for this cell (drives fractional Kelly). `capacity` is
    its `capacity_score` in [0, 1] (1.0 = unknown/neutral); it ranks WHERE the cell plays and tips cluster-keep."""

    id: str
    signal: list[float]
    deflated_edge: float
    capacity: float = 1.0


@dataclass(frozen=True)
class CellFactor:
    """Per-cell decomposition of the portfolio-axis exposure multiplier, for transparency on the verdict surface.
    `combined = kelly × crowding` is what the executor would multiply onto `size_fraction` (the same seam as
    tracks.exposure_factor). `cluster` is the redundancy-cluster id this cell fell into (0 = none / decorrelated)."""

    cell_id: str
    kelly: float
    crowding: float
    capacity: float
    combined: float
    cluster: int = 0
    is_cluster_representative: bool = False


@dataclass(frozen=True)
class PortfolioReport:
    """Propose-only portfolio-axis verdict over a set of live cells. NEVER a gate input and NEVER moves money."""

    factors: dict[str, CellFactor]
    n_cells: int
    n_clusters: int       # number of SIGNAL-crowding clusters (members > corr_cap) found
    n_capped: int         # cells scaled below FULL_EXPOSURE by the crowding clamp
    avg_signal_correlation: float
    corr_cap: float

    def combined(self) -> dict[str, float]:
        """The flat {cell_id: combined multiplier} the caller multiplies onto each cell's size_fraction."""
        return {cid: cf.combined for cid, cf in self.factors.items()}


def signal_crowding_factors(
    cells: list[PortfolioCell],
    *,
    corr_cap: float = SIGNAL_CROWDING_CAP,
    min_exposure: float = MIN_EXPOSURE,
) -> dict[str, float]:
    """Per-cell SIGNAL-crowding factor in [min_exposure, 1.0], one entry per cell id.

    Clusters cells by the Spearman correlation of their SIGNAL streams (reusing master/strategy_correlation, at the
    tighter `corr_cap`, default 0.70). Within each cluster keep the BEST representative — ranked by
    (deflated_edge × capacity), so a niche-market cell can WIN a cluster over a deeper-but-crowded one ("WHERE you
    play beats how well you play") — at FULL_EXPOSURE; scale every OTHER member to clamp(1/cluster_size,
    min_exposure, 1.0). A decorrelated cell (in no cluster) stays 1.0 — the honest no-op.

    The freed exposure is NOT redeployed (no pooled wallet): a crowd of K near-identical signals simply deploys
    ~one cell's worth in aggregate instead of K. Deterministic for fixed inputs; NEVER a gate input."""
    factors: dict[str, float] = {c.id: FULL_EXPOSURE for c in cells}
    if len(cells) < 2:
        return factors

    by_id = {c.id: c for c in cells}
    report = pairwise_correlation(
        {c.id: c.signal for c in cells}, redundancy_threshold=corr_cap
    )
    if not report.clusters:
        return factors

    members_by_cluster: dict[int, list[str]] = {}
    for cid, cluster in report.clusters.items():
        members_by_cluster.setdefault(cluster, []).append(cid)

    for members in members_by_cluster.values():
        if len(members) < 2:
            continue
        # Best representative: highest deflated_edge × capacity (game-selection tilt), deterministic tie-break on id.
        best = max(members, key=lambda c: (_rank_key(by_id[c]), c))
        share = max(min_exposure, min(FULL_EXPOSURE, 1.0 / len(members)))
        for cid in members:
            factors[cid] = FULL_EXPOSURE if cid == best else share
    return factors


def _rank_key(cell: PortfolioCell) -> float:
    """Cluster-keep rank: deflated edge weighted by capacity (the niche-moat rank). Higher = kept as the cluster's
    full-exposure representative. Capacity is a RANKED tilt, NEVER a gate: a cell that ranks last is still funded —
    it is only scaled to its cluster share (floored at min_exposure), and a DECORRELATED cell of any capacity keeps
    full exposure. A zero-capacity (unfillable) cell sorts to the bottom of its cluster (it won't be the rep), which
    is the intended game-selection behaviour — don't deploy the full slice where our size can't fill."""
    edge = max(0.0, float(cell.deflated_edge))
    cap = max(0.0, min(1.0, float(cell.capacity)))
    return edge * cap


def portfolio_exposure_factors(
    cells: list[PortfolioCell],
    *,
    corr_cap: float = SIGNAL_CROWDING_CAP,
    kelly_scale: float | None = None,
    min_exposure: float = MIN_EXPOSURE,
) -> PortfolioReport:
    """The full portfolio-axis verdict: per cell, combine fractional-Kelly self-sizing (from the DEFLATED edge) with
    the SIGNAL-crowding clamp into one frozen multiplier the executor would apply on top of size_fraction.

        combined = kelly_size_multiplier(deflated_edge) × signal_crowding_factor

    Both pieces only ever shrink a cell's OWN slice — never reallocate across cells (no pooled wallet). Propose-only,
    PURE, deterministic. `kelly_scale=None` uses the locked half-Kelly default in master/sizing."""
    crowding = signal_crowding_factors(cells, corr_cap=corr_cap, min_exposure=min_exposure)

    # Recover cluster ids + representatives for the transparency surface (re-run is cheap and keeps this pure).
    corr = pairwise_correlation({c.id: c.signal for c in cells}, redundancy_threshold=corr_cap) if len(cells) >= 2 else None
    cluster_by_id: dict[str, int] = dict(corr.clusters) if corr else {}
    reps = _representatives(cells, cluster_by_id)

    kelly_kwargs = {} if kelly_scale is None else {"kelly_scale": float(kelly_scale)}
    factors: dict[str, CellFactor] = {}
    n_capped = 0
    for c in cells:
        k = kelly_size_multiplier(c.deflated_edge, **kelly_kwargs)
        cr = crowding[c.id]
        if cr < FULL_EXPOSURE:
            n_capped += 1
        factors[c.id] = CellFactor(
            cell_id=c.id,
            kelly=k,
            crowding=cr,
            capacity=max(0.0, min(1.0, float(c.capacity))),
            combined=k * cr,
            cluster=cluster_by_id.get(c.id, 0),
            is_cluster_representative=(c.id in reps),
        )

    n_clusters = len({cl for cl in cluster_by_id.values()}) if cluster_by_id else 0
    avg_corr = corr.average_pairwise_correlation if corr else float("nan")
    return PortfolioReport(
        factors=factors,
        n_cells=len(cells),
        n_clusters=n_clusters,
        n_capped=n_capped,
        avg_signal_correlation=avg_corr,
        corr_cap=corr_cap,
    )


def _representatives(cells: list[PortfolioCell], cluster_by_id: dict[str, int]) -> set[str]:
    """The kept representative id of each crowding cluster (best deflated_edge × capacity, id tie-break)."""
    by_id = {c.id: c for c in cells}
    members_by_cluster: dict[int, list[str]] = {}
    for cid, cluster in cluster_by_id.items():
        members_by_cluster.setdefault(cluster, []).append(cid)
    reps: set[str] = set()
    for members in members_by_cluster.values():
        if len(members) < 2:
            continue
        reps.add(max(members, key=lambda c: (_rank_key(by_id[c]), c)))
    return reps


def summarise(report: PortfolioReport) -> str:
    """Human-readable one-paragraph diagnostic — logging / console only, NEVER gate logic."""
    avg = report.avg_signal_correlation
    avg_str = f"{avg:.3f}" if not math.isnan(avg) else "n/a"
    lines = [
        f"Portfolio-axis crowding scan: {report.n_cells} cells, avg signal ρ={avg_str}, "
        f"cap={report.corr_cap}. {report.n_clusters} crowded cluster(s), {report.n_capped} cell(s) scaled down.",
    ]
    for cf in sorted(report.factors.values(), key=lambda x: (x.cluster, -x.combined, x.cell_id)):
        if cf.cluster:
            tag = "KEEP" if cf.is_cluster_representative else "scaled"
            lines.append(
                f"  cluster {cf.cluster} {tag}: {cf.cell_id}  kelly={cf.kelly:.3f} × crowd={cf.crowding:.3f} "
                f"= {cf.combined:.3f}  (cap_rank={cf.capacity:.2f})"
            )
    return "\n".join(lines)
