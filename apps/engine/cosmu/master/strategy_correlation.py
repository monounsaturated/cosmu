# intent: pure diagnostic helper for cross-strategy return-stream correlation — identify REDUNDANT funded or
# candidate tracks before the floor allocates capital to near-identical books. Propose-only: this module
# NEVER moves money, never gates a strategy, never writes to the store. Callers read its output and decide.
# Inputs: {strategy_id: [per-bar net returns]} dicts. Outputs: CorrelationReport (pairwise matrix +
# redundancy flags). All thresholds are named constants so they appear once and are trivially tuneable.
# Deterministic: given the same return streams the output is always identical — no randomness, no I/O.

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import fmean

# ---------------------------------------------------------------------------
# Named thresholds — change here, nowhere else.
# ---------------------------------------------------------------------------

# Spearman rank-correlation above this threshold ⇒ the two tracks are flagged REDUNDANT.
# At 0.85 a pair that moves together 85 % of the time in rank order is diversification noise.
REDUNDANCY_THRESHOLD: float = 0.85

# Minimum number of overlapping observations required to compute a meaningful correlation.
# Below this floor the estimate is noise; we return NaN and do NOT flag redundancy.
MIN_OVERLAP: int = 20

# A 1-indexed "cluster" label of 0 means the strategy was not assigned to a cluster (isolated book).
_NO_CLUSTER: int = 0


# ---------------------------------------------------------------------------
# Data containers (frozen → safe to cache / pass across threads)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PairCorrelation:
    """Spearman correlation between one pair of strategy return streams."""

    strategy_a: str
    strategy_b: str
    # Spearman rank-correlation in [-1, 1], or NaN when overlap < MIN_OVERLAP.
    correlation: float
    # Number of bars where BOTH strategies had a return observation.
    overlap: int
    # True when |correlation| >= REDUNDANCY_THRESHOLD and overlap >= MIN_OVERLAP.
    redundant: bool


@dataclass(frozen=True)
class CorrelationReport:
    """Full pairwise correlation diagnostics for a set of strategy tracks.

    `pairs` — every unique (a, b) combination, sorted lexicographically by strategy id.
    `redundant_pairs` — subset where `redundant=True`.
    `clusters` — connected components of the redundancy graph: strategies flagged as redundant
        with one another are grouped together. A strategy with no redundant partners is absent
        from this dict. Cluster ids are arbitrary positive integers (not stable across calls).
    `average_pairwise_correlation` — mean Spearman ρ across all pairs with valid overlap (NaN
        when there are fewer than 2 strategies or no valid pairs). Useful as the `sr_correlation`
        input to `scorer.effective_trials`.
    """

    pairs: tuple[PairCorrelation, ...]
    redundant_pairs: tuple[PairCorrelation, ...]
    # {strategy_id: cluster_id}; only strategies in at least one redundant pair are included.
    clusters: dict[str, int]
    average_pairwise_correlation: float


# ---------------------------------------------------------------------------
# Core rank computation (no external dependencies)
# ---------------------------------------------------------------------------


