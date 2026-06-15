# intent: the COLD tier as a DuckLake table (Parquet data files on R2 + a SQL catalog living in the SAME
# control-plane Postgres) — the buy-not-build upgrade over the raw-Parquet glob (ParquetAltDataStore). DuckLake
# is a DuckDB extension, so it adds ZERO new infra: the catalog is just tables in the DB we already run
# region-pinned next to the engine, and it brings ACID appends, AUTOMATIC small-file compaction
# (ducklake_merge_adjacent_files), snapshots/time-travel, and a one-SQL browse surface. Same
# append/read_asof/read_all interface + IDENTICAL point-in-time semantics as PgAltDataStore /
# ParquetAltDataStore (verified by tests/test_ducklake_cold_tier.py), so it is a drop-in research-read backend.
# invariants: value + ts/available_at stored as TEXT 1:1 with Postgres (the string<= PIT comparison is
# load-bearing); read_asof keeps the LATEST available_at per ts (ingested_at ASC tiebreak = PG's first-write
# wins); read_all dedups exact (ts, available_at) photocopies — the SAME three rules as the other two stores, so
# a lake-fed backtest reads byte-identical numbers to a PG-fed one. The cold lake is RESEARCH-only; the money/UI
# paths never touch it (per-tick R2 reads would be 100-800ms — see orchestrator/loop.py).

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from cosmu.data._iso import iso_utc

from ._types import AltDataPoint

logger = logging.getLogger("cosmu.data.ducklake_store")

_TABLE = "lake.alt_data"


def _pg_catalog_dsn(url: str) -> str:
    """A clean SESSION-mode libpq DSN for DuckLake catalog DDL / VACUUM / the source attach: normalise the
    scheme, DROP the query string (`?pgbouncer=true` — DuckDB's libpq rejects unknown params), and map Supabase's
    TRANSACTION pooler port (6543) to the SESSION pooler port (5432). DuckLake's catalog transactions and VACUUM
    need a real session, which the transaction pooler (pgbouncer) does not provide — so the deployed/synced
    pooler URL is rewritten to session mode here (a direct `:5432` URL passes through unchanged)."""
    dsn = re.sub(r"^postgres(ql)?(\+\w+)?://", "postgresql://", url).split("?", 1)[0]
    return dsn.replace(":6543/", ":5432/")


def _is_remote(path: str) -> bool:
    return path.startswith(("r2://", "s3://"))


