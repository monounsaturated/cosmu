# Parity: the scipy.stats.spearmanr-backed `_spearman` (master/scorer) must reproduce the prior bespoke
# Pearson-on-average-ranks implementation — same value (to floating-point), same None contract (constant
# input / too-short / mismatched length). This metric is ADVISORY (it feeds rank_consistency, never a gate
# pass/fail), so floating-point identity to ~1e-12 is the bar, not bit-equality; the None handling is exact.
# The reference below IS the old bespoke algorithm, frozen here as the oracle.

from __future__ import annotations

import math
import random
from statistics import fmean

import pytest

from cosmu.master.scorer import _spearman

# --- frozen reference: the prior bespoke Spearman (verbatim) ------------------------------------------------

def _ref_rank(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _ref_spearman(a: list[float], b: list[float]) -> float | None:
    if len(a) < 2 or len(a) != len(b):
        return None
    ra, rb = _ref_rank(a), _ref_rank(b)
    mean_a, mean_b = fmean(ra), fmean(rb)
    cov = sum((x - mean_a) * (y - mean_b) for x, y in zip(ra, rb, strict=True))
    va = sum((x - mean_a) ** 2 for x in ra)
    vb = sum((y - mean_b) ** 2 for y in rb)
    if va <= 0 or vb <= 0:
        return None
    return cov / math.sqrt(va * vb)


# --- None contract (degenerate inputs) ----------------------------------------------------------------------

def test_none_contract_matches():
    cases = [
        ([], []),
        ([1.0], [2.0]),                       # fewer than 2 points
        ([1.0, 2.0], [3.0]),                  # mismatched lengths
        ([5.0, 5.0, 5.0], [1.0, 2.0, 3.0]),   # constant a -> undefined ranks
        ([1.0, 2.0, 3.0], [7.0, 7.0, 7.0]),   # constant b -> undefined ranks
    ]
    for a, b in cases:
        assert (_spearman(a, b) is None) == (_ref_spearman(a, b) is None), (a, b)
        assert _spearman(a, b) is None, (a, b)


# --- known closed-form values -------------------------------------------------------------------------------

def test_perfect_monotone_and_anti_monotone():
    xs = [0.1, 0.4, 0.2, 0.9, 0.5]
    assert _spearman(xs, xs) == pytest.approx(1.0, abs=1e-12)
    assert _spearman(xs, [-v for v in xs]) == pytest.approx(-1.0, abs=1e-12)


def test_tied_ranks_match_reference():
    a = [1.0, 1.0, 2.0, 3.0, 3.0, 4.0]
    b = [2.0, 1.0, 2.0, 5.0, 4.0, 4.0]
    assert _spearman(a, b) == pytest.approx(_ref_spearman(a, b), abs=1e-12)


# --- fuzz parity (value + None) -----------------------------------------------------------------------------

def test_fuzz_value_parity():
    rng = random.Random(20240617)
    max_diff = 0.0
    for _ in range(5000):
        n = rng.randint(2, 40)
        a = [round(rng.random(), rng.choice([2, 6])) for _ in range(n)]
        b = [round(rng.random(), rng.choice([2, 6])) for _ in range(n)]
        if rng.random() < 0.15:  # exercise the constant-input -> None branch
            a = [a[0]] * n
        new, ref = _spearman(a, b), _ref_spearman(a, b)
        assert (new is None) == (ref is None), (a, b)
        if new is not None and ref is not None:
            max_diff = max(max_diff, abs(new - ref))
    assert max_diff < 1e-12, max_diff
