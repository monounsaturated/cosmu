# intent: Benjamini-Hochberg false-discovery-rate control across all candidate trials so an LLM generating
# unlimited ideas can't manufacture a "winner" by sheer count; inputs: candidate p-values; outputs: reject mask
# at level q; invariants: deterministic, out of any agent's reach, and applied over EVERY registered trial.

from __future__ import annotations


def dsr_pvalue(deflated_sharpe_prob: float) -> float:
    """Turn a Deflated-Sharpe probability P(SR>0) into a one-sided p-value for the null 'no edge'."""
    return max(0.0, min(1.0, 1.0 - deflated_sharpe_prob))


def bh_threshold(pvalues: list[float], q: float = 0.10) -> float:
    """The Benjamini-Hochberg cutoff: the largest p_(k) with p_(k) <= (k/m) * q. Returns 0.0 if none qualify
    (nothing survives) — so a candidate is significant iff its p-value <= this threshold."""
    m = len(pvalues)
    if m == 0:
        return 0.0
    ordered = sorted(pvalues)
    threshold = 0.0
    for k, p in enumerate(ordered, start=1):
        if p <= (k / m) * q:
            threshold = p  # keep the largest passing p-value
    return threshold


def benjamini_hochberg(pvalues: list[float], q: float = 0.10) -> list[bool]:
    """Reject mask aligned to the input order: True = discovery survives FDR control at level q."""
    cutoff = bh_threshold(pvalues, q)
    return [p <= cutoff for p in pvalues]


def survives_fdr(candidate_pvalue: float, all_pvalues: list[float], q: float = 0.10) -> bool:
    """Does one candidate clear BH-FDR within the full set of registered p-values? `all_pvalues` must
    already include the candidate's own p-value."""
    return candidate_pvalue <= bh_threshold(all_pvalues, q)