class DuckLakeAltDataStore:
    """Cold-tier alt-data store backed by a DuckLake table (drop-in for PgAltDataStore / ParquetAltDataStore).

    `catalog` is a DuckLake catalog target — `postgres:<dsn>` (prod: the control-plane DB) or `sqlite:<path>`
    (research / tests). `data_path` is where the Parquet data files live — `r2://<bucket>/<prefix>` (prod) or a
    local dir. One DuckDB connection per instance; the ingest crons and sweeps are single-threaded."""

    def __init__(self, *, catalog: str, data_path: str, r2: dict[str, str] | None = None) -> None:
        self.catalog = catalog
        self.data_path = data_path.rstrip("/")
        self._r2 = r2 or None
        self._con: Any = None

    @classmethod
    def from_settings(cls, settings: Any) -> DuckLakeAltDataStore:
        """Build from Settings: the catalog is the Postgres control-plane when on a Postgres URL (else a local
        sqlite catalog for research/offline); the data path is R2 when all four creds are present, else local."""
        url = getattr(settings, "database_url", "") or ""
        local_root = getattr(settings, "alt_data_parquet_root", None) or ".cosmu/altdata_parquet"
        if url.startswith(("postgres://", "postgresql://")):
            catalog = f"postgres:{_pg_catalog_dsn(url)}"
        else:
            catalog = f"sqlite:{local_root}/ducklake_catalog.sqlite"
        acct = getattr(settings, "r2_account_id", None)
        key = getattr(settings, "r2_access_key_id", None)
        secret = getattr(settings, "r2_secret_access_key", None)
        bucket = getattr(settings, "r2_bucket", None)
        if acct and key and secret and bucket:
            return cls(catalog=catalog, data_path=f"r2://{bucket}/alt_lake", r2={"account_id": acct, "key_id": key, "secret": secret})
        return cls(catalog=catalog, data_path=f"{local_root}/ducklake_data")

    # --- connection ---------------------------------------------------------------------------------------
    def conn(self) -> Any:
        """Lazily open the DuckDB connection: load ducklake (+ httpfs + an R2 secret when the data path is
        remote), ATTACH the catalog with its DATA_PATH, and ensure the alt_data table + (provider, metric)
        partitioning exist. Credentials live ONLY in the in-memory secret, never on disk."""
        if self._con is not None:
            return self._con
        try:
            import duckdb
        except ImportError as e:  # pragma: no cover - clear actionable error
            raise RuntimeError(
                "DuckLakeAltDataStore needs DuckDB — install the lake extra: pip install -e 'apps/engine[lake]'"
            ) from e
        con = duckdb.connect(database=":memory:")
        con.execute("INSTALL ducklake; LOAD ducklake;")
        if _is_remote(self.data_path) and self._r2:
            con.execute("INSTALL httpfs; LOAD httpfs;")
            con.execute(
                "CREATE OR REPLACE SECRET cosmu_r2 (TYPE r2, KEY_ID ?, SECRET ?, ACCOUNT_ID ?)",
                [self._r2["key_id"], self._r2["secret"], self._r2["account_id"]],
            )
        con.execute(f"ATTACH 'ducklake:{self.catalog}' AS lake (DATA_PATH '{self.data_path}')")
        con.execute(
            f"CREATE TABLE IF NOT EXISTS {_TABLE} "
            "(provider VARCHAR, symbol VARCHAR, metric VARCHAR, ts VARCHAR, "
            "available_at VARCHAR, value VARCHAR, ingested_at VARCHAR)"
        )
        try:
            # Hive-style data-file pruning by provider+metric (year-on-TEXT-ts partitioning is intentionally
            # skipped — symbol stays a column and the in-file order gives ts pruning via row-group stats).
            con.execute(f"ALTER TABLE {_TABLE} SET PARTITIONED BY (provider, metric)")
        except Exception as e:  # noqa: BLE001 — already partitioned (re-open) → not an error
            logger.debug("ducklake partitioning already set or unsupported: %s", e)
        self._con = con
        return con

    # --- write --------------------------------------------------------------------------------------------
    def append(self, provider: str, symbol: str, metric: str, points: list[AltDataPoint]) -> None:
        """ACID append of a batch into the DuckLake table (one transaction). value as TEXT, ts/available_at
        canonicalized (iso_utc) — byte-identical to the PG/Parquet write paths."""
        if not points:
            return
        from cosmu.knowledge.store import utcnow

        now = utcnow()
        con = self.conn()
        con.execute(
            "CREATE OR REPLACE TEMP TABLE _w "
            "(provider VARCHAR, symbol VARCHAR, metric VARCHAR, ts VARCHAR, "
            "available_at VARCHAR, value VARCHAR, ingested_at VARCHAR)"
        )
        con.executemany(
            "INSERT INTO _w VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(provider, symbol, metric, iso_utc(p.ts), iso_utc(p.available_at), str(float(p.value)), now) for p in points],
        )
        con.execute("BEGIN")
        con.execute(f"INSERT INTO {_TABLE} SELECT * FROM _w")
        con.execute("COMMIT")
        con.execute("DROP TABLE _w")

    # --- read ---------------------------------------------------------------------------------------------
    def _query(self, sql: str, params: list[Any]) -> list[tuple[Any, ...]]:
        try:
            return self.conn().execute(sql, params).fetchall()
        except Exception as e:  # noqa: BLE001 — empty/unreachable lake → empty (honest), never a crashed read
            logger.debug("ducklake read miss (%s): %s", self.data_path, e)
            return []

    def read_asof(self, provider: str, symbol: str, metric: str, as_of: datetime) -> list[AltDataPoint]:
        """PIT read: the latest-revision row (LATEST available_at) per ts available by `as_of` — IDENTICAL to
        PgAltDataStore.read_asof. ingested_at ASC keeps the earliest copy of an exact (ts, available_at)
        photocopy, mirroring PG's uq_alt_data_pit ON CONFLICT DO NOTHING (first write wins)."""
        rows = self._query(
            "SELECT ts, available_at, value FROM ("
            "  SELECT ts, available_at, value, row_number() OVER "
            "    (PARTITION BY ts ORDER BY available_at DESC, ingested_at ASC) rn "
            f"  FROM {_TABLE} WHERE provider = ? AND symbol = ? AND metric = ? AND available_at <= ?"
            ") t WHERE rn = 1 ORDER BY ts",
            [provider, symbol, metric, iso_utc(as_of)],
        )
        return [AltDataPoint(ts=datetime.fromisoformat(r[0]), available_at=datetime.fromisoformat(r[1]), value=float(r[2])) for r in rows]

    def read_all(self, provider: str, symbol: str, metric: str) -> list[AltDataPoint]:
        """Full revision history, exact (ts, available_at) photocopies deduped (keep earliest ingest) — same
        contract + ordering as PgAltDataStore.read_all, so the per-bar as-of join collapses it identically."""
        rows = self._query(
            "SELECT ts, available_at, value FROM ("
            "  SELECT ts, available_at, value, row_number() OVER "
            "    (PARTITION BY ts, available_at ORDER BY ingested_at ASC) rn "
            f"  FROM {_TABLE} WHERE provider = ? AND symbol = ? AND metric = ?"
            ") t WHERE rn = 1 ORDER BY available_at, ts",
            [provider, symbol, metric],
        )
        return [AltDataPoint(ts=datetime.fromisoformat(r[0]), available_at=datetime.fromisoformat(r[1]), value=float(r[2])) for r in rows]

    # --- maintenance --------------------------------------------------------------------------------------
    def compact(self) -> None:
        """Merge small data files + expire old snapshots — the lake analogue of Postgres compaction, run weekly
        LOCAL/Modal (never the Railway hot-path cron — heavy R2 IO). Replaces ParquetAltDataStore.compact()'s
        local-only hand-rolled merge with DuckLake's built-in maintenance."""
        con = self.conn()
        con.execute("CALL ducklake_merge_adjacent_files('lake')")
        con.execute("CALL ducklake_expire_snapshots('lake', older_than => now() - INTERVAL 30 DAY)")
        con.execute("CALL ducklake_cleanup_old_files('lake', cleanup_all => true)")
