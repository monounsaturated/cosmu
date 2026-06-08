# The Mind KNOWS panel (analysts._latest_values) used to JOIN+GROUP-BY over the ~17M-row alt_data table on
# every /mind read to get the latest VALUE per metric — the same full-scan perf trap fixed for /intelligence
# and /scores. It now reads the value off the alt_data_provider_summary rollup, which carries the value of the
# newest-available row per (provider, metric), maintained INCREMENTALLY on ingest (PIT: newest available_at
# wins). OFFLINE only: seed a sqlite store via the real ingest path, assert the value comes off the summary,
# assert the newest available_at wins (not the largest value, not insertion order), and assert honest-empty.

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cosmu.config.settings import Settings
from cosmu.data.providers._types import AltDataPoint
from cosmu.data.providers.store import PgAltDataStore
from cosmu.ingest.alt_summary import latest_value_per_metric
from cosmu.mind.analysts import _latest_values
from cosmu.knowledge.store import Store


def _store(tmp_path) -> Store:
    store = Store(Settings(database_url=f"sqlite:///{tmp_path}/latest_value.sqlite3", openrouter_api_key=None))
    store.migrate()
    return store


def test_honest_empty_when_no_summary(tmp_path):
    """A fresh store has no summary rows → latest_value_per_metric and _latest_values both return {} (the Mind
    panel abstains), never a fabricated value."""
    store = _store(tmp_path)
    assert latest_value_per_metric(store) == {}
    assert _latest_values(store) == {}


def test_latest_value_comes_off_summary(tmp_path):
    """An ingest batch carries its newest-available value into the summary; the Mind reads it from there."""
    store = _store(tmp_path)
    pg = PgAltDataStore(store)
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    pg.append("alternative.me", "MARKET", "fear_greed", [
        AltDataPoint(ts=t0, available_at=t0, value=40.0),
        AltDataPoint(ts=t0 + timedelta(days=1), available_at=t0 + timedelta(days=1), value=55.0),
    ])
    vals = _latest_values(store)
    assert "fear_greed" in vals
    value, available_at = vals["fear_greed"]
    assert value == 55.0  # the value at the NEWEST available_at, not the first/largest by accident
    assert available_at == (t0 + timedelta(days=1)).isoformat()


def test_newest_available_at_wins_across_batches(tmp_path):
    """PIT correctness: a later batch with a newer available_at overrides latest_value; a backfill of OLDER
    rows (older available_at, even with a bigger value) must NOT override the newer one."""
    store = _store(tmp_path)
    pg = PgAltDataStore(store)
    t0 = datetime(2026, 6, 1, tzinfo=UTC)

    pg.append("provider_x", "MARKET", "metric_a", [AltDataPoint(ts=t0, available_at=t0, value=10.0)])
    assert _latest_values(store)["metric_a"][0] == 10.0

    # newer available_at → wins
    t1 = t0 + timedelta(days=2)
    pg.append("provider_x", "MARKET", "metric_a", [AltDataPoint(ts=t1, available_at=t1, value=20.0)])
    assert _latest_values(store)["metric_a"][0] == 20.0

    # a late backfill of an OLDER row with a BIGGER value must NOT clobber the newer value
    t_old = t0 - timedelta(days=5)
    pg.append("provider_x", "MARKET", "metric_a", [AltDataPoint(ts=t_old, available_at=t_old, value=999.0)])
    assert _latest_values(store)["metric_a"][0] == 20.0


def test_newest_provider_wins_per_metric(tmp_path):
    """When two providers write the same metric, the Mind takes the value from the one with the newest
    available_at (PIT), not an arbitrary one."""
    store = _store(tmp_path)
    pg = PgAltDataStore(store)
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    pg.append("provider_old", "MARKET", "shared_metric", [AltDataPoint(ts=t0, available_at=t0, value=1.0)])
    t1 = t0 + timedelta(days=3)
    pg.append("provider_new", "MARKET", "shared_metric", [AltDataPoint(ts=t1, available_at=t1, value=2.0)])
    assert _latest_values(store)["shared_metric"] == (2.0, t1.isoformat())
