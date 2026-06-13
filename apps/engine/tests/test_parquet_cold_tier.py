# The COLD tier of the hot/cold alt-data stack: ParquetAltDataStore (DuckDB + Parquet, local or R2) is a
# drop-in for PgAltDataStore. These tests pin it as PIT-IDENTICAL to the Postgres path (the gate/money read
# semantics must not change by backend) — read_asof + read_all parity across a mid-window revision — plus
# append/compact/read-miss behaviour and the resolve_alt_store routing. All OFFLINE: a LOCAL Parquet dir uses
# only DuckDB's core parquet reader (no extension download, no network). The R2 path + the PG→Parquet export
# need DuckDB's httpfs/postgres extensions (network) and are verified out-of-band, not here.

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from cosmu.config.settings import Settings
from cosmu.data.providers._types import AltDataPoint
from cosmu.data.providers.store import PgAltDataStore
from cosmu.knowledge.store import Store

duckdb = pytest.importorskip("duckdb")  # the lake extra; skip cleanly where it isn't installed
from cosmu.data.providers.parquet_store import ParquetAltDataStore  # noqa: E402

_P, _S, _M = "defillama", "MARKET", "defi_tvl"


def _pg(tmp_path) -> PgAltDataStore:
    store = Store(Settings(database_url=f"sqlite:///{tmp_path}/hot.sqlite3", openrouter_api_key=None))
    store.migrate()
    return PgAltDataStore(store)


def _series() -> list[AltDataPoint]:
    """A 30-day daily series with a mid-window REVISION (day 10 re-published later with a new value)."""
    base = datetime(2026, 1, 1, tzinfo=UTC)
    pts = [AltDataPoint(ts=base + timedelta(days=i), available_at=base + timedelta(days=i + 1), value=100.0 + i) for i in range(30)]
    # vendor revises day-10's value, learned 5 days later (a strictly-later available_at → a distinct PIT row)
    pts.append(AltDataPoint(ts=base + timedelta(days=10), available_at=base + timedelta(days=15), value=999.0))
    return pts


def test_read_asof_is_pit_identical_to_postgres(tmp_path):
    pg = _pg(tmp_path)
    cold = ParquetAltDataStore(tmp_path / "lake")
    pts = _series()
    pg.append(_P, _S, _M, pts)
    cold.append(_P, _S, _M, pts)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for d in range(0, 40):
        as_of = base + timedelta(days=d)
        a = [(p.ts, p.value) for p in pg.read_asof(_P, _S, _M, as_of)]
        b = [(p.ts, p.value) for p in cold.read_asof(_P, _S, _M, as_of)]
        assert a == b, f"read_asof divergence at day {d}"
    # the revision must actually flip (day-10 value 110 before its availability, 999 after) — proves it's exercised
    pre = {p.ts: p.value for p in cold.read_asof(_P, _S, _M, base + timedelta(days=12))}
    post = {p.ts: p.value for p in cold.read_asof(_P, _S, _M, base + timedelta(days=20))}
    assert pre[base + timedelta(days=10)] == 110.0
    assert post[base + timedelta(days=10)] == 999.0


def test_read_all_parity_with_postgres(tmp_path):
    pg, cold = _pg(tmp_path), ParquetAltDataStore(tmp_path / "lake")
    pts = _series()
    pg.append(_P, _S, _M, pts)
    cold.append(_P, _S, _M, pts)
    a = sorted((p.ts, p.available_at, p.value) for p in pg.read_all(_P, _S, _M))
    b = sorted((p.ts, p.available_at, p.value) for p in cold.read_all(_P, _S, _M))
    assert a == b


def test_read_miss_returns_empty_never_raises(tmp_path):
    cold = ParquetAltDataStore(tmp_path / "lake")
    assert cold.read_asof(_P, _S, _M, datetime(2026, 1, 1, tzinfo=UTC)) == []
    assert cold.read_all(_P, "NOPE", _M) == []


def test_compact_merges_files_and_preserves_reads(tmp_path):
    cold = ParquetAltDataStore(tmp_path / "lake")
    base = datetime(2026, 1, 1, tzinfo=UTC)
    # three separate append batches → three files in one partition
    for w in range(3):
        cold.append(_P, _S, _M, [AltDataPoint(ts=base + timedelta(days=w), available_at=base + timedelta(days=w + 1), value=float(w))])
    part = tmp_path / "lake" / "alt_data" / f"provider={_P}" / f"metric={_M}"
    assert len(list(part.glob("*.parquet"))) == 3
    before = sorted((p.ts, p.value) for p in cold.read_all(_P, _S, _M))
    kept = cold.compact(_P, _M)
    assert kept == 3
    assert len(list(part.glob("*.parquet"))) == 1  # merged to one file
    assert sorted((p.ts, p.value) for p in cold.read_all(_P, _S, _M)) == before  # reads unchanged


def test_resolve_alt_store_routes_to_parquet_when_configured(tmp_path):
    from cosmu.data.alt_join import resolve_alt_store

    s = Settings(database_url="sqlite:///:memory:", alt_data_backend="parquet",
                 alt_data_parquet_root=str(tmp_path / "lake"))
    assert isinstance(resolve_alt_store(s, None), ParquetAltDataStore)
    # default backend stays Postgres/JSONL (no behaviour change)
    s_pg = Settings(database_url="postgresql://x/y")
    assert type(resolve_alt_store(s_pg, object())).__name__ == "PgAltDataStore"


def test_from_settings_prefers_r2_when_keyed_else_local(tmp_path):
    local = ParquetAltDataStore.from_settings(Settings(alt_data_parquet_root=str(tmp_path / "lake")))
    assert local.root.endswith("lake") and not local.root.startswith(("r2://", "s3://"))
    keyed = ParquetAltDataStore.from_settings(Settings(
        r2_account_id="acct", r2_access_key_id="k", r2_secret_access_key="s", r2_bucket="cosmu-lake"))
    assert keyed.root == "r2://cosmu-lake"
