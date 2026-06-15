# intent: the ONE steady-state writer of the cold lake. Incrementally mirrors the Postgres alt_data table into
# the DuckLake lake via a single set-based DuckDB statement (ATTACH the source READ-ONLY + INSERT INTO lake
# SELECT) — no Python row loop. A watermark on available_at makes it incremental: the watermark-ABSENT first run
# is the full one-time backfill; every later run copies only rows newer than the watermark (the steady-state
# aged-out pass). value→TEXT + the ISO casts mirror export_alt_parquet so the lake stays byte-identical to PG.
# It is READ-ONLY on alt_data and NEVER deletes — pruning Postgres is a SEPARATE, operator-gated step
# (run AFTER a COUNT parity on the moved window). Heavy R2 IO → run LOCAL or on Modal, NEVER a Railway hot cron.

from __future__ import annotations

import logging
from typing import Any

from cosmu.config.settings import get_settings
from cosmu.data.providers.ducklake_store import _TABLE, DuckLakeAltDataStore, _pg_catalog_dsn

logger = logging.getLogger("cosmu.data.age_out")

_WATERMARK_KEY = "alt_data_age_out"


def _ensure_watermark_table(store: Any) -> None:
    with store.batch() as w:
        w.execute(
            "CREATE TABLE IF NOT EXISTS alt_lake_watermark (k TEXT PRIMARY KEY, last_available_at TEXT NOT NULL)"
        )


def _read_watermark(store: Any) -> str | None:
    _ensure_watermark_table(store)
    row = store.row("SELECT last_available_at FROM alt_lake_watermark WHERE k = ?", (_WATERMARK_KEY,))
    return row["last_available_at"] if row else None


def _write_watermark(store: Any, value: str) -> None:
    with store.batch() as w:
        w.execute(
            "INSERT INTO alt_lake_watermark (k, last_available_at) VALUES (?, ?) "
            "ON CONFLICT (k) DO UPDATE SET last_available_at = excluded.last_available_at",
            (_WATERMARK_KEY, value),
        )


def _attach_source(con: Any, url: str) -> str:
    """ATTACH the alt_data source READ-ONLY and return its qualified table name (postgres prod or sqlite test).
    Detaches any prior attachment first so a re-run (or a partial failure) re-attaches cleanly."""
    try:
        con.execute("DETACH src")  # idempotent: no-op when not attached
    except Exception:  # noqa: BLE001 — not attached yet
        pass
    if url.startswith(("postgres://", "postgresql://")):
        con.execute("INSTALL postgres; LOAD postgres;")
        con.execute(f"ATTACH '{_pg_catalog_dsn(url)}' AS src (TYPE postgres, READ_ONLY)")
        return "src.public.alt_data"
    if url.startswith("sqlite:///"):
        con.execute("INSTALL sqlite; LOAD sqlite;")
        con.execute(f"ATTACH '{url.replace('sqlite:///', '', 1)}' AS src (TYPE sqlite, READ_ONLY)")
        return "src.alt_data"
    raise SystemExit(f"unsupported alt_data source for age-out: {url!r}")


def sync_to_lake(*, settings: Any = None, store: Any = None, lake: DuckLakeAltDataStore | None = None) -> dict:
    """Mirror alt_data → the DuckLake lake incrementally: copy every PG row with available_at > the stored
    watermark (set-based), then advance the watermark to the new max. The first (watermark-absent) run is the
    full backfill; later runs are the steady-state aged-out pass. READ-ONLY on alt_data.

    Returns {moved, lake_window, parity_ok, watermark_from, watermark_to, lake_total}. `parity_ok` compares the
    source count and the lake count FOR THE MOVED WINDOW (available_at > watermark_from), so it stays correct
    even after Postgres has been pruned (totals would differ; the moved window never does)."""
    from cosmu.knowledge.store import Store

    settings = settings or get_settings()
    store = store or Store(settings)
    lake = lake or DuckLakeAltDataStore.from_settings(settings)

    wm = _read_watermark(store)  # exclusive lower bound; None on the first (backfill) run
    con = lake.conn()  # ducklake attached + lake.alt_data ensured
    src_table = _attach_source(con, settings.database_url)

    where, params = "", []
    if wm:
        where, params = " WHERE available_at > ?", [wm]

    con.execute("BEGIN")
    con.execute(
        f'INSERT INTO {_TABLE} SELECT provider, symbol, metric, CAST(ts AS VARCHAR), '
        f'CAST(available_at AS VARCHAR), CAST("value" AS VARCHAR), CAST(ingested_at AS VARCHAR) '
        f"FROM {src_table}{where}",
        params,
    )
    con.execute("COMMIT")

    # Parity on the JUST-MOVED window (robust to a later PG prune): source rows == lake rows for available_at > wm.
    moved = int(con.execute(f"SELECT count(*) FROM {src_table}{where}", params).fetchone()[0])
    lake_window = int(con.execute(f"SELECT count(*) FROM {_TABLE}{where}", params).fetchone()[0])
    lake_total = int(con.execute(f"SELECT count(*) FROM {_TABLE}").fetchone()[0])
    new_wm = con.execute(f"SELECT max(available_at) FROM {src_table}{where}", params).fetchone()[0]
    con.execute("DETACH src")  # release the source (read) attachment so a concurrent writer never blocks

    if new_wm:
        _write_watermark(store, new_wm)
    parity_ok = moved == lake_window
    logger.info("age-out: moved=%d parity_ok=%s watermark %s→%s lake_total=%d", moved, parity_ok, wm, new_wm, lake_total)
    return {
        "moved": moved,
        "lake_window": lake_window,
        "parity_ok": parity_ok,
        "watermark_from": wm,
        "watermark_to": new_wm,
        "lake_total": lake_total,
    }


def _main() -> int:
    result = sync_to_lake()
    status = "OK" if result["parity_ok"] else "PARITY MISMATCH"
    print(f"age-out [{status}]: moved {result['moved']:,} rows; lake total {result['lake_total']:,}; "
          f"watermark {result['watermark_from']} → {result['watermark_to']}")
    return 0 if result["parity_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())