def _rank(values: list[float]) -> list[float]:
    """Assign average ranks to values (handles ties). Returns a parallel list of rank values."""
    n = len(values)
    if n == 0:
        return []
    # pair each value with its index, sort by value
    indexed = sorted(range(n), key=lambda i: values[i])
    ranks: list[float] = [0.0] * n
    i = 0
    while i < n:
        j = i
        # find run of equal values
        while j < n - 1 and values[indexed[j + 1]] == values[indexed[j]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0  # 1-based average rank
        for k in range(i, j + 1):
            ranks[indexed[k]] = avg_rank
        i = j + 1
    return ranks


def _spearman(xs: list[float], ys: list[float]) -> float:
    """Spearman rank-correlation between two equal-length lists. Returns NaN on degenerate input."""
    n = len(xs)
    if n < 2:
        return float("nan")
    rx = _rank(xs)
    ry = _rank(ys)
    mx = fmean(rx)
    my = fmean(ry)
    num = fmean([(rx[i] - mx) * (ry[i] - my) for i in range(n)])
    var_x = fmean([(r - mx) ** 2 for r in rx])
    var_y = fmean([(r - my) ** 2 for r in ry])
    if var_x <= 0 or var_y <= 0:
        return float("nan")
    return num / math.sqrt(var_x * var_y)


# ---------------------------------------------------------------------------
# Overlap alignment
# ---------------------------------------------------------------------------


def _overlapping_returns(
    a_returns: list[float],
    b_returns: list[float],
) -> tuple[list[float], list[float]]:
    """Return the suffix of both series where BOTH have observations.

    Strategy tracks may start at different times. We use a simple trailing-alignment: take the last
    min(len(a), len(b)) bars of each series, which assumes bars are aligned to the same calendar
    (same bar cadence, most-recent bar last). If callers have date-indexed series they should
    pre-align before passing here; this function is the degenerate-length safety net only.
    """
    n = min(len(a_returns), len(b_returns))
    return a_returns[-n:], b_returns[-n:]


# ---------------------------------------------------------------------------
# Union–Find for connected-component clustering
# ---------------------------------------------------------------------------


def _cluster_redundant_pairs(
    redundant: list[PairCorrelation],
) -> dict[str, int]:
    """Union-Find over the redundancy graph. Returns {strategy_id: cluster_id}."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent.get(x, x), parent.get(x, x))
            x = parent.get(x, x)
        return x

    def union(x: str, y: str) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for p in redundant:
        if p.strategy_a not in parent:
            parent[p.strategy_a] = p.strategy_a
        if p.strategy_b not in parent:
            parent[p.strategy_b] = p.strategy_b
        union(p.strategy_a, p.strategy_b)

    # assign stable integer ids
    root_to_id: dict[str, int] = {}
    result: dict[str, int] = {}
    next_id = 1
    for sid in parent:
        root = find(sid)
        if root not in root_to_id:
            root_to_id[root] = next_id
            next_id += 1
        result[sid] = root_to_id[root]
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def pairwise_correlation(
    streams: dict[str, list[float]],
    *,
    redundancy_threshold: float = REDUNDANCY_THRESHOLD,
    min_overlap: int = MIN_OVERLAP,
) -> CorrelationReport:
    """Compute the full pairwise Spearman correlation matrix for a set of return streams.

    Parameters
    ----------
    streams:
        Mapping of {strategy_id: [per-bar net returns]}, bars ordered oldest-first.
        Streams may differ in length; only the overlapping suffix is correlated.
    redundancy_threshold:
        |ρ| >= this value AND overlap >= min_overlap ⇒ flagged REDUNDANT. Defaults to
        the module constant `REDUNDANCY_THRESHOLD`.
    min_overlap:
        Minimum bars of overlap to compute a valid ρ. Below this, ρ=NaN and redundant=False.

    Returns
    -------
    CorrelationReport
        A frozen, propose-only diagnostic. Caller decides what to do with it.
    """
    ids = sorted(streams)  # lexicographic — deterministic ordering
    pairs: list[PairCorrelation] = []
    valid_rhos: list[float] = []

    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            sid_a = ids[i]
            sid_b = ids[j]
            a_aligned, b_aligned = _overlapping_returns(streams[sid_a], streams[sid_b])
            overlap = len(a_aligned)
            if overlap < min_overlap:
                rho = float("nan")
                redundant = False
            else:
                rho = _spearman(a_aligned, b_aligned)
                if math.isnan(rho):
                    redundant = False
                else:
                    valid_rhos.append(rho)
                    redundant = abs(rho) >= redundancy_threshold

            pairs.append(
                PairCorrelation(
                    strategy_a=sid_a,
                    strategy_b=sid_b,
                    correlation=rho,
                    overlap=overlap,
                    redundant=redundant,
                )
            )

    redundant_pairs = [p for p in pairs if p.redundant]
    clusters = _cluster_redundant_pairs(redundant_pairs)
    avg_rho = fmean(valid_rhos) if valid_rhos else float("nan")

    return CorrelationReport(
        pairs=tuple(pairs),
        redundant_pairs=tuple(redundant_pairs),
        clusters=clusters,
        average_pairwise_correlation=avg_rho,
    )


def redundant_strategy_ids(report: CorrelationReport) -> frozenset[str]:
    """Convenience: flat set of all strategy ids involved in at least one redundant pair."""
    result: set[str] = set()
    for p in report.redundant_pairs:
        result.add(p.strategy_a)
        result.add(p.strategy_b)
    return frozenset(result)


def summarise(report: CorrelationReport) -> str:
    """Human-readable one-paragraph diagnostic — for logging / console output only, never for gate logic."""
    n_strategies = len({sid for p in report.pairs for sid in (p.strategy_a, p.strategy_b)})
    n_pairs = len(report.pairs)
    n_redundant = len(report.redundant_pairs)
    n_clusters = len(set(report.clusters.values()))
    avg = report.average_pairwise_correlation
    avg_str = f"{avg:.3f}" if not math.isnan(avg) else "n/a"
    lines = [
        f"Strategy correlation scan: {n_strategies} tracks, {n_pairs} pairs, "
        f"avg ρ={avg_str}, redundancy threshold={REDUNDANCY_THRESHOLD}.",
    ]
    if n_redundant == 0:
        lines.append("All tracks are sufficiently decorrelated — no redundant pairs detected.")
    else:
        lines.append(
            f"REDUNDANT: {n_redundant} pair(s) in {n_clusters} cluster(s). "
            f"Recommend funding only ONE track per cluster."
        )
        for p in report.redundant_pairs:
            lines.append(f"  {p.strategy_a} <-> {p.strategy_b}  ρ={p.correlation:.3f}  overlap={p.overlap}")
    return "\n".join(lines)
