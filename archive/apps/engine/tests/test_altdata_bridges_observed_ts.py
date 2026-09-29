# Offline tests for the altdata_bridges._snapshot PIT-honesty fix: when a DataSource carries the reading's
# TRUE observation timestamp (SourceFeature.observed_ts), _snapshot must stamp the AltDataPoint's `ts` with
# that observed time and keep `available_at` distinct (the availability lag) — never collapse the two. When a
# source leaves observed_ts None, _snapshot falls back to available_at (the legacy, backward-compatible shape).

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cosmu.data.sources.altdata_bridges import _snapshot
from cosmu.data.sources.registry import SourceFeature

_NOW = datetime(2025, 1, 2, tzinfo=UTC)
_OBS = datetime(2025, 1, 1, tzinfo=UTC)
_AVAIL = _OBS + timedelta(days=1)  # the +1d availability lag (= _NOW here)


class _FakeSource:
    """A DataSource whose query() returns a fixed SourceFeature (no network)."""

    def __init__(self, feat: SourceFeature | None) -> None:
        self._feat = feat

    def query(self, scope: str, as_of: datetime, *, limit: int = 4096) -> SourceFeature | None:  # noqa: ARG002
        return self._feat


def _feat(*, value, available_at, observed_ts) -> SourceFeature:
    return SourceFeature(
        name="x", scope="MARKET", as_of=_NOW, value=value, available_at=available_at,
        confidence=0.4, transform_version="v1", prior="p", observed_ts=observed_ts,
    )


def test_snapshot_keeps_ts_distinct_from_available_at_when_observed_ts_present():
    src = _FakeSource(_feat(value=42.0, available_at=_AVAIL, observed_ts=_OBS))
    pts = _snapshot(src, "MARKET")
    assert len(pts) == 1
    p = pts[0]
    assert p.value == 42.0
    assert p.ts == _OBS                 # the TRUE observation day
    assert p.available_at == _AVAIL     # the availability lag — kept distinct
    assert p.ts != p.available_at       # the whole point of the fix


def test_snapshot_falls_back_to_available_at_when_no_observed_ts():
    # Legacy / backward-compatible: a source that cannot distinguish obs vs availability leaves observed_ts
    # None, and _snapshot stamps ts = available_at (the old behaviour — never crashes, never look-ahead).
    src = _FakeSource(_feat(value=7.0, available_at=_AVAIL, observed_ts=None))
    pts = _snapshot(src, "MARKET")
    assert len(pts) == 1
    assert pts[0].ts == _AVAIL == pts[0].available_at


def test_snapshot_none_value_is_honest_gap():
    src = _FakeSource(_feat(value=None, available_at=_AVAIL, observed_ts=_OBS))
    assert _snapshot(src, "MARKET") == []


def test_snapshot_none_feature_is_honest_gap():
    assert _snapshot(_FakeSource(None), "MARKET") == []
