# intent: ONE-SHOT migration of the hot alt_data table (Postgres or SQLite) into the COLD Parquet lake (local
# dir or Cloudflare R2). DuckDB ATTACHes the source and streams it to Hive-partitioned Parquet in a single
# COPY — columnar, fast, no Python row loop. The layout matches ParquetAltDataStore's read path exactly
# (provider=…/metric=… partitions; ts/available_at copied as ISO-8601 TEXT 1:1). Re-runnable (OVERWRITE).
# CLI: python -m cosmu.data.export_alt_parquet [--root DIR] [--memory-limit 8GB]  (root → settings: R2 if keyed)
# Heavy reads → run LOCAL (memory-bound on a small box) or on Modal (export_lake, 32GB), never a Railway cron.
# live OFF; read-only on the source. Streamed write (preserve_insertion_order=false) keeps memory flat.

from __future__ import annotations

import sys

from cosmu.config.settings import get_settings
from cosmu.data.providers.parquet_store import ParquetAltDataStore


def export_alt_data(*, root: str | None = None, memory_limit: str | None = None) -> dict:
    """Stream the source alt_data → partitioned Parquet at the cold-tier root. Returns {rows, root, source}."""
    settings = get_settings()
    dst = ParquetAltDataStore(root) if root else ParquetAltDataStore.from_settings(settings)
    con = dst.conn()  # reuses the R2-secret-attached connection when the root is remote
    # A partitioned COPY buffers per-partition; with order preserved, a 13.5M-row export (LunarCrush alone is
    # ~99%) spills GBs into OS swap — the ~35min thrash observed on a 16GB box. Insertion order is irrelevant
    # here (read_asof re-sorts on every read), so streaming the write keeps memory flat. An optional
    # memory_limit hard-caps DuckDB so a small box spills to local temp instead of drowning in OS swap.
    con.execute("SET preserve_insertion_order=false")
    if memory_limit:
        con.execute("SET memory_limit=?", [memory_limit])
    url = settings.database_url or ""

    if url.startswith(("postgres://", "postgresql://")):
        from cosmu.knowledge.store import _pg_dsn

        con.execute("INSTALL postgres; LOAD postgres;")
        con.execute(f"ATTACH '{_pg_dsn(url)}' AS src (TYPE postgres, READ_ONLY)")
        src_table, source = "src.public.alt_data", "postgres"
    elif url.startswith("sqlite:///"):
        con.execute("INSTALL sqlite; LOAD sqlite;")
        con.execute(f"ATTACH '{url.replace('sqlite:///', '', 1)}' AS src (TYPE sqlite, READ_ONLY)")
        src_table, source = "src.alt_data", "sqlite"
    else:
        raise SystemExit(f"unsupported source for export: {url!r}")

    target = f"{dst.root}/alt_data"
    # PARTITION_BY (provider, metric) writes provider=…/metric=… dirs; the file keeps symbol/ts/available_at/
    # value/ingested_at — exactly ParquetAltDataStore's read schema. value→VARCHAR (the source NUMERIC kept as
    # EXACT text — a DOUBLE cast rounds 18-significant-digit values and would make a lake-fed backtest read a
    # different funding_rate/TVL than the PG path); the two timestamps stay ISO-8601 TEXT (string<= PIT
    # comparison, parsed on read — identical to the PG path).
    con.execute(
        f"COPY (SELECT provider, symbol, metric, CAST(ts AS VARCHAR) AS ts, "
        f'  CAST(available_at AS VARCHAR) AS available_at, CAST("value" AS VARCHAR) AS "value", '
        f"  CAST(ingested_at AS VARCHAR) AS ingested_at FROM {src_table}) "
        f"TO '{target}' (FORMAT parquet, PARTITION_BY (provider, metric), OVERWRITE_OR_IGNORE)"
    )
    rows = int(con.execute(f"SELECT count(*) FROM read_parquet('{target}/**/*.parquet')").fetchone()[0])
    return {"rows": rows, "root": dst.root, "source": source}


def _main() -> int:
    root = None
    memory_limit = None
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == "--root" and i + 1 < len(argv):
            root = argv[i + 1]
        if a == "--memory-limit" and i + 1 < len(argv):
            memory_limit = argv[i + 1]  # e.g. "8GB" — cap DuckDB on a small box; omit on a beefy Modal run
    result = export_alt_data(root=root, memory_limit=memory_limit)
    print(f"exported {result['rows']:,} alt_data rows from {result['source']} → {result['root']}/alt_data (Parquet)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
