# intent: the COLD tier of the hot/cold alt-data stack — an append-only Parquet lake (local dir or Cloudflare
# R2), queried via embedded DuckDB. Same append/read_asof/read_all interface as PgAltDataStore, so it's a
# drop-in via resolve_alt_store (settings.alt_data_backend = "parquet"). Why it exists: alt_data in Postgres is
# ~99% of the DB and its btree indexes are 1.4x the data (a time-series hoard is the wrong shape for an OLTP
# store). Parquet is columnar (5-15x smaller, NO per-row indexes), R2 is ~$0.36/mo/24GB with ZERO egress, and
# DuckDB scans it with predicate pushdown for research sweeps. This realigns to VISION.md ("history lives in the
# columnar catalog; Postgres is control-plane + money-truth ONLY"). invariants: PIT-honest reads collapse
# revisions exactly like PgAltDataStore.read_asof (latest-available per ts, value at the latest ts), and store
# ts/available_at as ISO-8601 TEXT EXACTLY like the Postgres/SQLite alt_data table — so reads parse identically,
# string<= comparison matches PgAltDataStore's, and the export copies columns 1:1. Append-only (a batch = one
# immutable Parquet file; compact() merges); local for research, R2 for prod; the gate/money path is untouched.

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from cosmu.data._iso import iso_utc

from ._types import AltDataPoint

logger = logging.getLogger("cosmu.data.parquet_store")


def _is_remote(root: str) -> bool:
    return root.startswith(("r2://", "s3://"))


