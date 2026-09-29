# The /intelligence data-freshness panel and the /scores source-trust freshness used to GROUP BY over the
# ~17M-row alt_data table on EVERY request (a full seq-scan → ~24s/~22s, timing out the SSR fetch). They now
# read a tiny per-(provider, metric) rollup table, alt_data_provider_summary, refreshed INCREMENTALLY by the
# ingest path (an upsert from the just-written rows, never a full re-aggregate). OFFLINE only: seed a sqlite
# store, assert the readers come off the summary, assert ingest updates the summary incrementally, and assert
# honest-empty (no summary → empty answer, never fabricated).

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cosmu.api.intelligence import _data_freshness, compute_intelligence, reset_cache
from cosmu.config.settings import Settings
from cosmu.data.providers._types import AltDataPoint
from cosmu.data.providers.store import PgAltDataStore
from cosmu.ingest.alt_summary import latest_per_metric, latest_per_provider, record_ingest
from cosmu.knowledge.store import Store
from cosmu.mind.source_trust import _latest_per_source


def _store(tmp_path, name="alt_summary") -> Store:
    store = Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3", openrouter_api_key=None))
    store.migrate()
    return store


def _summary_rows(store: Store) -> list[dict]:
    return store.rows(
        "SELECT provider, metric, n_rows, latest_available_at FROM alt_data_provider_summary "
        "ORDER BY provider, metric"
    )


def test_honest_empty_when_no_summary(tmp_path):
    """A fresh store has no summary rows → both readers return empty, never a fabricated freshness row."""
    store = _store(tmp_path)
    assert latest_per_provider(store) == []
    assert latest_per_metric(store, ["fear_greed", "funding_rate"]) == {}
    assert _latest_per_source(store) == {}
    reset_cache()
    assert compute_intelligence(store, use_cache=False)["data_freshness"] == []


def test_ingest_appends_update_summary_incrementally(tmp_path):
    """Each PgAltDataStore.append rolls its just-written batch into the summary: n_rows ACCUMULATES and
    latest_available_at takes the running MAX — an incremental upsert, never a full re-aggregate."""
    store = _store(tmp_path)
    pg = PgAltDataStore(store)
    t0 = datetime(2026, 6, 1, tzinfo=UTC)

    # First batch: 2 fear_greed points (market-wide).
    pg.append("alternative.me", "MARKET", "fear_greed", [
        AltDataPoint(ts=t0, available_at=t0, value=40.0),
        AltDataPoint(ts=t0 + timedelta(days=1), available_at=t0 + timedelta(days=1), value=55.0),
    ])
    rows = _summary_rows(store)
    assert len(rows) == 1
    assert rows[0]["provider"] == "alternative.me" and rows[0]["metric"] == "fear_greed"
    assert rows[0]["n_rows"] == 2
    assert rows[0]["latest_available_at"] == (t0 + timedelta(days=1)).isoformat()

    # Second batch, SAME (provider, metric), newer availability → n_rows accumulates to 3, MAX advances.
    pg.append("alternative.me", "MARKET", "fear_greed", [
        AltDataPoint(ts=t0 + timedelta(days=2), available_at=t0 + timedelta(days=2), value=60.0),
    ])
    rows = _summary_rows(store)
    assert len(rows) == 1  # still one summary row for this (provider, metric)
    assert rows[0]["n_rows"] == 3
    assert rows[0]["latest_available_at"] == (t0 + timedelta(days=2)).isoformat()

    # An OLDER batch must NOT regress latest_available_at, but DOES still add to n_rows.
    pg.append("alternative.me", "MARKET", "fear_greed", [
        AltDataPoint(ts=t0 - timedelta(days=5), available_at=t0 - timedelta(days=5), value=10.0),
    ])
    rows = _summary_rows(store)
    assert rows[0]["n_rows"] == 4
    assert rows[0]["latest_available_at"] == (t0 + timedelta(days=2)).isoformat()  # MAX held

    # A different provider/metric (per-symbol) creates its own summary row.
    pg.append("binance", "BTCUSDT", "funding_rate", [
        AltDataPoint(ts=t0, available_at=t0, value=0.01),
    ])
    pg.append("binance", "ETHUSDT", "funding_rate", [
        AltDataPoint(ts=t0, available_at=t0, value=0.02),
    ])
    rows = {(r["provider"], r["metric"]): r for r in _summary_rows(store)}
    # Two symbols of the SAME (provider, metric) accumulate into ONE summary row (the provider/metric grain).
    assert rows[("binance", "funding_rate")]["n_rows"] == 2


def test_data_freshness_reads_summary_not_a_full_scan(tmp_path):
    """The /intelligence panel aggregates the summary to one row per PROVIDER (SUM n_rows, MAX availability)
    — and matches what a GROUP BY over alt_data would have produced, but off the tiny rollup."""
    store = _store(tmp_path)
    pg = PgAltDataStore(store)
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    # Two metrics under the SAME provider ("fred"), plus a second provider.
    pg.append("fred", "MARKET", "macro_regime", [
        AltDataPoint(ts=t0, available_at=t0, value=1.0),
        AltDataPoint(ts=t0 + timedelta(days=1), available_at=t0 + timedelta(days=1), value=1.1),
    ])
    pg.append("fred", "MARKET", "vix_level", [
        AltDataPoint(ts=t0 + timedelta(days=2), available_at=t0 + timedelta(days=2), value=18.0),
    ])
    pg.append("alternative.me", "MARKET", "fear_greed", [
        AltDataPoint(ts=t0, available_at=t0, value=40.0),
    ])

    fresh = {d["source"]: d for d in _data_freshness(store)}
    # fred: 2 + 1 = 3 points, latest = the vix_level day (day+2).
    assert fresh["fred"]["points"] == 3
    assert fresh["fred"]["last_at"] == (t0 + timedelta(days=2)).isoformat()
    assert fresh["alternative.me"]["points"] == 1
    assert fresh["alternative.me"]["last_at"] == t0.isoformat()


def test_latest_per_source_maps_metric_freshness_to_registry_source(tmp_path):
    """source_trust._latest_per_source reads per-metric freshness from the summary, then maps metric → registry
    source. A registry metric WITH summary data shows its source as fresh; one without stays absent (no data)."""
    store = _store(tmp_path)
    pg = PgAltDataStore(store)
    t0 = datetime(2026, 6, 3, tzinfo=UTC)
    pg.append("alternative.me", "MARKET", "fear_greed", [
        AltDataPoint(ts=t0, available_at=t0, value=50.0),
    ])

    by_source = _latest_per_source(store)
    # fear_greed → registry source "alternative.me"; its freshness reflects the ingested availability.
    assert by_source.get("alternative.me") == t0
    # A source with no ingested metric is simply absent (→ "no data" downstream), never fabricated.
    assert "fred" not in by_source


def test_record_ingest_is_best_effort_and_zero_row_noop(tmp_path):
    """record_ingest never writes a 0-row summary (empty store stays honestly empty) and never raises."""
    store = _store(tmp_path)
    with store.batch() as w:
        record_ingest(w, "fred", "macro_regime", n_rows=0, latest_available_at=None)
    assert _summary_rows(store) == []
    # A None availability is tolerated (still records the count).
    with store.batch() as w:
        record_ingest(w, "fred", "macro_regime", n_rows=2, latest_available_at=None)
    rows = _summary_rows(store)
    assert len(rows) == 1 and rows[0]["n_rows"] == 2 and rows[0]["latest_available_at"] is None
