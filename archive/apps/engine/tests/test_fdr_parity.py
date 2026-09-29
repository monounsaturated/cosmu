# BYTE-FOR-BYTE parity: the statsmodels-backed Benjamini-Hochberg (master/fdr) must reproduce the prior
# hand-rolled BH EXACTLY — same reject mask, same cutoff, same survives_fdr verdict — across the whole
# p-value space at the pre-registered q=0.10 (and other q's), so swapping the implementation cannot move the
# Gate by a single bit. The reference below IS the old hand-rolled algorithm, frozen here as the oracle.

from __future__ import annotations

import random

from cosmu.master.fdr import benjamini_hochberg, bh_threshold, survives_fdr

# --- frozen reference: the prior hand-rolled BH-FDR (verbatim) ---------------------------------------------

def _ref_bh_threshold(pvalues: list[float], q: float = 0.10) -> float:
    m = len(pvalues)
    if m == 0:
        return 0.0
    ordered = sorted(pvalues)
    threshold = 0.0
    for k, p in enumerate(ordered, start=1):
        if p <= (k / m) * q:
            threshold = p  # keep the largest passing p-value
    return threshold


def _ref_bh(pvalues: list[float], q: float = 0.10) -> list[bool]:
    cutoff = _ref_bh_threshold(pvalues, q)
    return [p <= cutoff for p in pvalues]


def _ref_survives(candidate: float, all_pvalues: list[float], q: float = 0.10) -> bool:
    return candidate <= _ref_bh_threshold(all_pvalues, q)


# --- hand-picked edge cases (ties at the cutoff, all-noise, single, boundary) -------------------------------

_EDGE_CASES = [
    [],
    [0.05],
    [0.9, 0.95],
    [0.001, 0.002, 0.5, 0.6, 0.9],
    [0.4, 0.6, 0.8, 0.95],
    [0.01, 0.05, 0.05],            # tie straddling the cutoff
    [0.05, 0.05, 0.05, 0.05],      # all identical
    [0.0, 0.0, 1.0, 1.0],          # exact 0/1 boundaries
    [0.10, 0.10],                  # equal to q
    [0.02, 0.02, 0.04, 0.04, 0.9],
]


def test_edge_cases_byte_identical_at_q010():
    for pvals in _EDGE_CASES:
        assert benjamini_hochberg(pvals, q=0.10) == _ref_bh(pvals, q=0.10), pvals
        assert bh_threshold(pvals, q=0.10) == _ref_bh_threshold(pvals, q=0.10), pvals


def test_empty_input_is_empty_mask():
    assert benjamini_hochberg([], q=0.10) == []
    assert bh_threshold([], q=0.10) == 0.0


def test_survives_fdr_byte_identical():
    pvals = [0.001, 0.01, 0.04, 0.2, 0.5, 0.8]
    for cand in pvals + [0.039, 0.041, 0.10]:
        assert survives_fdr(cand, pvals, q=0.10) == _ref_survives(cand, pvals, q=0.10), cand


def test_fuzz_byte_identical_at_q010():
    # The headline guarantee: exact equality at the existing q=0.10 over thousands of random cohorts,
    # deliberately seeded with ties (the one place a naive BH can diverge).
    rng = random.Random(20240617)
    for _ in range(5000):
        m = rng.randint(1, 60)
        precision = rng.choice([2, 3, 6])
        pvals = [round(rng.random(), precision) for _ in range(m)]
        if m > 2 and rng.random() < 0.5:  # inject ties
            dup = rng.choice(pvals)
            for _ in range(rng.randint(1, 4)):
                pvals[rng.randrange(m)] = dup
        assert benjamini_hochberg(pvals, q=0.10) == _ref_bh(pvals, q=0.10), pvals
        assert bh_threshold(pvals, q=0.10) == _ref_bh_threshold(pvals, q=0.10), pvals


def test_fuzz_byte_identical_other_q():
    # Parity is not special to 0.10 — it holds across the whole q dial.
    rng = random.Random(99)
    for q in (0.01, 0.05, 0.20, 0.50):
        for _ in range(1000):
            m = rng.randint(1, 40)
            pvals = [round(rng.random(), rng.choice([2, 6])) for _ in range(m)]
            assert benjamini_hochberg(pvals, q=q) == _ref_bh(pvals, q=q), (q, pvals)
