# intent: the SELF-MANAGED money-truth backup — Supabase's managed daily backups are GONE on the Free plan, so
# this is the safety net. `pg_dump -Fc` of the control plane + DuckLake catalog, EXCLUDING the alt_data ROWS
# (they live in the R2 lake, parity-proven — its schema+indexes ARE kept so a restore recreates the empty table),
# uploaded to r2://<bucket>/backups/pg/ with last-N retention. Runs as the daily_backup Modal cron (the image has
# postgresql-client + boto3 via [ops]); also runnable locally. invariants: READ-ONLY on Postgres (pg_dump only);
# keyless-degrades (no R2 creds / no pg_dump / non-Postgres URL → loud no-op, never crashes a cron) like the rest
# of the data layer. Restore: pg_restore --no-owner --clean --if-exists -d '<session DSN :5432>' <file>.
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from cosmu.config.settings import Settings, get_settings
from cosmu.data.providers.ducklake_store import _pg_catalog_dsn

logger = logging.getLogger("cosmu.data.pg_backup")

_PREFIX = "backups/pg"
_KEEP = 14  # daily backups retained on R2 (~1 MB each; older ones pruned)
_EXCLUDE_DATA = "public.alt_data"  # the 256 MB hoard lives in the lake; keep its SCHEMA, skip the rows


def _find_pg_dump() -> str | None:
    """pg_dump on PATH (the Modal image's postgresql-client), else the homebrew libpq keg (local dev)."""
    found = shutil.which("pg_dump")
    if found:
        return found
    for cand in Path("/opt/homebrew/Cellar/libpq").glob("*/bin/pg_dump"):
        return str(cand)
    return None


def pg_dump_argv(pg_dump: str, session_dsn: str, out_path: str) -> list[str]:
    """The pg_dump command: custom format (pg_restore-able), control-plane only — alt_data ROWS excluded."""
    return [
        pg_dump, session_dsn,
        "-Fc", "--no-owner", "--no-privileges",
        f"--exclude-table-data={_EXCLUDE_DATA}",
        "-f", out_path,
    ]


def backups_to_prune(keys: list[str], keep: int = _KEEP) -> list[str]:
    """Given backup object keys (timestamped `cosmu_pg_<UTC>.dump`, lexically == chronologically sortable), the
    ones to DELETE so only the newest `keep` survive. Ignores non-`.dump` keys (e.g. manifests)."""
    dumps = sorted(k for k in keys if k.endswith(".dump"))
    return dumps[:-keep] if len(dumps) > keep else []


def _r2_client(settings: Settings):  # noqa: ANN202 - boto3 client; lazy import keeps boto3 out of the base deps
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",
    )


def run_backup(settings: Settings | None = None, *, now: datetime | None = None) -> int:
    """Dump → upload → prune. Returns a process exit code (0 ok / skipped, 1 hard failure)."""
    settings = settings or get_settings()
    if not all(
        (settings.r2_account_id, settings.r2_access_key_id, settings.r2_secret_access_key, settings.r2_bucket)
    ):
        logger.warning("pg_backup: R2 creds absent — skipping (keyless degradation).")
        return 0
    dsn = _pg_catalog_dsn(settings.database_url)  # session mode (:5432), query stripped — pg_dump needs a session
    if not dsn.startswith("postgresql://"):
        logger.warning("pg_backup: DATABASE_URL is not Postgres (%s) — skipping.", dsn.split("://", 1)[0])
        return 0
    pg_dump = _find_pg_dump()
    if not pg_dump:
        logger.error("pg_backup: pg_dump not found — install postgresql-client.")
        return 1

    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    bucket, key = settings.r2_bucket, f"{_PREFIX}/cosmu_pg_{stamp}.dump"
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, f"cosmu_pg_{stamp}.dump")
        proc = subprocess.run(pg_dump_argv(pg_dump, dsn, out), capture_output=True, text=True)
        if proc.returncode != 0:
            logger.error("pg_backup: pg_dump failed (rc=%s): %s", proc.returncode, (proc.stderr or "").strip()[:600])
            return 1
        size_mb = os.path.getsize(out) / 1e6
        s3 = _r2_client(settings)
        s3.upload_file(out, bucket, key)
    logger.info("pg_backup: uploaded r2://%s/%s (%.2f MB)", bucket, key, size_mb)

    try:  # retention is best-effort — a failed prune must never fail the backup
        existing = [o["Key"] for o in s3.list_objects_v2(Bucket=bucket, Prefix=f"{_PREFIX}/").get("Contents", [])]
        for stale in backups_to_prune(existing):
            s3.delete_object(Bucket=bucket, Key=stale)
        kept = min(len([k for k in existing if k.endswith(".dump")]), _KEEP)
        logger.info("pg_backup: retention OK — keeping newest %d", kept)
    except Exception as e:  # noqa: BLE001
        logger.warning("pg_backup: retention prune skipped: %s", e)
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    return run_backup()


if __name__ == "__main__":
    sys.exit(main())
