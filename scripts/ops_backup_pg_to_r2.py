# intent: Self-managed money-truth backup — the thing you LOSE when Supabase drops to Free (no managed daily
# backups). Dumps the control plane (+ ducklake catalog) as a restorable custom-format pg_dump, EXCLUDING the
# 256 MB alt_data row-data (it lives in the R2 lake, parity-proven), then uploads to R2 + mirrors locally.
# Read-only against PG. Run on a daily cron once on Free. Restore:  pg_restore --no-owner -d "$SESSION_DSN" <file>
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3


def load_env(path: str) -> None:
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env("/Users/device/cosmu/.env.local")

# locate pg_dump (PATH, then homebrew libpq keg)
pgdump = shutil.which("pg_dump")
if not pgdump:
    for cand in Path("/opt/homebrew/Cellar/libpq").glob("*/bin/pg_dump"):
        pgdump = str(cand)
        break
if not pgdump:
    print("pg_dump not found", file=sys.stderr)
    sys.exit(1)

# session DSN (pg_dump needs a session conn, NOT the transaction pooler): 6543 -> 5432, strip query params
raw = os.environ["DATABASE_URL"]
session_dsn = raw.replace(":6543", ":5432").split("?", 1)[0]

stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
out_dir = Path("/Users/device/cosmu/.cosmu/backups/pg")
out_dir.mkdir(parents=True, exist_ok=True)
local_file = out_dir / f"cosmu_pg_{stamp}.dump"

cmd = [
    pgdump, session_dsn,
    "-Fc",                                   # custom format (compressed, pg_restore-able, selective)
    "--no-owner", "--no-privileges",
    "--exclude-table-data=public.alt_data",  # the 256 MB hoard lives in the lake; keep its SCHEMA, skip rows
    "-f", str(local_file),
]
print(f"# pg_dump -> {local_file}")
r = subprocess.run(cmd, capture_output=True, text=True)
if r.returncode != 0:
    print("pg_dump FAILED:\n" + r.stderr, file=sys.stderr)
    sys.exit(1)
size = local_file.stat().st_size
print(f"# dump OK: {size/1e6:.2f} MB")

# upload to R2
acct = os.environ["R2_ACCOUNT_ID"]
s3 = boto3.client(
    "s3", endpoint_url=f"https://{acct}.r2.cloudflarestorage.com",
    aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto",
)
key = f"backups/pg/cosmu_pg_{stamp}.dump"
s3.upload_file(str(local_file), "cosmu-lake", key)
head = s3.head_object(Bucket="cosmu-lake", Key=key)
print(f"# uploaded -> r2://cosmu-lake/{key}  ({head['ContentLength']/1e6:.2f} MB, etag {head['ETag']})")

# list existing backups for retention awareness
print("\n# backups currently in R2 (newest first):")
objs = s3.list_objects_v2(Bucket="cosmu-lake", Prefix="backups/pg/").get("Contents", [])
for o in sorted(objs, key=lambda x: x["LastModified"], reverse=True)[:10]:
    print(f"    {o['Key']}  {o['Size']/1e6:.2f} MB  {o['LastModified']}")

print(f"\n# RESTORE:  pg_restore --no-owner --clean --if-exists -d '<SESSION_DSN :5432>' '{local_file.name}'")
print("# (download from R2 first; this is a control-plane backup — alt_data restores empty, rehydrate from the lake)")
