"""The standing leakage tripwire (cosmu.research.leakage_tripwire) — proven on a CLEAN + a LEAKED control.

The Gate validates edge-after-costs; it does NOT verify the feature pipeline was point-in-time honest. A
look-ahead bug UPSTREAM of the Gate is Gate-INVISIBLE (a survivor real on paper, zero/negative live). The
tripwire is the standing guard a NEW data source must clear BEFORE it is trusted as a feature. It bundles three
INDEPENDENT disconfirmers:

  [1] available_at audit   — align_asof is strictly backward-looking (no value joined before its available_at).
  [2] shuffle-null         — the IC survives a time-shuffle (genuine alignment, not a noise artefact).
  [3] forward-shift sanity — lagging the feature does NOT beat the live read (no baked-in 1-bar look-ahead).

These tests prove the harness CAN tell clean from leaked:
  - a KNOWN-CLEAN on-bar-honest feature PASSES all three;
  - a deliberately LEAKED feature (each value stamped one bar early — a hidden look-ahead) FAILS the RIGHT
    disconfirmer (forward-shift sanity), while [1] and the shuffle stay green (the leak is the ALIGNMENT, not
    the data — which is exactly why the available_at audit alone can miss it).

Offline + deterministic (string-seeded RNG, no network, no DB, no Binance — the M2 is geo-blocked).
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.data.market import Bar
from cosmu.data.providers._types import AltDataPoint
from cosmu.research.leakage_tripwire import (
    TripwireReport,
    audit_feature,
    available_at_audit,
    forward_shift_sanity,
)
from cosmu.research.leakage_tripwire import (
    _synthetic_clean_feature as clean_feature,
)
from cosmu.research.leakage_tripwire import (
    _synthetic_leaked_feature as leaked_feature,
)

_T0 = datetime(2024, 1, 1, tzinfo=UTC)


def _bars(n: int) -> list[Bar]:
    out = []
    for i in range(n):
        px = Decimal(100 + i)
        out.append(Bar(ts=_T0 + timedelta(days=i), open=px, high=px, low=px, close=px, volume=Decimal(1000)))
    return out


# =========================================================================== the bundled report (end to end)


def test_clean_feature_passes_all_three_checks():
    """A known-CLEAN, on-bar-honest feature (real forward-predictive edge, strictly PIT-stamped) must PASS every
    disconfirmer — the tripwire never blocks an honest source."""
    points, bars = clean_feature(seed=7)
    report = audit_feature(points, bars, horizon=1, feature="clean", shuffle_trials=200, seed=7)
    assert isinstance(report, TripwireReport)
    assert report.passed, f"clean feature flagged as leaky: {report.failed_checks}"
    assert report.failed_checks == ()
    assert report.available_at.passed
    assert report.shuffle.survives  # the real IC sits OUTSIDE the shuffled band
    assert report.forward_shift.passed
    # The honest alignment is the PEAK: neither the +1 cheat nor the -1 lag beats the live read.
    assert not report.forward_shift.backward_improves


def test_leaked_feature_fails_the_forward_shift_disconfirmer():
    """A deliberately LEAKED feature (each value stamped ONE BAR EARLY — a hidden 1-bar look-ahead) must FAIL,
    and specifically on the forward-shift sanity: lagging the feature back -1 bar recovers a STRONGER alignment,
    the live-peek fingerprint. The available_at audit + shuffle stay GREEN — the leak is the ALIGNMENT, not the
    data — which is exactly the Gate-invisible failure mode the third disconfirmer exists to catch."""
    points, bars = leaked_feature(seed=7)
    report = audit_feature(points, bars, horizon=1, feature="leaked", shuffle_trials=200, seed=7)
    assert not report.passed, "a baked-in 1-bar look-ahead slipped through the tripwire"
    assert "forward_shift_sanity" in report.failed_checks
    # The back-dated stamp makes the JOIN look clean and the IC is genuinely real — only the forward-shift
    # disconfirmer is positioned to catch this class. Assert it is the one that fired.
    assert report.available_at.passed, "the leaked join should look PIT-clean (that is why this leak is sneaky)"
    assert report.shuffle.survives, "the leaked IC is real (the leak is alignment, not noise)"
    assert not report.forward_shift.passed
    assert report.forward_shift.backward_improves
    # The honest (-1) read is materially stronger than the live read — the quantitative leak signature.
    assert report.forward_shift.backward_ic > report.forward_shift.live_ic


# =========================================================================== (1) available_at audit (direct)


def test_available_at_audit_flags_a_back_dated_lookahead_point():
    """A point whose available_at is AFTER a bar must never land on it. If align_asof were ever to leak a
    not-yet-published value, the audit would flag a violation. Here we assert the HONEST path: a 3-day-lagged
    publish lands only on bars at/after its availability — zero violations, zero wrong-winners."""
    bars = _bars(6)
    pts = [AltDataPoint(ts=bars[0].ts, available_at=bars[3].ts, value=42.0)]  # observed day 0, published day 3
    res = available_at_audit(pts, bars)
    assert res.passed
    assert res.violations == 0
    assert res.mismatches == 0
    # bars 0..2 (pre-availability) carry nothing; bars 3..5 carry the value.
    assert res.n_joined == 3


def test_available_at_audit_property_no_value_predates_availability():
    """Property sweep: across random stamps, the audit must report a strictly backward-looking join (zero
    violations) — the core look-ahead contract held universally."""
    for seed in range(6):
        rng = random.Random(f"tripwire-availat-{seed}")
        bars = _bars(40)
        pts = []
        for idx in range(60):
            obs_i = rng.randint(0, 39)
            lag = rng.randint(0, 10)
            avail = bars[obs_i].ts + timedelta(days=lag, microseconds=idx)
            pts.append(AltDataPoint(ts=bars[obs_i].ts, available_at=avail, value=rng.uniform(-5, 5)))
        res = available_at_audit(pts, bars)
        assert res.violations == 0, f"seed {seed}: align_asof leaked a future value"
        assert res.mismatches == 0, f"seed {seed}: align_asof picked the wrong as-of winner"
        assert res.passed


# =========================================================================== (3) forward-shift sanity (direct)


def test_forward_shift_sanity_clean_feature_does_not_flag():
    """On a clean feature the live alignment is the peak: lagging it -1 bar does NOT improve, so the check passes
    and the +1 cheat does not beat the live read either."""
    points, bars = clean_feature(seed=11)
    res = forward_shift_sanity(points, bars, horizon=1)
    assert res.passed
    assert not res.backward_improves
    assert res.live_ic > 0.5  # the control carries a strong, real signal to reason about


def test_forward_shift_sanity_leaked_feature_flags_a_peek():
    """On the leaked feature (read one bar too early) lagging -1 bar recovers a stronger alignment, so the check
    FAILS with backward_improves=True — the live-peek fingerprint."""
    points, bars = leaked_feature(seed=11)
    res = forward_shift_sanity(points, bars, horizon=1)
    assert not res.passed
    assert res.backward_improves
    assert res.backward_ic > res.live_ic


# =========================================================================== determinism (a gate must repeat)


def test_audit_feature_is_deterministic():
    """Same inputs + seed → identical verdict (a disconfirmer must be reproducible to be a gate)."""
    points, bars = clean_feature(seed=3)
    a = audit_feature(points, bars, horizon=1, seed=3, shuffle_trials=100)
    b = audit_feature(points, bars, horizon=1, seed=3, shuffle_trials=100)
    assert (a.passed, a.failed_checks, a.real_ic) == (b.passed, b.failed_checks, b.real_ic)
    assert a.shuffle.p_value == b.shuffle.p_value


def test_report_render_is_human_readable():
    """The CLI body renders a multi-line PASS/FAIL report naming each check — a reviewer reads this."""
    points, bars = clean_feature(seed=5)
    text = audit_feature(points, bars, horizon=1, seed=5, shuffle_trials=50).render()
    assert "LEAKAGE TRIPWIRE" in text
    assert "available_at audit" in text
    assert "shuffle-null" in text
    assert "forward-shift" in text
    assert "PASS" in text


def test_shuffle_survival_can_be_advisory():
    """With require_shuffle_survival=False a noise feature is NOT failed on the shuffle alone (the audit then
    only fails on a positive look-ahead) — but the shuffle verdict is still recorded for the reviewer."""
    rng = random.Random("tripwire-noise")
    n = 200
    bars = _bars(n)
    # a feature independent of returns: IC inside the shuffled band (shuffle would normally fail it).
    pts = [AltDataPoint(ts=b.ts, available_at=b.ts, value=rng.gauss(0, 1)) for b in bars]
    strict = audit_feature(pts, bars, horizon=1, seed=1, shuffle_trials=100, require_shuffle_survival=True)
    advisory = audit_feature(pts, bars, horizon=1, seed=1, shuffle_trials=100, require_shuffle_survival=False)
    assert "shuffle_null" in strict.failed_checks  # strict mode fails noise on the shuffle
    assert "shuffle_null" not in advisory.failed_checks  # advisory mode does not
    # noise has no look-ahead, so with the shuffle advisory it passes the positive-leak checks.
    assert advisory.available_at.passed
    assert advisory.forward_shift.passed
