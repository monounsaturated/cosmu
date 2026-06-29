# Offline tests for the BEHAVIORAL leakage gate folded into the data-trust audit (ingest/profile_source.py).
# The metadata checks (coverage · gaps · staleness · available_at-vs-ts · declared-lag honesty) all reason about
# DECLARED point-in-time stamps. They CANNOT catch a baked-in ALIGNMENT leak: a feature whose metadata looks
# perfectly clean (available_at == ts, deep, fresh, no holes) but whose actual join to bars peeks a bar forward.
# These tests prove the new behavioral path (research.leakage_tripwire.audit_feature, folded in when matched bars
# are supplied) closes that gap: a baked-in forward-peeking source comes back NO-GO even with spotless metadata,
# a genuinely clean PIT source comes back GO, and the gate degrades gracefully (skipped, never silently passed)
# when there aren't enough bars to audit. PURE + deterministic + offline (injected clock, no network, no Binance).

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.data.market import Bar
from cosmu.data.providers._types import AltDataPoint
from cosmu.ingest.profile_source import profile_points

_T0 = datetime(2023, 1, 1, tzinfo=UTC)
_DAY = 86400.0


def _check(profile, name):
    return next((c for c in profile.checks if c.name == name), None)


def _ar1_market(
    n: int = 140, *, seed: int = 7, phi: float = 0.85, beta: float = 0.02
) -> tuple[list[float], list[Bar]]:
    """A SMOOTH (AR(1)) latent feature + a price path whose return t->t+1 is driven by the feature value AT bar t.
    AR(1) persistence makes a 1-bar misalignment DEGRADE (not destroy) the IC — exactly what lets the behavioral
    forward-shift sanity SEE a baked-in too-early read. Mirrors leakage_tripwire's offline market generator."""
    rng = random.Random(f"behavioral-market-{seed}")
    feats: list[float] = []
    x = 0.0
    for _ in range(n):
        x = phi * x + rng.gauss(0, 1)
        feats.append(x)
    closes = [100.0]
    for t in range(n - 1):
        ret = beta * feats[t] + 0.004 * rng.gauss(0, 1)
        closes.append(max(0.01, closes[-1] * (1.0 + ret)))
    bars: list[Bar] = []
    for t in range(n):
        ts = _T0 + timedelta(days=t)
        px = Decimal(str(round(closes[t], 6)))
        bars.append(Bar(ts=ts, open=px, high=px, low=px, close=px, volume=Decimal(1000)))
    return feats, bars


def _now_for(bars: list[Bar]) -> datetime:
    """A clock one day after the last bar so a daily feed reads FRESH (not stale) — isolates the behavioral gate."""
    return bars[-1].ts + timedelta(days=1)


def _clean_source(n: int = 140, *, seed: int = 7) -> tuple[list[AltDataPoint], list[Bar]]:
    """A genuinely clean PIT source: each value stamped available exactly at its observation bar (available_at ==
    ts), with a REAL forward-predictive edge (feature[t] leads return t->t+1). Clean metadata AND clean wiring."""
    feats, bars = _ar1_market(n, seed=seed)
    points = [AltDataPoint(ts=b.ts, available_at=b.ts, value=feats[t]) for t, b in enumerate(bars)]
    return points, bars


def _baked_in_leak_source(n: int = 140, *, seed: int = 7) -> tuple[list[AltDataPoint], list[Bar]]:
    """A baked-in ALIGNMENT leak with SPOTLESS metadata: bar t carries bar t+1's value, back-dated to bar t's
    availability (available_at == ts, no holes, deep, fresh). The metadata checks see nothing wrong — available_at
    is never < ts, there is no declared lag to violate — but the JOIN peeks a bar forward. Because the feature is
    AR(1)-smooth, reading it a bar early stays predictive (a strong but DEGRADED live IC), and lagging it back -1
    recovers the true STRONGER alignment: the forward-shift fingerprint the behavioral audit catches."""
    feats, bars = _ar1_market(n, seed=seed)
    leaked = [AltDataPoint(ts=bars[t].ts, available_at=bars[t].ts, value=feats[t + 1]) for t in range(n - 1)]
    return leaked, bars[: len(leaked)]


