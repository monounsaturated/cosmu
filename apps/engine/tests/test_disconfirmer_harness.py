"""The reusable disconfirmer harness (item 2) — proven on synthetic positive + negative controls.

A disconfirmer is only useful if it CAN tell a real signal from an artefact. So every null here is exercised
both ways: it must let a genuine edge through AND flag the spurious / memorized one. If a future change makes
a disconfirmer always-pass (or always-fail), one of these controls breaks — that is the point.

  - shuffle_null              : real timing edge SURVIVES (IC outside the shuffled band); noise does NOT.
  - symbol_anonymization_null : within-symbol timing edge SURVIVES masking; a memorized per-symbol prior dies.

All offline + deterministic (string-seeded RNG, matching the repo's fixture style).
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.data.market import Bar
from cosmu.data.providers._types import AltDataPoint
from cosmu.research.disconfirmers import (
    pit_ic,
    shuffle_null,
    symbol_anonymization_null,
)

_T0 = datetime(2024, 1, 1, tzinfo=UTC)


def _build(feature: list[float], step_ret: list[float]) -> tuple[list[AltDataPoint], list[Bar]]:
    """Build a (feature points, bars) pair where the feature value at bar t is `feature[t]` (stamped PIT at the
    bar's close) and the realized return from bar t to t+1 is `step_ret[t]`. So forward_returns(horizon=1)
    pairs feature[t] with step_ret[t] — exactly the relationship the controls below dial in or break."""
    n = len(feature)
    assert len(step_ret) == n - 1
    closes = [100.0]
    for r in step_ret:
        closes.append(closes[-1] * (1.0 + r))
    bars = []
    pts = []
    for t in range(n):
        ts = _T0 + timedelta(days=t)
        px = Decimal(str(round(closes[t], 6)))
        bars.append(Bar(ts=ts, open=px, high=px, low=px, close=px, volume=Decimal(1000)))
        pts.append(AltDataPoint(ts=ts, available_at=ts, value=feature[t]))
    return pts, bars


# --------------------------------------------------------------------------- shuffle null


def test_shuffle_null_real_timing_edge_survives():
    """A feature that genuinely predicts the next return: real IC sits OUTSIDE the shuffled band (survives)."""
    rng = random.Random("shuffle-pos")
    n = 240
    feature = [rng.gauss(0, 1) for _ in range(n)]
    # step_ret[t] is driven by feature[t] (strong, with noise) — a real timing relationship.
    step_ret = [0.02 * feature[t] + 0.005 * rng.gauss(0, 1) for t in range(n - 1)]
    pts, bars = _build(feature, step_ret)

    res = shuffle_null(pts, bars, horizon=1, trials=200, seed=1)
    assert abs(res.real_ic) > 0.3, f"control too weak: real_ic={res.real_ic}"
    assert res.survives, f"a real timing edge was flagged as artefact: p={res.p_value}"
    assert res.collapsed, "the shuffled ICs did not collapse toward 0 relative to the real IC"
    assert res.null_mean_abs < abs(res.real_ic)


def test_shuffle_null_pure_noise_does_not_survive():
    """A feature independent of returns: real IC sits INSIDE the shuffled band (does NOT survive) — the
    BlindTrade collapse. The harness must NOT bless noise as a signal."""
    rng = random.Random("shuffle-neg")
    n = 240
    feature = [rng.gauss(0, 1) for _ in range(n)]
    step_ret = [0.01 * rng.gauss(0, 1) for _ in range(n - 1)]  # returns independent of the feature
    pts, bars = _build(feature, step_ret)

    res = shuffle_null(pts, bars, horizon=1, trials=200, seed=2)
    assert not res.survives, f"pure noise was blessed as a signal: real_ic={res.real_ic} p={res.p_value}"
    assert res.p_value > 0.05


def test_shuffle_null_is_deterministic():
    """Same inputs + seed → identical verdict (a disconfirmer must be reproducible to be a gate)."""
    rng = random.Random("shuffle-det")
    feature = [rng.gauss(0, 1) for _ in range(120)]
    step_ret = [0.02 * feature[t] + 0.004 * rng.gauss(0, 1) for t in range(119)]
    pts, bars = _build(feature, step_ret)
    a = shuffle_null(pts, bars, horizon=1, trials=100, seed=7)
    b = shuffle_null(pts, bars, horizon=1, trials=100, seed=7)
    assert (a.real_ic, a.p_value, a.survives) == (b.real_ic, b.p_value, b.survives)


# --------------------------------------------------------------------------- symbol-anonymization null


def test_symbol_anonymization_real_within_symbol_edge_survives():
    """The SAME within-symbol timing rule on every symbol: pooled IC and within-symbol IC agree → the edge is
    transferable, NOT a memorized per-symbol prior. Survives ticker masking."""
    series: dict[str, list[AltDataPoint]] = {}
    bars: dict[str, list[Bar]] = {}
    for sym in ("AAA", "BBB", "CCC", "DDD"):
        rng = random.Random(f"anon-pos-{sym}")
        n = 160
        feature = [rng.gauss(0, 1) for _ in range(n)]
        step_ret = [0.02 * feature[t] + 0.004 * rng.gauss(0, 1) for t in range(n - 1)]
        pts, bb = _build(feature, step_ret)
        series[sym] = pts
        bars[sym] = bb

    res = symbol_anonymization_null(series, bars, horizon=1)
    assert abs(res.pooled_ic) > 0.2
    assert not res.memorized, f"a transferable edge was flagged memorized: within={res.within_ic} pooled={res.pooled_ic}"
    assert res.survives
    assert res.identity_share < 0.5  # most of the IC is real within-symbol timing, not symbol identity


def test_symbol_anonymization_memorized_prior_dies():
    """A feature that is CONSTANT within each symbol and whose level ranks with that symbol's drift: pooled IC
    is high (cross-sectional level), within-symbol IC ~ 0. The edge is a memorized per-symbol prior — it dies
    when the ticker is masked (demeaned). The harness MUST flag it."""
    series: dict[str, list[AltDataPoint]] = {}
    bars: dict[str, list[Bar]] = {}
    # Each symbol gets a constant feature == its drift rank; higher feature ⇒ higher steady drift.
    for level in (-2.0, -1.0, 1.0, 2.0):
        sym = f"SYM{level}"
        rng = random.Random(f"anon-mem-{sym}")
        n = 160
        feature = [level] * n  # CONSTANT within the symbol — pure identity, zero within-symbol variation
        drift = 0.01 * level   # the symbol's steady drift, monotone in its (constant) feature level
        step_ret = [drift + 0.003 * rng.gauss(0, 1) for _ in range(n - 1)]
        pts, bb = _build(feature, step_ret)
        series[sym] = pts
        bars[sym] = bb

    res = symbol_anonymization_null(series, bars, horizon=1)
    assert abs(res.pooled_ic) > 0.1, f"control too weak: pooled_ic={res.pooled_ic}"
    assert res.memorized, f"a memorized per-symbol prior survived masking: within={res.within_ic} pooled={res.pooled_ic}"
    assert not res.survives
    assert res.identity_share > 0.8  # almost all of the IC is symbol identity


def test_pit_ic_matches_correlation_scan_semantics():
    """pit_ic must align the feature point-in-time and score the strictly-future return — a quick sanity that
    the harness reuses the canonical IC, not a private re-roll."""
    rng = random.Random("pit-ic")
    feature = [rng.gauss(0, 1) for _ in range(120)]
    step_ret = [0.02 * feature[t] + 0.004 * rng.gauss(0, 1) for t in range(119)]
    pts, bars = _build(feature, step_ret)
    ic, n = pit_ic(pts, bars, horizon=1)
    assert n > 100
    assert ic > 0.3
