# DuckLake cold tier: PIT-IDENTICAL to PgAltDataStore (read_asof + read_all + photocopy dedup), exercised
# OFFLINE via a sqlite catalog + a local data dir (no R2/network for data; the ducklake EXTENSION itself needs
# one network install, so the module skips cleanly where it can't be loaded). Mirrors test_parquet_cold_tier so
# all three backends are pinned to the same money/gate read semantics.

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
    _c.close()
except Exception:  # noqa: BLE001 — extension unavailable offline → skip the whole module cleanly
    pytest.skip("ducklake extension unavailable (offline)", allow_module_level=True)

from cosmu.data.providers.ducklake_store import DuckLakeAltDataStore  # noqa: E402
from cosmu.data.providers.tiered_store import TieredAltDataStore  # noqa: E402

_P, _S, _M = "defillama", "MARKET", "defi_tvl"


def _pg(tmp_path) -> PgAltDataStore:
    store = Store(Settings(database_url=f"sqlite:///{tmp_path}/hot.sqlite3", openrouter_api_key=None))
    store.migrate()
    return PgAltDataStore(store)


def _lake(tmp_path) -> DuckLakeAltDataStore:
    return DuckLakeAltDataStore(catalog=f"sqlite:{tmp_path}/cat.sqlite", data_path=str(tmp_path / "data"))


def _series() -> list[AltDataPoint]:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    pts = [AltDataPoint(ts=base + timedelta(days=i), available_at=base + timedelta(days=i + 1), value=100.0 + i) for i in range(30)]
    pts.append(AltDataPoint(ts=base + timedelta(days=10), available_at=base + timedelta(days=15), value=999.0))  # revision
    return pts


def test_read_asof_pit_identical_to_postgres(tmp_path):
    pg, lake = _pg(tmp_path), _lake(tmp_path)
    pts = _series()
    pg.append(_P, _S, _M, pts)
    lake.append(_P, _S, _M, pts)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for d in range(0, 40):
        as_of = base + timedelta(days=d)
        assert [(p.ts, p.value) for p in pg.read_asof(_P, _S, _M, as_of)] == \
               [(p.ts, p.value) for p in lake.read_asof(_P, _S, _M, as_of)], f"read_asof divergence at day {d}"


def test_read_all_parity_and_photocopy_dedup(tmp_path):
    pg, lake = _pg(tmp_path), _lake(tmp_path)
    pts = _series()
    pg.append(_P, _S, _M, pts)
    lake.append(_P, _S, _M, pts)
    pg.append(_P, _S, _M, [pts[5]])    # exact PIT photocopy → no-op in PG (uq), physical dup in the lake
    lake.append(_P, _S, _M, [pts[5]])
    a = sorted((p.ts, p.available_at, p.value) for p in pg.read_all(_P, _S, _M))
    b = sorted((p.ts, p.available_at, p.value) for p in lake.read_all(_P, _S, _M))
    assert a == b and len(b) == len(pts)


def test_read_miss_returns_empty_never_raises(tmp_path):
    lake = _lake(tmp_path)
    assert lake.read_asof(_P, _S, _M, datetime(2026, 1, 1, tzinfo=UTC)) == []
    assert lake.read_all(_P, "NOPE", _M) == []


def test_from_settings_picks_catalog_and_data_path(tmp_path):
    local = DuckLakeAltDataStore.from_settings(Settings(database_url="sqlite:///:memory:", alt_data_parquet_root=str(tmp_path)))
    assert local.catalog.startswith("sqlite:") and not local.data_path.startswith(("r2://", "s3://"))
    r2 = DuckLakeAltDataStore.from_settings(Settings(
        database_url="postgresql://u:p@h:6543/postgres?pgbouncer=true",
        r2_account_id="a", r2_access_key_id="k", r2_secret_access_key="s", r2_bucket="cosmu-lake"))
    assert r2.catalog == "postgres:postgresql://u:p@h:6543/postgres"  # query string stripped for libpq
    assert r2.data_path == "r2://cosmu-lake/alt_lake"


def test_tiered_union_equals_single_store(tmp_path):
    """A research read over PG-hot ∪ DuckLake-cold is tuple-identical to a single PG holding ALL rows — proves
    the seam dedup matches PG's revision winner, so a prune (moving aged rows to the lake) never changes a sweep."""
    for sub in ("full", "hot", "lake"):
        (tmp_path / sub).mkdir()
    full = _pg(tmp_path / "full")
    hot = _pg(tmp_path / "hot")
    lake = _lake(tmp_path / "lake")
    pts = _series()
    full.append(_P, _S, _M, pts)
    cutoff = datetime(2026, 1, 20, tzinfo=UTC)
    lake.append(_P, _S, _M, [p for p in pts if p.ts < cutoff])   # aged-out cold (incl. the day-10 revision)
    hot.append(_P, _S, _M, [p for p in pts if p.ts >= cutoff])   # recent hot window
    tiered = TieredAltDataStore(hot, lake)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for d in range(0, 40):
        as_of = base + timedelta(days=d)
        assert [(p.ts, p.value) for p in tiered.read_asof(_P, _S, _M, as_of)] == \
               [(p.ts, p.value) for p in full.read_asof(_P, _S, _M, as_of)], f"tiered read_asof divergence at day {d}"
    assert sorted((p.ts, p.available_at, p.value) for p in tiered.read_all(_P, _S, _M)) == \
           sorted((p.ts, p.available_at, p.value) for p in full.read_all(_P, _S, _M))


def test_resolve_alt_store_routes_tiered_and_ducklake(tmp_path):
    from cosmu.data.alt_join import resolve_alt_store

    s_dl = Settings(database_url="sqlite:///:memory:", alt_data_parquet_root=str(tmp_path), alt_data_backend="ducklake")
    assert type(resolve_alt_store(s_dl, None)).__name__ == "DuckLakeAltDataStore"
    s_ti = Settings(database_url="sqlite:///:memory:", alt_data_parquet_root=str(tmp_path), alt_data_backend="tiered")
    assert type(resolve_alt_store(s_ti, object())).__name__ == "TieredAltDataStore"