def test_baked_in_alignment_leak_is_no_go_via_behavioral_path():
    """The headline gap: clean DECLARED metadata, but the join peeks forward. Metadata checks PASS; the behavioral
    look-ahead check FAILS → NO-GO. This is the exact vibe-coded failure vector the metadata audit alone misses."""
    points, bars = _baked_in_leak_source()
    p = profile_points(points, provider="vendor", symbol="BTCUSDT", metric="leaky_align",
                       now=_now_for(bars), bars=bars)

    # Metadata is spotless — the OLD audit would have blessed this feed.
    assert _check(p, "look_ahead").passed          # no available_at < ts
    assert _check(p, "pit_lag").passed             # no declared lag dishonesty
    assert _check(p, "coverage_depth").passed      # deep + long enough

    # The NEW behavioral gate catches the baked-in peek and forces NO-GO.
    beh = _check(p, "behavioral_lookahead")
    assert beh is not None and not beh.passed and beh.severity == "hard"
    assert p.verdict == "NO-GO"


def test_clean_pit_source_with_bars_is_go():
    """A genuinely honest PIT source with a real edge clears BOTH the metadata checks AND all three behavioral
    disconfirmers → GO. The behavioral gate does not over-reject a clean feed."""
    points, bars = _clean_source()
    p = profile_points(points, provider="vendor", symbol="BTCUSDT", metric="clean_align",
                       now=_now_for(bars), bars=bars)

    beh = _check(p, "behavioral_lookahead")
    assert beh is not None and beh.passed and beh.severity == "hard"
    shuf = _check(p, "behavioral_shuffle")
    assert shuf is not None and shuf.passed
    assert p.verdict == "GO"


def test_behavioral_audit_skipped_without_bars_is_not_silent_pass():
    """Backward compatible: no bars → the behavioral gate is REPORTED as skipped (INFO), the metadata verdict is
    unchanged, and the skip is VISIBLE so a human knows the behavioral audit did not run. It never silently
    passes a source it could not behaviorally audit."""
    points, _bars = _clean_source()
    p = profile_points(points, provider="vendor", symbol="BTCUSDT", metric="no_bars", now=_T0 + timedelta(days=200))
    skipped = _check(p, "behavioral_audit")
    assert skipped is not None and skipped.severity == "info"
    assert "skipped" in skipped.detail
    # No behavioral hard/soft check was emitted, so it cannot have moved the verdict on its own.
    assert _check(p, "behavioral_lookahead") is None


def test_behavioral_audit_skipped_when_overlap_too_thin():
    """Too few joined observations → the disconfirmers are too noisy; the gate degrades to INFO 'skipped' rather
    than guessing a verdict from an unreliable IC."""
    feats, bars = _ar1_market(140)
    points = [AltDataPoint(ts=b.ts, available_at=b.ts, value=feats[t]) for t, b in enumerate(bars)]
    p = profile_points(points, provider="vendor", symbol="BTCUSDT", metric="thin",
                       now=_now_for(bars), bars=bars[:5])  # only ~5 bars overlap
    skipped = _check(p, "behavioral_audit")
    assert skipped is not None and skipped.severity == "info" and "skipped" in skipped.detail
    assert _check(p, "behavioral_lookahead") is None


def test_baked_in_leak_named_in_reasons_and_dict():
    """The NO-GO reason surfaces the behavioral look-ahead so the operator fixes the right surface, and the new
    checks serialize for tooling (to_dict)."""
    points, bars = _baked_in_leak_source()
    p = profile_points(points, provider="vendor", symbol="BTCUSDT", metric="leaky_align",
                       now=_now_for(bars), bars=bars)
    assert p.verdict == "NO-GO"
    assert any("look-ahead" in r.lower() or "forward-shift" in r.lower() for r in p.reasons)
    names = {c["name"] for c in p.to_dict()["checks"]}
    assert "behavioral_lookahead" in names and "behavioral_shuffle" in names