class ParquetAltDataStore:
    """Cold-tier alt-data store backed by Parquet + DuckDB (drop-in for PgAltDataStore).

    `root` is a local directory or an object-store URL (`r2://<bucket>` / `s3://<bucket>`). When remote, pass
    `r2` credentials so DuckDB attaches httpfs + an R2 secret. Layout: `<root>/alt_data/provider=<p>/
    metric=<m>/part_<uuid>.parquet` — Hive-partitioned by provider+metric (pruned by path on read); symbol is a
    column (handles slashes like BTC/USD). ts/available_at/ingested_at are ISO-8601 TEXT (mirrors the PG table).
    One DuckDB connection per store instance (one per process); the ingest crons and sweeps are single-threaded."""

    def __init__(self, root: str | Path = ".cosmu/altdata_parquet", *, r2: dict[str, str] | None = None) -> None:
        self.root = str(root).rstrip("/")
        self._r2 = r2 or None
        self._con: Any = None

    @classmethod
    def from_settings(cls, settings: Any) -> ParquetAltDataStore:
        """Build from Settings: prefer R2 when all four R2 creds are present (the prod hoard), else the local
        dir (research / offline). Mirrors the keyless-degradation pattern used across the data layer."""
        acct = getattr(settings, "r2_account_id", None)
        key = getattr(settings, "r2_access_key_id", None)
        secret = getattr(settings, "r2_secret_access_key", None)
        bucket = getattr(settings, "r2_bucket", None)
        local_root = getattr(settings, "alt_data_parquet_root", None) or ".cosmu/altdata_parquet"
        if acct and key and secret and bucket:
            return cls(f"r2://{bucket}", r2={"account_id": acct, "key_id": key, "secret": secret})
        return cls(local_root)

    # --- connection ---------------------------------------------------------------------------------------
    def conn(self) -> Any:
        """The lazily-opened DuckDB connection (httpfs + R2 secret attached when the root is remote)."""
        if self._con is not None:
            return self._con
        try:
            import duckdb
        except ImportError as e:  # pragma: no cover - clear actionable error
            raise RuntimeError(
                "ParquetAltDataStore needs DuckDB — install the lake extra: pip install -e 'apps/engine[lake]'"
            ) from e
        con = duckdb.connect(database=":memory:")
        if _is_remote(self.root) and self._r2:
            con.execute("INSTALL httpfs; LOAD httpfs;")
            # DuckDB-native R2 secret (no boto3). Credentials live ONLY in this in-memory secret, never on disk.
            con.execute(
                "CREATE OR REPLACE SECRET cosmu_r2 (TYPE r2, KEY_ID ?, SECRET ?, ACCOUNT_ID ?)",
                [self._r2["key_id"], self._r2["secret"], self._r2["account_id"]],
            )
        self._con = con
        return con

    def _partition_glob(self, provider: str, metric: str) -> str:
        return f"{self.root}/alt_data/provider={provider}/metric={metric}/*.parquet"

    # --- write --------------------------------------------------------------------------------------------
    def append(self, provider: str, symbol: str, metric: str, points: list[AltDataPoint]) -> None:
        """Append a batch as ONE immutable Parquet file in the (provider, metric) partition. Append-only: a
        re-append writes another file; reads collapse duplicate (ts, available_at) pairs and compact() merges."""
        if not points:
            return
        from cosmu.knowledge.store import utcnow

        now = utcnow()
        con = self.conn()
        con.execute(
            "CREATE OR REPLACE TEMP TABLE _w "
            "(symbol VARCHAR, ts VARCHAR, available_at VARCHAR, value VARCHAR, ingested_at VARCHAR)"
        )
        # value stored as TEXT (str of the float) — byte-exact with the PG NUMERIC→VARCHAR export path, no DOUBLE
        # rounding; ts/available_at canonicalized (iso_utc) so the string<= PIT read matches PgAltDataStore exactly.
        con.executemany(
            "INSERT INTO _w VALUES (?, ?, ?, ?, ?)",
            [(symbol, iso_utc(p.ts), iso_utc(p.available_at), str(float(p.value)), now) for p in points],
        )
        target_dir = f"{self.root}/alt_data/provider={provider}/metric={metric}"
        if not _is_remote(self.root):
            Path(target_dir).mkdir(parents=True, exist_ok=True)
        con.execute(f"COPY _w TO '{target_dir}/part_{uuid4().hex}.parquet' (FORMAT parquet)")
        con.execute("DROP TABLE _w")

    # --- read ---------------------------------------------------------------------------------------------
    def _query(self, sql: str, params: list[Any]) -> list[tuple[Any, ...]]:
        try:
            return self.conn().execute(sql, params).fetchall()
        except Exception as e:  # noqa: BLE001 — no partition file yet / unreachable store → empty (honest)
            logger.debug("parquet read miss (%s): %s", self.root, e)
            return []

    def read_asof(self, provider: str, symbol: str, metric: str, as_of: datetime) -> list[AltDataPoint]:
        """PIT read: the latest-revision row per ts available by `as_of`, sorted by ts — IDENTICAL semantics to
        PgAltDataStore.read_asof. ISO-8601 TEXT sorts chronologically, so `available_at <= ?` (string) and the
        revision tiebreak match the PG path exactly."""
        rows = self._query(
            # Latest available_at per ts (the PIT revision winner) — IDENTICAL to PgAltDataStore.read_asof. The
            # secondary `ingested_at ASC` keeps the EARLIEST-ingested copy of an exact (ts, available_at)
            # photocopy, mirroring PG's uq_alt_data_pit ON CONFLICT DO NOTHING (first write wins).
            "SELECT ts, available_at, value FROM ("
            "  SELECT ts, available_at, value, row_number() OVER "
            "    (PARTITION BY ts ORDER BY available_at DESC, ingested_at ASC) rn "
            f"  FROM read_parquet('{self._partition_glob(provider, metric)}') WHERE symbol = ? AND available_at <= ?"
            ") t WHERE rn = 1 ORDER BY ts",
            [symbol, iso_utc(as_of)],
        )
        return [AltDataPoint(ts=datetime.fromisoformat(r[0]), available_at=datetime.fromisoformat(r[1]), value=float(r[2])) for r in rows]

    def read_all(self, provider: str, symbol: str, metric: str) -> list[AltDataPoint]:
        """Full revision history (the per-bar as-of join collapses it) — same contract as PgAltDataStore."""
        rows = self._query(
            # Dedup exact PIT photocopies (same ts AND available_at; keep the earliest ingest — mirrors PG's
            # uq_alt_data_pit ON CONFLICT DO NOTHING) so read_all is tuple-identical to PgAltDataStore even
            # though the append-only lake can physically hold a re-appended window across files.
            "SELECT ts, available_at, value FROM ("
            "  SELECT ts, available_at, value, row_number() OVER "
            "    (PARTITION BY ts, available_at ORDER BY ingested_at ASC) rn "
            f"  FROM read_parquet('{self._partition_glob(provider, metric)}') WHERE symbol = ?"
            ") t WHERE rn = 1 ORDER BY available_at, ts",
            [symbol],
        )
        return [AltDataPoint(ts=datetime.fromisoformat(r[0]), available_at=datetime.fromisoformat(r[1]), value=float(r[2])) for r in rows]

    # --- maintenance --------------------------------------------------------------------------------------
    def compact(self, provider: str, metric: str) -> int:
        """Merge a partition's many small append-files into ONE deduped Parquet (latest revision per
        (symbol, ts, available_at)). The lake analogue of the Postgres compaction — run periodically; reads are
        unaffected (same glob). Local only for now (remote merge is a follow-up). Returns rows kept."""
        if _is_remote(self.root):
            raise NotImplementedError("compact() is local-only for now; remote merge is a follow-up")
        part_dir = Path(self.root) / "alt_data" / f"provider={provider}" / f"metric={metric}"
        files = sorted(part_dir.glob("*.parquet"))
        if len(files) <= 1:
            return sum(1 for _ in part_dir.glob("*.parquet")) and self._count(provider, metric)
        con = self.conn()
        glob = self._partition_glob(provider, metric)
        tmp = part_dir / f"part_{uuid4().hex}.parquet.tmp"
        con.execute(
            f"COPY (SELECT symbol, ts, available_at, value, ingested_at FROM ("
            f"  SELECT *, row_number() OVER (PARTITION BY symbol, ts, available_at ORDER BY ingested_at ASC) rn "
            f"  FROM read_parquet('{glob}')) WHERE rn = 1) TO '{tmp}' (FORMAT parquet)"
        )
        kept = int(con.execute(f"SELECT count(*) FROM read_parquet('{tmp}')").fetchone()[0])
        for f in files:
            f.unlink()
        tmp.rename(tmp.with_suffix(""))  # drop the .tmp suffix
        return kept

    def _count(self, provider: str, metric: str) -> int:
        r = self._query(f"SELECT count(*) FROM read_parquet('{self._partition_glob(provider, metric)}')", [])
        return int(r[0][0]) if r else 0
