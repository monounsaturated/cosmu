# intent: READ-ONLY parity check between Postgres alt_data (hot) and the R2 DuckLake (cold). Answers the only
# question that gates a prune/downgrade: is the lake a COMPLETE SUPERSET of PG? Compares per-(provider,metric)
# row counts and max(available_at), and flags any PG series/rows the lake is missing (= would be LOST on prune).
from __future__ import annotations

import os
from pathlib import Path

import boto3
import duckdb
import psycopg2


def load_env(path: str) -> None:
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env("<repo>/.env.local")
acct = os.environ["R2_ACCOUNT_ID"]

# --- enumerate the lake's CURRENT files via boto3 (authoritative; matches the 61 catalog rows, no orphans) ---
s3 = boto3.client(
    "s3", endpoint_url=f"https://{acct}.r2.cloudflarestorage.com",
    aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto",
)
keys = []
for page in s3.get_paginator("list_objects_v2").paginate(Bucket="cosmu-lake", Prefix="alt_lake/"):
    keys += [o["Key"] for o in page.get("Contents", []) if o["Key"].endswith(".parquet")]
urls = [f"r2://cosmu-lake/{k}" for k in keys]
print(f"# lake files: {len(urls)}")

# --- read the lake via DuckDB (explicit file list + hive partitioning for provider/metric) ---
con = duckdb.connect(":memory:")
con.execute("INSTALL httpfs; LOAD httpfs;")
con.execute(
    "CREATE OR REPLACE SECRET r2 (TYPE r2, KEY_ID ?, SECRET ?, ACCOUNT_ID ?)",
    [os.environ["R2_ACCESS_KEY_ID"], os.environ["R2_SECRET_ACCESS_KEY"], acct],
)
_arr = "[" + ",".join("'" + u.replace("'", "''") + "'" for u in urls) + "]"
con.execute(f"CREATE OR REPLACE TEMP VIEW lake AS SELECT * FROM read_parquet({_arr}, hive_partitioning=true)")
cols = [r[0] for r in con.execute("DESCRIBE SELECT * FROM lake").fetchall()]
print("# lake columns:", cols)
lk_total = con.execute("SELECT count(*) FROM lake").fetchone()[0]
print(f"# lake total rows: {lk_total:,}")
lk_maxav = con.execute("SELECT max(available_at) FROM lake").fetchone()[0]
print(f"# lake max(available_at): {lk_maxav}")
lake_pm = {
    (r[0], r[1]): (r[2], r[3])
    for r in con.execute(
        "SELECT provider, metric, count(*), max(available_at) FROM lake GROUP BY 1,2"
    ).fetchall()
}

# --- read PG ---
dsn = os.environ["DATABASE_URL"].split("?", 1)[0]
pg = psycopg2.connect(dsn, connect_timeout=20)
pg.autocommit = True
cur = pg.cursor()
cur.execute("SELECT count(*), max(available_at) FROM alt_data")
pg_total, pg_maxav = cur.fetchone()
print(f"\n# PG total rows: {pg_total:,}")
print(f"# PG max(available_at): {pg_maxav}")
cur.execute("SELECT provider, metric, count(*), max(available_at) FROM alt_data GROUP BY 1,2")
pg_pm = {(r[0], r[1]): (r[2], r[3]) for r in cur.fetchall()}

# --- compare ---
print("\n=== PARITY: PG series the lake does NOT fully cover ===")
missing_series = []
short_series = []
stale_series = []  # lake exists but is behind PG on available_at
for (prov, met), (pc, pmax) in sorted(pg_pm.items()):
    if (prov, met) not in lake_pm:
        missing_series.append((prov, met, pc))
        continue
    lc, lmax = lake_pm[(prov, met)]
    if lc < pc:
        short_series.append((prov, met, pc, lc))
    if str(lmax) < str(pmax):
        stale_series.append((prov, met, str(pmax), str(lmax)))

if missing_series:
    print("  !! series in PG but ABSENT from lake (would be LOST on prune):")
    for prov, met, pc in missing_series:
        print(f"     {prov}/{met}  pg_rows={pc:,}")
else:
    print("  OK: every PG (provider,metric) series exists in the lake.")

print("\n=== series where lake has FEWER rows than PG (note: dedup/PIT collapse can explain) ===")
if short_series:
    for prov, met, pc, lc in short_series[:40]:
        print(f"  {prov}/{met}: pg={pc:,} lake={lc:,} (diff {pc-lc:+,})")
    print(f"  ...total short series: {len(short_series)}")
else:
    print("  none")

print("\n=== series where lake's max(available_at) is BEHIND PG (new rows not yet synced) ===")
if stale_series:
    for prov, met, pmax, lmax in stale_series[:40]:
        print(f"  {prov}/{met}: pg_max={pmax} > lake_max={lmax}")
    print(f"  ...total stale series: {len(stale_series)}")
else:
    print("  none — lake is current vs PG on available_at")

print("\n=== SUMMARY ===")
print(f"  lake_total={lk_total:,}  pg_total={pg_total:,}  lake>=pg total: {lk_total >= pg_total}")
print(f"  series missing from lake: {len(missing_series)}")
print(f"  series short in lake:     {len(short_series)}")
print(f"  series stale in lake:     {len(stale_series)}")

cur.close()
pg.close()
