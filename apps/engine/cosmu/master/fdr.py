# intent: Benjamini-Hochberg false-discovery-rate control across all candidate trials so an LLM generating
# unlimited ideas can't manufacture a "winner" by sheer count; inputs: candidate p-values; outputs: reject mask
# at level q; invariants: deterministic, out of any agent's reach, and applied over EVERY registered trial.

from __future__ import annotations


def dsr_pvalue(deflated_sharpe_prob: float) -> float:
    """Turn a Deflated-Sharpe probability P(SR>0) into a one-sided p-value for the null 'no edge'."""
    return max(0.0, min(1.0, 1.0 - deflated_sharpe_prob))


def benjamini_hochberg(pvalues: list[float], q: float = 0.10) -> list[bool]:
    """Reject mask aligned to the input order: True = discovery survives FDR control at level q.

    Backed by statsmodels' canonical `multipletests(method='fdr_bh')` step-up procedure. This is
    byte-identical to the prior hand-rolled BH across the whole p-value space — including ties at the cutoff —
    so the pre-registered q=0.10 gate is unchanged (parity pinned in tests/test_fdr_parity.py). The
    statsmodels import is local so the lean engine boot path never pays for scipy/statsmodels unless FDR is
    actually evaluated. Empty input ⇒ empty mask (statsmodels rejects a zero-length array)."""
    if not pvalues:
        return []
    from statsmodels.stats.multitest import multipletests

    reject, *_ = multipletests(pvalues, alpha=q, method="fdr_bh")
    return [bool(r) for r in reject]


def bh_threshold(pvalues: list[float], q: float = 0.10) -> float:
    """The Benjamini-Hochberg cutoff: the largest p-value the FDR step-up rejects at level q (= p_(k*)), or
    0.0 if nothing survives — so a candidate is significant iff its p-value <= this threshold."""
    mask = benjamini_hochberg(pvalues, q)
    return max((p for p, ok in zip(pvalues, mask, strict=True) if ok), default=0.0)


def survives_fdr(candidate_pvalue: float, all_pvalues: list[float], q: float = 0.10) -> bool:
    """Does one candidate clear BH-FDR within the full set of registered p-values? `all_pvalues` must
    already include the candidate's own p-value."""
    return candidate_pvalue <= bh_threshold(all_pvalues, q)
