# intent: purged + embargoed combinatorial cross-validation (CPCV, López de Prado) so fold splits don't leak;
# inputs: sample size, group/test counts, label horizon; outputs: (train_idx, test_idx) splits with purge+embargo;
# invariants: a test observation's label window is purged from train, and an embargo follows each test block —
# this is the only fold structure the gate trusts (no single in-sample fit, walk-forward only).

from __future__ import annotations

import math
from itertools import combinations


def embargo_size(n_obs: int, *, embargo_pct: float = 0.01, label_horizon: int = 1, min_embargo: int = 5) -> int:
    """Embargo length = 1% of the sample, but never less than the label horizon or `min_embargo` bars."""
    return max(math.ceil(embargo_pct * n_obs), label_horizon, min_embargo)


def purged_embargo_splits(
    n_obs: int,
    *,
    n_groups: int = 6,
    n_test_groups: int = 2,
    label_horizon: int = 1,
    embargo_pct: float = 0.01,
) -> list[tuple[list[int], list[int]]]:
    """Combinatorial purged CV: split [0, n) into `n_groups` contiguous blocks, take every choice of
    `n_test_groups` as the test set, and build the train set as everything else minus (a) any observation
    whose label window [t, t+horizon] overlaps a test observation (purge) and (b) `embargo` observations
    immediately after each test block (embargo). Returns C(n_groups, n_test_groups) splits.
    """
    if n_obs < n_groups or n_groups < 2 or not (1 <= n_test_groups < n_groups):
        return []
    emb = embargo_size(n_obs, embargo_pct=embargo_pct, label_horizon=label_horizon)

    # contiguous group boundaries
    bounds: list[tuple[int, int]] = []
    size = n_obs / n_groups
    for g in range(n_groups):
        lo = int(round(g * size))
        hi = int(round((g + 1) * size))
        bounds.append((lo, min(hi, n_obs)))

    splits: list[tuple[list[int], list[int]]] = []
    for test_groups in combinations(range(n_groups), n_test_groups):
        test_idx: list[int] = []
        for g in test_groups:
            lo, hi = bounds[g]
            test_idx.extend(range(lo, hi))
        test_set = set(test_idx)

        # forbidden = test ∪ label-window-around-test ∪ embargo-after-each-test-block
        forbidden = set(test_set)
        for t in test_idx:
            for h in range(label_horizon + 1):          # purge: label window [t, t+horizon]
                forbidden.add(t - h)                     # train obs whose label reaches into test
        for g in test_groups:                            # embargo after each test block
            _, hi = bounds[g]
            forbidden.update(range(hi, min(hi + emb, n_obs)))

        train_idx = [i for i in range(n_obs) if i not in forbidden]
        if train_idx and test_idx:
            splits.append((train_idx, sorted(test_idx)))
    return splits
