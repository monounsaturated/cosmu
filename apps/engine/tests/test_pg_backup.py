# Tests for the self-managed pg_dump→R2 backup (cosmu.data.pg_backup). Pure-function + keyless-degradation
# coverage — no Postgres, no R2, no boto3 needed (boto3 is lazy-imported only on the upload path).
from __future__ import annotations

from cosmu.data import pg_backup


def test_pg_dump_argv_is_custom_format_and_excludes_alt_data_rows():
    argv = pg_backup.pg_dump_argv("/usr/bin/pg_dump", "postgresql://u:p@h:5432/db", "/tmp/x.dump")
    assert argv[0] == "/usr/bin/pg_dump"
    assert "postgresql://u:p@h:5432/db" in argv
    assert "-Fc" in argv                                    # custom format → pg_restore-able + selective
    assert "--exclude-table-data=public.alt_data" in argv   # rows live in the lake; schema kept
    assert "--no-owner" in argv and "--no-privileges" in argv
    assert argv[-2:] == ["-f", "/tmp/x.dump"]


def test_backups_to_prune_keeps_newest_and_ignores_non_dumps():
    keys = [f"backups/pg/cosmu_pg_2026010{i}T000000Z.dump" for i in range(1, 8)]  # 7 dumps, oldest→newest
    assert pg_backup.backups_to_prune(keys, keep=3) == keys[:4]      # delete oldest 4, keep newest 3
    assert pg_backup.backups_to_prune(keys[:2], keep=3) == []        # fewer than keep → nothing pruned
    assert pg_backup.backups_to_prune(keys[:3], keep=3) == []        # exactly keep → nothing pruned
    assert pg_backup.backups_to_prune(["backups/pg/_manifest.json"], keep=1) == []  # non-.dump ignored


class _NoCredsSettings:
    database_url = "postgresql://u:p@h:6543/postgres"
    r2_account_id = r2_access_key_id = r2_secret_access_key = r2_bucket = None


class _NonPgSettings:
    database_url = "sqlite:///./.cosmu/cosmu.sqlite3"
    r2_account_id = "acct"
    r2_access_key_id = "key"
    r2_secret_access_key = "secret"
    r2_bucket = "cosmu-lake"


def test_run_backup_skips_without_r2_creds(monkeypatch):
    # keyless degradation: missing R2 creds → no-op success, never shells out to pg_dump
    monkeypatch.setattr(pg_backup, "_find_pg_dump", lambda: (_ for _ in ()).throw(AssertionError("must not run pg_dump")))
    assert pg_backup.run_backup(_NoCredsSettings()) == 0


def test_run_backup_skips_non_postgres_url():
    # creds present but a sqlite DATABASE_URL → skip cleanly (nothing to pg_dump)
    assert pg_backup.run_backup(_NonPgSettings()) == 0
