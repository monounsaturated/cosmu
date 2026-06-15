# sync_to_lake mirrors alt_data → the DuckLake lake incrementally: the watermark-absent first run is the full
# backfill, later runs copy only newer rows. Offline: a sqlite "Postgres" source + a local DuckLake (sqlite
# catalog + local data dir). Pins backfill, idempotent re-run, incremental copy, and lake==PG read-back.

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from cosmu.config.settings import Settings
from cosmu.data.providers._types import AltDataPoint
from cosmu.data.providers.store import PgAltDataStore
from cosmu.knowledge.store import Store

duckdb = pytest.importorskip("duckdb")
try:
    _c = duckdb.connect(":memory:")
    _c.execute("INSTALL ducklake; LOAD ducklake;")
    _c.execute("INSTALL sqlite; LOAD sqlite;")
    _c.close()
except Exception:  # noqa: BLE001 — extensions unavailable offline → skip cleanly
    pytest.skip("ducklake/sqlite extension unavailable (offline)", allow_module_level=True)

from cosmu.data.age_out import sync_to_lake  # noqa: E402
from cosmu.data.providers.ducklake_store import DuckLakeAltDataStore  # noqa: E402

_P, _S, _M = "binance", "BTCUSDT", "funding_rate"


def _setup(tmp_path):
    (tmp_path / "lakeroot").mkdir(parents=True)
    settings = Settings(database_url=f"sqlite:///{tmp_path}/hot.sqlite3",
                        alt_data_parquet_root=str(tmp_path / "lakeroot"), openrouter_api_key=None)
    store = Store(settings)
    store.migrate()
    return settings, store, PgAltDataStore(store), DuckLakeAltDataStore.from_settings(settings)


def _pts(n: int, start: int):
    base = datetime(2026, 1, 1, tzinfo=UTC)
    return [AltDataPoint(ts=base + timedelta(days=i), available_at=base + timedelta(days=i, hours=1), value=round(0.0001 * i, 6))
            for i in range(start, start + n)]


def test_backfill_then_idempotent_then_incremental(tmp_path):
    settings, store, pg, lake = _setup(tmp_path)
    pg.append(_P, _S, _M, _pts(10, 0))                       # 10 rows in "PG"

    r1 = sync_to_lake(settings=settings, store=store, lake=lake)   # full backfill (no watermark)
    assert r1["moved"] == 10 and r1["parity_ok"] and r1["lake_total"] == 10

    r2 = sync_to_lake(settings=settings, store=store, lake=lake)   # nothing new → no-op
    assert r2["moved"] == 0 and r2["parity_ok"] and r2["lake_total"] == 10

    pg.append(_P, _S, _M, _pts(5, 10))                       # 5 newer rows
    r3 = sync_to_lake(settings=settings, store=store, lake=lake)   # incremental: only the 5
    assert r3["moved"] == 5 and r3["parity_ok"] and r3["lake_total"] == 15
    assert r3["watermark_from"] is not None and r3["watermark_to"] > r3["watermark_from"]

    # the lake reads back PIT-identical to PG across the whole series
    asof = datetime(2026, 3, 1, tzinfo=UTC)
    assert [(p.ts, p.value) for p in lake.read_asof(_P, _S, _M, asof)] == \
           [(p.ts, p.value) for p in pg.read_asof(_P, _S, _M, asof)]
