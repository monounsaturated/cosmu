# intent: the GATED Postgres retention prune for alt_data — the step that actually keeps the hot DB lean after
# the history has been mirrored to the DuckLake cold lake. It DELETEs rows older than the hot window, but ONLY
# after confirming the lake already holds them (a count gate on the exact delete window), then VACUUMs to return
# the freed space to the FSM (NOT VACUUM FULL — no exclusive rewrite; the disk allocation is unchanged per the
# "stop growth, don't right-size" decision). Dry-run by DEFAULT — `apply=True` is required to delete. The funding
# series is EXEMPT (the money read `_funding_rate_asof` wants the latest rate fast from PG; it is tiny). Heavy
# enough (DuckDB lake read + a multi-million-row delete) that it runs on Modal/local, never a Railway hot cron.
# invariants: never deletes a row the lake lacks (the gate aborts loudly); batched delete (bounded locks);
# COLLATE "C"/binary cutoff so "older than" is chronological on Postgres (matches the lake) — see read_asof.

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from cosmu.config.settings import get_settings
from cosmu.data._iso import iso_utc
from cosmu.data.providers.ducklake_store import _TABLE, DuckLakeAltDataStore, _pg_catalog_dsn

logger = logging.getLogger("cosmu.data.retention")

# (provider, metric) series kept in Postgres regardless of age — the money path reads them hot.
_EXEMPT: tuple[tuple[str, str], ...] = (("binance", "funding_rate"),)


def _exempt_sql(exempt: tuple[tuple[str, str], ...]) -> str:
    # provider/metric are controlled config literals (not user input) — safe to inline.
    return "".join(f" AND NOT (provider = '{p}' AND metric = '{m}')" for p, m in exempt)


def _delete_and_vacuum(settings: Any, where_sql: str, cutoff: str, *, is_pg: bool, batch: int, max_batches: int) -> int:
    """Batched DELETE (bounded locks) on a dedicated SESSION-mode connection, then VACUUM (ANALYZE). Returns the
    total rows deleted. The connection is autocommit so each batch commits immediately and VACUUM runs outside a
    transaction (Postgres forbids VACUUM inside one)."""
    if is_pg:
        import psycopg2

        conn = psycopg2.connect(_pg_catalog_dsn(settings.database_url), connect_timeout=30)
        conn.autocommit = True
        ph, vacuum = "%s", "VACUUM (ANALYZE) alt_data"
    else:
        import sqlite3

        conn = sqlite3.connect(settings.database_url.replace("sqlite:///", "", 1), isolation_level=None)
        ph, vacuum = "?", "VACUUM"
    sub = f"SELECT id FROM alt_data WHERE {where_sql.replace('?', ph)} LIMIT {batch}"
    deleted = 0
    try:
        cur = conn.cursor()
        for _ in range(max_batches):
            cur.execute(f"DELETE FROM alt_data WHERE id IN ({sub})", (cutoff,))
            n = cur.rowcount or 0
            deleted += max(n, 0)
            if n <= 0:
                break
        cur.execute(vacuum)
    finally:
        conn.close()
    return deleted


def run_alt_data_retention(
    *, settings: Any = None, store: Any = None, lake: DuckLakeAltDataStore | None = None,
    hot_window_days: int = 90, now_iso: str | None = None, exempt: tuple[tuple[str, str], ...] = _EXEMPT,
    apply: bool = False, batch: int = 50_000, max_batches: int = 100_000,
) -> dict:
    """Prune alt_data rows older than `hot_window_days` from Postgres, gated on lake completeness.

    Returns a plan dict: {cutoff, pg_to_delete, lake_has_window, lake_complete, apply, deleted, pg_remaining?}.
    With apply=False (default) it computes the gate and deletes NOTHING. With apply=True it deletes ONLY when
    `lake_complete` (the lake holds at least every row in the delete window), else aborts with `aborted`."""
    settings = settings or get_settings()
    from cosmu.knowledge.store import Store

    store = store or Store(settings)
    lake = lake or DuckLakeAltDataStore.from_settings(settings)
    is_pg = settings.database_url.startswith(("postgres://", "postgresql://"))
    c = ' COLLATE "C"' if is_pg else ""  # binary "older than" cut = chronological = lake-identical

    base = datetime.fromisoformat(now_iso) if now_iso else datetime.now(tz=UTC)
    cutoff = iso_utc(base - timedelta(days=hot_window_days))
    ex = _exempt_sql(exempt)
    where = f"available_at{c} < ?{ex}"

    pg_to_delete = int(store.row(f"SELECT count(*) AS n FROM alt_data WHERE {where}", (cutoff,))["n"])
    # The SAME window in the lake (DuckDB binary `<` == Postgres COLLATE "C" `<`). The lake must hold them all.
    lcon = lake.conn()
    lake_has = int(lcon.execute(f"SELECT count(*) FROM {_TABLE} WHERE available_at < ?{ex}", [cutoff]).fetchone()[0])
    complete = lake_has >= pg_to_delete

    plan: dict[str, Any] = {
        "cutoff": cutoff, "hot_window_days": hot_window_days, "pg_to_delete": pg_to_delete,
        "lake_has_window": lake_has, "lake_complete": complete, "apply": apply, "deleted": 0,
    }
    logger.info("retention plan: %s", plan)
    if not apply:
        return plan
    if not complete:
        plan["aborted"] = f"lake holds {lake_has} of {pg_to_delete} delete-window rows — refusing to delete"
        logger.error(plan["aborted"])
        return plan
    plan["deleted"] = _delete_and_vacuum(settings, where, cutoff, is_pg=is_pg, batch=batch, max_batches=max_batches)
    plan["pg_remaining"] = int(store.row("SELECT count(*) AS n FROM alt_data")["n"])
    logger.info("retention applied: deleted=%d pg_remaining=%d", plan["deleted"], plan["pg_remaining"])
    return plan


def _main() -> int:
    import sys

    argv = sys.argv[1:]
    apply = "--apply" in argv
    days = 90
    for i, a in enumerate(argv):
        if a == "--hot-window-days" and i + 1 < len(argv):
            days = int(argv[i + 1])
    res = run_alt_data_retention(hot_window_days=days, apply=apply)
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"RETENTION [{mode}] hot_window_days={days} :: {res}")
    return 1 if res.get("aborted") else 0


if __name__ == "__main__":
    raise SystemExit(_main())
