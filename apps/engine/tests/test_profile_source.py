# Offline tests for the data-trust audit (ingest/profile_source.py). PURE + deterministic + REVIEW-ONLY: the
# clock is injected, no network, no wall-time. The audit profiles a NEW alt-source (coverage · gaps · staleness ·
# look-ahead · PIT-lag honesty · revision safety) into GO / REVIEW / NO-GO — it only RECOMMENDS, it wires nothing.
# Covers the clean GO, the hard NO-GOs (look-ahead leak, dishonest PIT lag, empty feed), the soft REVIEWs
# (shallow, stale, heavily revised), and the store-backed reader over an AltDataStore.

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cosmu.data.altdata import AltDataPoint, AltDataStore
from cosmu.ingest.profile_source import profile_points, profile_source

_T0 = datetime(2023, 1, 1, tzinfo=UTC)
_NOW = _T0 + timedelta(days=80)

_DAY = 86400.0


def _daily(n: int, *, lag_days: float = 1.0, end: datetime = _NOW - timedelta(days=1)) -> list[AltDataPoint]:
    """n daily points ending at `end`, each available `lag_days` after its observation (point-in-time honest)."""
    start = end - timedelta(days=n - 1)
    return [
        AltDataPoint(ts=start + timedelta(days=i), available_at=start + timedelta(days=i + lag_days), value=float(i))
        for i in range(n)
    ]


def _check(profile, name):
    return next(c for c in profile.checks if c.name == name)


def test_clean_deep_fresh_pit_honest_source_is_go():
    pts = _daily(70, lag_days=1.0)
    p = profile_points(pts, provider="alternative.me", symbol="MARKET", metric="fear_greed",
                       now=_NOW, declared_lag_seconds=_DAY)
    assert p.verdict == "GO"
    assert _check(p, "look_ahead").passed
    assert _check(p, "pit_lag").passed
    assert _check(p, "coverage_depth").passed


def test_lookahead_leak_is_a_hard_no_go():
    good = _daily(70, lag_days=1.0)
    leak = AltDataPoint(ts=_NOW - timedelta(days=2), available_at=_NOW - timedelta(days=4), value=9.0)  # avail < ts
    p = profile_points(good + [leak], provider="x", symbol="MARKET", metric="leaky", now=_NOW)
    assert p.verdict == "NO-GO"
    assert not _check(p, "look_ahead").passed
    assert _check(p, "look_ahead").severity == "hard"


def test_dishonest_pit_lag_is_a_hard_no_go():
    # The feed DECLARES next-day availability but is stamped available at observation time (lag 0) — a backtest
    # would read each value a full day before it was really published. Not a raw leak, but a latent one → NO-GO.
    pts = _daily(70, lag_days=0.0)
    p = profile_points(pts, provider="vendor", symbol="MARKET", metric="too_early",
                       now=_NOW, declared_lag_seconds=_DAY)
    assert p.verdict == "NO-GO"
    assert not _check(p, "pit_lag").passed
    assert _check(p, "pit_lag").severity == "hard"
    assert p.observed_median_lag_seconds == 0.0


def test_no_declared_lag_makes_pit_check_informational():
    pts = _daily(70, lag_days=0.0)
    p = profile_points(pts, provider="vendor", symbol="MARKET", metric="instant", now=_NOW)
    pit = _check(p, "pit_lag")
    assert pit.severity == "info" and pit.passed
    assert p.verdict == "GO"  # availability == observation is legitimate when nothing is declared


def test_shallow_history_is_a_review():
    pts = _daily(20, lag_days=1.0)  # too few rows / too short a span to judge OOS yet
    p = profile_points(pts, provider="vendor", symbol="MARKET", metric="shallow", now=_NOW)
    assert p.verdict == "REVIEW"
    assert not _check(p, "coverage_depth").passed


def test_stale_source_is_a_review():
    pts = _daily(70, lag_days=1.0, end=_NOW - timedelta(days=40))  # last availability ~39d ago → stale
    p = profile_points(pts, provider="vendor", symbol="MARKET", metric="stale", now=_NOW)
    assert p.verdict == "REVIEW"
    assert not _check(p, "staleness").passed


def test_empty_feed_is_a_no_go():
    p = profile_points([], provider="vendor", symbol="MARKET", metric="empty", now=_NOW)
    assert p.verdict == "NO-GO"
    assert "no data" in p.reasons[0]


def test_heavy_revisions_trigger_review():
    base = _daily(70, lag_days=1.0)
    # 20 same-ts restatements (vendor rewrites history) — available later, so not leaks, but a trust caveat.
    revisions = [
        AltDataPoint(ts=b.ts, available_at=b.available_at + timedelta(hours=6), value=b.value + 1.0)
        for b in base[:20]
    ]
    p = profile_points(base + revisions, provider="vendor", symbol="MARKET", metric="revised", now=_NOW)
    assert p.revision_count == 20
    assert p.verdict == "REVIEW"
    assert not _check(p, "revision_safety").passed


def test_to_dict_and_to_text_are_stable_for_tooling():
    pts = _daily(70, lag_days=1.0)
    p = profile_points(pts, provider="alternative.me", symbol="MARKET", metric="fear_greed",
                       now=_NOW, declared_lag_seconds=_DAY)
    d = p.to_dict()
    assert d["verdict"] == "GO"
    assert d["coverage"]["rows"] == 70
    # The six metadata checks are always present; with no bars supplied the behavioral gate reports an INFO
    # 'behavioral_audit' skipped check (visible, never a silent pass), so it appears in the serialized set too.
    assert {c["name"] for c in d["checks"]} == {
        "coverage_depth", "gaps", "staleness", "look_ahead", "pit_lag", "revision_safety", "behavioral_audit"
    }
    behavioral = next(c for c in d["checks"] if c["name"] == "behavioral_audit")
    assert behavioral["severity"] == "info" and "skipped" in behavioral["detail"]
    text = p.to_text()
    assert "DATA-TRUST AUDIT" in text and "VERDICT: GO" in text


def test_store_backed_profile_reads_and_audits(tmp_path):
    store = AltDataStore(tmp_path / "alt")
    store.append("alternative.me", "MARKET", "fear_greed", _daily(70, lag_days=1.0))
    p = profile_source(store, "alternative.me", "MARKET", "fear_greed", now=_NOW, declared_lag_seconds=_DAY)
    assert p.verdict == "GO"
    # A series the store has no rows for is named NO-GO, never silently passed.
    missing = profile_source(store, "vendor", "MARKET", "absent", now=_NOW)
    assert missing.verdict == "NO-GO"
