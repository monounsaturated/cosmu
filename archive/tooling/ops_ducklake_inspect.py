# intent: READ-ONLY inspection of the DuckLake catalog living in prod Supabase Postgres (the ducklake_* tables)
# and the R2 data files it points at. Answers: what tables/rows are in the cold lake, where the parquet lives,
# how many files + total record_count, and the latest snapshot time. No writes.
from __future__ import annotations

import os
from pathlib import Path

import psycopg2


def load_env(path: str) -> None:
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env("<repo>/.env.local")
dsn = os.environ["DATABASE_URL"].split("?", 1)[0]
conn = psycopg2.connect(dsn, connect_timeout=20)
conn.autocommit = True
cur = conn.cursor()


def q(sql):
    cur.execute(sql)
    return cur.fetchall()


print("=== ducklake_metadata (key/value) ===")
for r in q("SELECT key, value FROM ducklake_metadata ORDER BY key"):
    print(f"  {r[0]:30} = {r[1]}")

print("\n=== ducklake tables cataloged ===")
try:
    for r in q("SELECT table_id, table_name FROM ducklake_table ORDER BY table_id"):
        print(f"  id={r[0]} name={r[1]}")
except Exception as e:  # noqa: BLE001
    print(f"  (ducklake_table missing/err: {e})")

print("\n=== data files: count, total record_count, total bytes, path sample ===")
rows = q("SELECT count(*), COALESCE(SUM(record_count),0), COALESCE(SUM(file_size_bytes),0) FROM ducklake_data_file")
print(f"  files={rows[0][0]}  total_records={int(rows[0][1]):,}  total_bytes={int(rows[0][2])/1e6:.1f} MB")
print("  sample paths:")
for r in q("SELECT path, record_count FROM ducklake_data_file ORDER BY data_file_id LIMIT 8"):
    print(f"    {r[0]}  ({r[1]} rows)")

print("\n=== per-table record_count in the lake ===")
try:
    for r in q(
        """
        SELECT t.table_name, count(f.data_file_id) AS files, COALESCE(SUM(f.record_count),0) AS rows
        FROM ducklake_data_file f JOIN ducklake_table t ON t.table_id = f.table_id
        GROUP BY t.table_name ORDER BY rows DESC
        """
    ):
        print(f"  {r[0]:28} files={r[1]:>4}  rows={int(r[2]):>14,}")
except Exception as e:  # noqa: BLE001
    print(f"  (join failed: {e})")

print("\n=== snapshots (latest 5) ===")
try:
    for r in q("SELECT snapshot_id, snapshot_time FROM ducklake_snapshot ORDER BY snapshot_id DESC LIMIT 5"):
        print(f"  snap {r[0]} @ {r[1]}")
except Exception as e:  # noqa: BLE001
    print(f"  (snapshot err: {e})")

print("\n=== alt_lake_watermark (what the migration thinks is synced) ===")
try:
    cur.execute("SELECT * FROM alt_lake_watermark")
    cols = [d[0] for d in cur.description]
    print(f"  cols: {cols}")
    for r in cur.fetchall():
        print(f"  {r}")
except Exception as e:  # noqa: BLE001
    print(f"  (watermark err: {e})")

cur.close()
conn.close()
