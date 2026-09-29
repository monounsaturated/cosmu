# run_alt_data_retention prunes aged alt_data from Postgres ONLY after the DuckLake lake holds the delete
# window (a count gate), dry-run by default, with the funding series exempt. Offline: a sqlite "Postgres" source
# + a local DuckLake. Pins: the gate ABORTS when the lake is incomplete, dry-run deletes nothing, apply removes
# only aged non-exempt rows, funding stays, and the lake is never touched.

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
except Exception:  # noqa: BLE001
    pytest.skip("ducklake/sqlite extension unavailable (offline)", allow_module_level=True)

from cosmu.data.age_out import sync_to_lake  # noqa: E402
from cosmu.data.providers.ducklake_store import DuckLakeAltDataStore  # noqa: E402
from cosmu.data.retention import run_alt_data_retention  # noqa: E402


def _setup(tmp_path):
    (tmp_path / "lr").mkdir(parents=True)
    s = Settings(database_url=f"sqlite:///{tmp_path}/hot.sqlite3", alt_data_parquet_root=str(tmp_path / "lr"), openrouter_api_key=None)
    st = Store(s)
    st.migrate()
    return s, st, PgAltDataStore(st), DuckLakeAltDataStore.from_settings(s)


def _series(n: int):
    base = datetime(2026, 1, 1, tzinfo=UTC)
    return [AltDataPoint(ts=base + timedelta(days=i), available_at=base + timedelta(days=i, hours=1), value=float(i)) for i in range(n)]


def test_prune_gated_on_lake_and_exempts_funding(tmp_path):
    s, st, pg, lake = _setup(tmp_path)
    pg.append("defillama", "MARKET", "defi_tvl", _series(100))          # prunable
    pg.append("binance", "BTCUSDT", "funding_rate", _series(100))       # EXEMPT (money series)
    now = (datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=120)).isoformat()  # cutoff = now-90d = day30

    # 1) GATE: lake empty → apply must ABORT (never delete what the lake lacks)
    abort = run_alt_data_retention(settings=s, store=st, lake=lake, hot_window_days=90, now_iso=now, apply=True)
    assert abort.get("aborted") and abort["deleted"] == 0

    sync_to_lake(settings=s, store=st, lake=lake)  # full mirror → lake now complete

    # 2) DRY-RUN: reports a non-zero plan, deletes nothing
    dry = run_alt_data_retention(settings=s, store=st, lake=lake, hot_window_days=90, now_iso=now, apply=False)
    assert dry["lake_complete"] and dry["deleted"] == 0 and dry["pg_to_delete"] == 30  # defi_tvl days 0..29

    # 3) APPLY: deletes exactly the aged non-exempt rows
    res = run_alt_data_retention(settings=s, store=st, lake=lake, hot_window_days=90, now_iso=now, apply=True)
    assert res["deleted"] == 30
    cutoff = datetime.fromisoformat(res["cutoff"])
    kept = pg.read_all("defillama", "MARKET", "defi_tvl")
    assert len(kept) == 70 and all(p.available_at >= cutoff for p in kept)        # only recent defi_tvl remains
    assert len(pg.read_all("binance", "BTCUSDT", "funding_rate")) == 100          # funding fully exempt
    assert len(lake.read_all("defillama", "MARKET", "defi_tvl")) == 100           # lake untouched (full history)
