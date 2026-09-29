# intent: keep backtest_symbols.equity_curve_json from re-bloating the hot DB. The finder persists a per-cell
# net-equity curve (~4.5 KB TEXT) on EVERY screen, so the column TOASTs to hundreds of MB within weeks (48k rows
# in 2 weeks = ~200 MB) and dominates both the Supabase DB-size quota and the daily pg_dump egress. The curve is a
# RECOMPUTABLE CACHE — when NULL the API rebuilds it on the fly from the version's spec/params over the cell's real
# bars and writes it back (see api/routers/strategies.py::cell_curve, api/models/explorer.py). So nulling aged
# curves is loss-free and self-healing: the per-symbol SCALARS (return_pct/sharpe/max_drawdown/verdict) — the
# honest non-pooled visibility row — are UNTOUCHED; only the heavy drill-in curve is dropped and recomputed on the
# next view. Dry-run by DEFAULT; apply=True nulls + VACUUMs. Runs alongside the alt_data prune (cold_tier_maintenance).
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from cosmu.config.settings import get_settings
from cosmu.data._iso import iso_utc

logger = logging.getLogger("cosmu.data.backtest_curve_retention")


def _null_and_vacuum(settings: Any, cutoff: str, *, is_pg: bool) -> int:
    """NULL aged equity_curve_json on a dedicated autocommit connection, then VACUUM (ANALYZE) to return the freed
    TOAST to the FSM (steady-state; the one-time on-disk right-size is a manual VACUUM FULL). Returns rows nulled."""
    where = (
        "created_at < {ph} AND equity_curve_json IS NOT NULL AND length(equity_curve_json) > 2"
    )
    if is_pg:
        import psycopg2

        from cosmu.data.providers.ducklake_store import _pg_catalog_dsn

        conn = psycopg2.connect(_pg_catalog_dsn(settings.database_url), connect_timeout=30)
        conn.autocommit = True
        ph, vacuum = "%s", "VACUUM (ANALYZE) backtest_symbols"
    else:
        import sqlite3

        conn = sqlite3.connect(settings.database_url.replace("sqlite:///", "", 1), isolation_level=None)
        ph, vacuum = "?", "VACUUM"
    try:
        cur = conn.cursor()
        cur.execute(f"UPDATE backtest_symbols SET equity_curve_json = NULL WHERE {where.format(ph=ph)}", (cutoff,))
        nulled = cur.rowcount or 0
        cur.execute(vacuum)
    finally:
        conn.close()
    return max(nulled, 0)


def run_backtest_curve_retention(
    *, settings: Any = None, store: Any = None, keep_days: int = 1, now_iso: str | None = None, apply: bool = False,
) -> dict:
    """Null backtest_symbols.equity_curve_json older than `keep_days` (the recent hot curves stay for a snappy
    strat sheet; older ones recompute on demand). Returns {cutoff, to_null, apply, nulled, column_present}. With
    apply=False (default) it counts and changes NOTHING."""
    settings = settings or get_settings()
    from cosmu.knowledge.store import Store, backtest_symbols_has_equity_curve

    store = store or Store(settings)
    is_pg = settings.database_url.startswith(("postgres://", "postgresql://"))

    plan: dict[str, Any] = {"cutoff": None, "to_null": 0, "apply": apply, "nulled": 0, "column_present": False}
    if not backtest_symbols_has_equity_curve(store):
        logger.info("backtest_curve_retention: equity_curve_json column absent — nothing to do")
        return plan  # pre-migration prod: the finder never wrote the column, so there is nothing to prune

    base = datetime.fromisoformat(now_iso) if now_iso else datetime.now(tz=UTC)
    cutoff = iso_utc(base - timedelta(days=keep_days))
    plan["cutoff"] = cutoff
    plan["column_present"] = True
    plan["to_null"] = int(
        store.row(
            "SELECT count(*) AS n FROM backtest_symbols "
            "WHERE created_at < ? AND equity_curve_json IS NOT NULL AND length(equity_curve_json) > 2",
            (cutoff,),
        )["n"]
    )
    logger.info("backtest_curve_retention plan: %s", plan)
    if not apply:
        return plan
    plan["nulled"] = _null_and_vacuum(settings, cutoff, is_pg=is_pg)
    logger.info("backtest_curve_retention applied: nulled=%d", plan["nulled"])
    return plan


def _main() -> int:
    import sys

    argv = sys.argv[1:]
    apply = "--apply" in argv
    keep = 1
    for i, a in enumerate(argv):
        if a == "--keep-days" and i + 1 < len(argv):
            keep = int(argv[i + 1])
    res = run_backtest_curve_retention(keep_days=keep, apply=apply)
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"BACKTEST-CURVE-RETENTION [{mode}] keep_days={keep} :: {res}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
