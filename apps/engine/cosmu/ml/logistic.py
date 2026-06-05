# intent: the shared pure-Python regularized-logistic primitives used by every tabular ML head in cosmu.ml
# (the survival ranker AND the triple-barrier meta-label gate). One implementation, two callers — composing,
# not duplicating. invariants: deterministic (fixed zero init, fixed iteration order, no randomness), offline
# (zero required dependency), and L2-regularized so a thin/correlated design matrix can't blow the weights up.

from __future__ import annotations

import math


def sigmoid(z: float) -> float:
    """Numerically-guarded logistic squashing (clamped exponent so a large |z| can't overflow math.exp)."""
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))


def standardize(rows: list[list[float]]) -> tuple[list[float], list[float]]:
    """Per-feature mean and (non-zero) std so the pure-Python logistic trains stably. Deterministic. A constant
    column gets std 1.0 so standardization is a no-op there instead of dividing by zero."""
    n = len(rows)
    dim = len(rows[0])
    means = [sum(r[j] for r in rows) / n for j in range(dim)]
    stds: list[float] = []
    for j in range(dim):
        var = sum((r[j] - means[j]) ** 2 for r in rows) / n
        stds.append(math.sqrt(var) or 1.0)
    return means, stds


def apply_standardization(vec: list[float], means: list[float], stds: list[float]) -> list[float]:
    """Standardize one feature vector with a fitted (means, stds) — the serve-time mirror of `standardize`."""
    return [(vec[j] - means[j]) / stds[j] for j in range(len(vec))]


def train_logistic(
    rows: list[list[float]], labels: list[int], *, epochs: int = 400, lr: float = 0.1, l2: float = 1e-3
) -> tuple[list[float], float]:
    """Pure-Python deterministic logistic regression (batch gradient descent, L2). Returns (weights, bias).
    Deterministic: fixed init (zeros), fixed iteration order, no randomness — same inputs => same model. `l2`
    is the ridge penalty on the weights (not the bias), the only regularization knob."""
    dim = len(rows[0])
    w = [0.0] * dim
    b = 0.0
    n = len(rows)
    for _ in range(epochs):
        gw = [0.0] * dim
        gb = 0.0
        for x, y in zip(rows, labels, strict=True):
            z = b + sum(w[j] * x[j] for j in range(dim))
            p = sigmoid(z)
            err = p - y
            for j in range(dim):
                gw[j] += err * x[j]
            gb += err
        for j in range(dim):
            w[j] -= lr * (gw[j] / n + l2 * w[j])
        b -= lr * (gb / n)
    return w, b
