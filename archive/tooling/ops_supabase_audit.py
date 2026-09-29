# intent: READ-ONLY audit of the live Supabase Postgres for the "can we downgrade Pro->Free?" decision.
# Measures total DB size, per-table heap+index breakdown, alt_data shape (rows/providers/metrics/ts-span),
# and the realtime bars_intraday table. NO writes, NO DDL. Prints results only (never secrets).
from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg2


def load_env(path: str) -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env("<repo>/.env.local")
dsn = os.environ.get("DATABASE_URL")
if not dsn:
    print("NO DATABASE_URL", file=sys.stderr)
    sys.exit(1)

# strip pooler-only query params (pgbouncer=true) that libpq/psycopg2 rejects
dsn = dsn.split("?", 1)[0]
# host only, for sanity (no creds)
host = dsn.split("@")[-1].split("/")[0] if "@" in dsn else "?"
print(f"# connecting to host: {host}\n")

conn = psycopg2.connect(dsn, connect_timeout=20)
conn.autocommit = True  # read-only by discipline: this script issues only SELECT/size queries, no DML/DDL
cur = conn.cursor()


def q(sql, params=None):
    cur.execute(sql, params or [])
    return cur.fetchall()


print("=== DB TOTAL ===")
print(q("SELECT current_database(), pg_size_pretty(pg_database_size(current_database()))")[0])

print("\n=== TOP TABLES (heap+indexes, public) ===")
rows = q(
    """
    SELECT relname,
           pg_size_pretty(pg_total_relation_size(c.oid))            AS total,
           pg_size_pretty(pg_table_size(c.oid))                     AS heap,
           pg_size_pretty(pg_indexes_size(c.oid))                   AS indexes,
           pg_total_relation_size(c.oid)                            AS total_bytes,
           c.reltuples::bigint                                      AS approx_rows
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind = 'r'
    ORDER BY pg_total_relation_size(c.oid) DESC
    LIMIT 40
    """
)
print(f"{'table':38} {'total':>10} {'heap':>10} {'indexes':>10} {'approx_rows':>14}")
total_all = 0
for r in rows:
    print(f"{r[0]:38} {r[1]:>10} {r[2]:>10} {r[3]:>10} {r[5]:>14}")
    total_all += r[4]
print(f"\n# sum of listed tables total: {total_all/1e6:.1f} MB")

print("\n=== CONTROL PLANE (everything EXCEPT alt_data*) ===")
rows = q(
    """
    SELECT COALESCE(SUM(pg_total_relation_size(c.oid)),0)
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relname NOT LIKE 'alt_data%%'
    """
)
print(f"control-plane (non-alt_data) total: {float(rows[0][0])/1e6:.1f} MB")

print("\n=== alt_data SHAPE ===")
try:
    cnt = q("SELECT count(*) FROM alt_data")[0][0]
    print(f"alt_data rows: {cnt:,}")
    span = q("SELECT min(ts), max(ts), count(DISTINCT provider), count(DISTINCT metric), count(DISTINCT symbol) FROM alt_data")[0]
    print(f"ts span: {span[0]} .. {span[1]} | providers={span[2]} metrics={span[3]} symbols={span[4]}")
    print("\n  per-provider rows:")
    for r in q("SELECT provider, count(*) FROM alt_data GROUP BY provider ORDER BY 2 DESC"):
        print(f"    {r[0]:24} {r[1]:>12,}")
except Exception as e:  # noqa: BLE001
    print(f"alt_data query failed: {e}")

print("\n=== bars_intraday (realtime table) ===")
try:
    exists = q("SELECT to_regclass('public.bars_intraday')")[0][0]
    if exists:
        c = q("SELECT count(*), min(ts), max(ts) FROM bars_intraday")[0]
        sz = q("SELECT pg_size_pretty(pg_total_relation_size('public.bars_intraday'))")[0][0]
        print(f"bars_intraday: rows={c[0]:,} span={c[1]}..{c[2]} size={sz}")
    else:
        print("bars_intraday: does not exist")
except Exception as e:  # noqa: BLE001
    print(f"bars_intraday query failed: {e}")

print("\n=== alt_data indexes (the 4 btrees) ===")
for r in q(
    """
    SELECT indexrelname, pg_size_pretty(pg_relation_size(i.indexrelid)) AS sz
    FROM pg_stat_user_indexes i WHERE relname = 'alt_data'
    ORDER BY pg_relation_size(i.indexrelid) DESC
    """
):
    print(f"    {r[0]:40} {r[1]:>10}")

cur.close()
conn.close()
print("\n# done (read-only)")
