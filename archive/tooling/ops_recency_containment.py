# intent: READ-ONLY. (1) Is PG alt_data still being WRITTEN (ingested_at recency = is backend still 'pg')?
# (2) Row-level containment: for a sample of series, is the PG row-set a SUBSET of the lake row-set
# (ts, available_at, value)? Proves the prune-safety claim beyond aggregate counts.
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
dsn = os.environ["DATABASE_URL"].split("?", 1)[0]

pg = psycopg2.connect(dsn, connect_timeout=20)
pg.autocommit = True
cur = pg.cursor()

print("=== PG alt_data WRITE recency (ingested_at) — is the hot path still writing? ===")
cur.execute("SELECT min(ingested_at), max(ingested_at), count(*) FROM alt_data")
print("  ingested_at min/max/count:", cur.fetchone())
cur.execute(
    "SELECT date_trunc('day', ingested_at::timestamptz) d, count(*) "
    "FROM alt_data GROUP BY 1 ORDER BY 1 DESC LIMIT 7"
)
print("  recent ingest days:")
for r in cur.fetchall():
    print(f"    {r[0]}  {r[1]:,}")

# pick sample series: the biggest + a few small ones
cur.execute("SELECT provider, metric, count(*) FROM alt_data GROUP BY 1,2 ORDER BY 3 DESC LIMIT 3")
big = cur.fetchall()
cur.execute("SELECT provider, metric, count(*) FROM alt_data GROUP BY 1,2 ORDER BY 3 ASC LIMIT 3")
small = cur.fetchall()
samples = big + small

# lake conn
s3 = boto3.client(
    "s3", endpoint_url=f"https://{acct}.r2.cloudflarestorage.com",
    aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto",
)
keys = []
for page in s3.get_paginator("list_objects_v2").paginate(Bucket="cosmu-lake", Prefix="alt_lake/"):
    keys += [o["Key"] for o in page.get("Contents", []) if o["Key"].endswith(".parquet")]
urls = [f"r2://cosmu-lake/{k}" for k in keys]
con = duckdb.connect(":memory:")
con.execute("INSTALL httpfs; LOAD httpfs;")
con.execute("CREATE OR REPLACE SECRET r2 (TYPE r2, KEY_ID ?, SECRET ?, ACCOUNT_ID ?)",
            [os.environ["R2_ACCESS_KEY_ID"], os.environ["R2_SECRET_ACCESS_KEY"], acct])
_arr = "[" + ",".join("'" + u + "'" for u in urls) + "]"
con.execute(f"CREATE OR REPLACE TEMP VIEW lake AS SELECT * FROM read_parquet({_arr}, hive_partitioning=true)")

print("\n=== ROW-LEVEL CONTAINMENT: PG rows NOT present in lake (by ts,available_at,value) ===")
all_ok = True
for prov, met, pc in samples:
    cur.execute(
        "SELECT symbol, ts, available_at, value FROM alt_data WHERE provider=%s AND metric=%s",
        (prov, met),
    )
    pgrows = set((r[0], str(r[1]), str(r[2]), round(float(r[3]), 10)) for r in cur.fetchall())
    lk = con.execute(
        "SELECT symbol, ts, available_at, value FROM lake WHERE provider=? AND metric=?",
        [prov, met],
    ).fetchall()
    lkrows = set((r[0], str(r[1]), str(r[2]), round(float(r[3]), 10)) for r in lk)
    missing = pgrows - lkrows
    status = "OK (PG ⊆ lake)" if not missing else f"!! {len(missing)} PG rows MISSING from lake"
    if missing:
        all_ok = False
    print(f"  {prov}/{met}: pg={len(pgrows):,} lake={len(lkrows):,} -> {status}")
    if missing:
        for m in list(missing)[:3]:
            print(f"       missing sample: {m}")

print("\n=== VERDICT ===")
print(f"  row-level containment across {len(samples)} sampled series: {'ALL PG ⊆ lake' if all_ok else 'FAILURES — see above'}")
cur.close()
pg.close()
