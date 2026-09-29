# The 15-min ingest cron used to re-append a full provider window every pass with no dedup, so alt_data accreted
# exact (provider, symbol, metric, ts, available_at) photocopies (~96 copies/day/series). The uq_alt_data_pit
# unique index + an ON CONFLICT DO NOTHING append make re-appending an identical window a no-op AT THE DB LAYER —
# idempotent, never a raise — while a genuine vendor revision (a DIFFERENT available_at) is still kept as a
# distinct point-in-time row. These are offline SQLite tests; the same index ships in both schema files.

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cosmu.config.settings import Settings
from cosmu.data.providers._types import AltDataPoint
from cosmu.data.providers.store import PgAltDataStore
from cosmu.knowledge.store import Store


def _store(tmp_path) -> Store:
    store = Store(Settings(database_url=f"sqlite:///{tmp_path}/pit.sqlite3", openrouter_api_key=None))
    store.migrate()
    return store


def _count(store: Store) -> int:
    return int(store.row("SELECT count(*) AS n FROM alt_data")["n"])


def _window(n: int) -> list[AltDataPoint]:
    """A deterministic n-day window; ts and available_at are fixed per index so a re-append is byte-identical."""
    base = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        AltDataPoint(ts=base + timedelta(days=i), available_at=base + timedelta(days=i, hours=12), value=1.0 + i)
        for i in range(n)
    ]


def test_reappending_identical_window_writes_zero_rows_and_never_raises(tmp_path):
    """The exact scenario the pre-dedup cron created: append the same window twice. The unique index would RAISE
    on a plain insert; ON CONFLICT DO NOTHING makes the second pass a no-op with zero new rows."""
    store = _store(tmp_path)
    alt = PgAltDataStore(store)
    points = _window(10)
    alt.append("binance", "BTCUSDT", "funding_rate", points)
    assert _count(store) == 10
    alt.append("binance", "BTCUSDT", "funding_rate", points)  # must not raise
    assert _count(store) == 10  # zero new rows


def test_partial_overlap_inserts_only_the_new_points(tmp_path):
    """A later window that overlaps the stored one and adds fresh days lands ONLY the new rows."""
    store = _store(tmp_path)
    alt = PgAltDataStore(store)
    alt.append("binance", "BTCUSDT", "funding_rate", _window(10))
    assert _count(store) == 10
    alt.append("binance", "BTCUSDT", "funding_rate", _window(15))  # first 10 collide, 5 are new
    assert _count(store) == 15


def test_real_revision_same_ts_different_available_at_is_kept(tmp_path):
    """A genuine vendor revision shares the observation ts but we learned the new value LATER → a different
    available_at. It is NOT a photocopy and must survive as a distinct point-in-time row (zero information loss)."""
    store = _store(tmp_path)
    alt = PgAltDataStore(store)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    first = [AltDataPoint(ts=base, available_at=base + timedelta(hours=12), value=1.0)]
    revised = [AltDataPoint(ts=base, available_at=base + timedelta(days=1, hours=12), value=2.0)]
    alt.append("binance", "BTCUSDT", "funding_rate", first)
    alt.append("binance", "BTCUSDT", "funding_rate", revised)
    assert _count(store) == 2
