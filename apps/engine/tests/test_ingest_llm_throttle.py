# The paid-LLM-source throttle in the ingest pass (ingest/run.py::_llm_source_fresh): the Tier-1 15-min cron
# multiplied pass frequency x24 — xAI LiveSearch and llm_index rubric calls must scale with DATA freshness,
# not cron cadence. Free/numeric sources never throttle. Offline + deterministic.

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cosmu.data.altdata import AltDataPoint
from cosmu.ingest.run import _llm_source_fresh


class _Store:
    def __init__(self, points: list[AltDataPoint], *, raises: bool = False) -> None:
        self._points = points
        self._raises = raises
        self.reads = 0

    def read_asof(self, provider, symbol, metric, as_of):  # noqa: ANN001
        self.reads += 1
        if self._raises:
            raise OSError("db down")
        return list(self._points)


def _point(age_minutes: float) -> AltDataPoint:
    ts = datetime.now(UTC) - timedelta(minutes=age_minutes)
    return AltDataPoint(ts=ts, available_at=ts, value=0.5)


def test_fresh_series_skips_the_paid_source():
    assert _llm_source_fresh(_Store([_point(10)]), "xai", "twitter_sentiment", 60) is True


def test_stale_series_runs_the_source():
    assert _llm_source_fresh(_Store([_point(120)]), "xai", "twitter_sentiment", 60) is False


def test_empty_store_runs_the_source():
    assert _llm_source_fresh(_Store([]), "llm_index", "risk_on_off", 60) is False


def test_store_failure_never_blocks_ingest():
    assert _llm_source_fresh(_Store([_point(1)], raises=True), "xai", "twitter_sentiment", 60) is False


def test_zero_interval_disables_the_throttle():
    store = _Store([_point(1)])
    assert _llm_source_fresh(store, "xai", "twitter_sentiment", 0) is False
    assert store.reads == 0  # disabled means no store read at all
