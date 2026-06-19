# intent: PORTFOLIO-RISK overlay — turn the (already-built, propose-only) cross-cell crowding detector
# (master/strategy_correlation.pairwise_correlation) into a per-cell EXPOSURE CAP at the capital-allocation
# stage, AFTER the per-combo gate. The brut gate judges each (algo × asset × venue) cell ALONE on its OWN data;
# this module NEVER touches that verdict — it only decides how much CAPITAL a funded cluster of near-identical
# cells gets, so the book can't fund N copies of the same momentum beta at full exposure (concentration risk).
#
# Mechanism: cluster the funded+candidate cells by Spearman correlation of their REALIZED return streams; within
# each redundancy cluster keep the BEST representative (highest rolling deflated-Sharpe) at full exposure (1.0)
# and vol-scale the correlated members DOWN to 1/cluster_size — they still paper-trade (generous-paper model
# intact, each cell keeps proving itself), but the cluster's TOTAL deployed exposure is capped at ~one cell's
# worth. PURE + propose-only: no I/O, no DB, no gate, no money — the caller reads the factors and persists them.
# HONEST NO-OP when < 2 cells, or when no cell has enough overlapping return history to cluster (every factor 1.0).

from __future__ import annotations

from cosmu.master.strategy_correlation import pairwise_correlation

# A cell is sized DOWN to its cluster's per-member share (1/cluster_size) so a redundancy cluster of K
# near-identical cells deploys ~ONE cell's worth of capital in aggregate — the concentration cap. The single
# best representative per cluster is exempt (stays 1.0) so the cluster's strongest edge keeps full size.
FULL_EXPOSURE: float = 1.0
# Floor so a huge crowd never sizes a member to dust (it still needs a real, scoreable forward stream).
MIN_EXPOSURE: float = 0.10


def cluster_exposure_factors(
    streams: dict[str, list[float]],
    rolling_dsr: dict[str, float] | None = None,
    *,
    min_exposure: float = MIN_EXPOSURE,
) -> dict[str, float]:
    """Per-cell exposure factor in [min_exposure, 1.0], one entry per id in `streams`.

    `streams`   — {cell_id: [realized per-period net returns]}, the SAME shape the crowding detector consumes.
    `rolling_dsr` — {cell_id: rolling deflated-Sharpe}; picks each cluster's best representative (the member kept
                  at full exposure). Missing/None → 0.0, so ties break on cell_id (deterministic).

    A cell NOT in any redundancy cluster (decorrelated, or too little overlap to judge) gets 1.0 — the honest
    no-op. A cluster's best representative gets 1.0; every other member of that cluster gets
    clamp(1/cluster_size, min_exposure, 1.0). Deterministic for fixed inputs. NEVER a gate input."""
    factors: dict[str, float] = {cid: FULL_EXPOSURE for cid in streams}
    if len(streams) < 2:
        return factors  # nothing to crowd against — every cell at full exposure

    report = pairwise_correlation(streams)
    if not report.clusters:
        return factors  # no redundant pair survived the threshold + overlap floor → all full exposure

    dsr = rolling_dsr or {}
    # Group cell_ids by their redundancy cluster id.
    members_by_cluster: dict[int, list[str]] = {}
    for cid, cluster in report.clusters.items():
        members_by_cluster.setdefault(cluster, []).append(cid)

    for members in members_by_cluster.values():
        if len(members) < 2:
            continue
        # Best representative = highest rolling DSR; deterministic tie-break on cell_id.
        best = max(members, key=lambda c: (float(dsr.get(c, 0.0)), c))
        share = max(min_exposure, min(FULL_EXPOSURE, 1.0 / len(members)))
        for cid in members:
            factors[cid] = FULL_EXPOSURE if cid == best else share
    return factors
