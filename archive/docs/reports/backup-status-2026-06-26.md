# Backup status — Supabase → R2 (2026-06-26)

**Operator question:** "backup supabase sur R2?" — does a recent, restorable backup of the
experiment ledger (the moat) actually exist, given Supabase is on the Free plan with **no managed
backups**?

## Verdict

**YES — backup is fresh AND restorable. NOT a P0.**

- **Newest backup:** `r2://cosmu-lake/backups/pg/cosmu_pg_20260626T050010Z.dump` — **age ≈ 2.0 h**
  at time of check (fired 05:00 UTC today, exactly on the `0 5 * * *` schedule).
- **Format:** PostgreSQL custom-format `pg_dump -Fc` (magic header `PGDMP`), **29.9 MB**.
- **Restorable:** `pg_restore --list` parses it cleanly (exit 0, no errors): **739 TOC entries —
  345 table defs, 172 TABLE DATA segments, 102 indexes, 127 constraints, 17 sequences.**
- **The moat is captured with data:** `strategies`, `strategy_versions`, `gate_verdicts`,
  `backtests`, `backtest_symbols`, `tracks`, `strategy_promotions`, `research_notes`, `events`,
  `runs`, `version_blocks`/`version_combos`, `asset_class_gates` — all present as TABLE DATA.
- **DuckLake catalog backed up too:** all `ducklake_*` catalog tables (`ducklake_data_file`,
  `ducklake_column`, …) are in the dump **with data** — so the R2 Parquet lake stays *readable*
  after a restore (without the catalog the lake's alt_data Parquet would be orphaned).
- **alt_data rows correctly excluded:** the `alt_data` *schema* is in the dump, but there is **no
  `TABLE DATA public alt_data`** entry — by design (`--exclude-table-data=public.alt_data`). The
  256 MB row hoard lives in the R2 lake (parity-proven); a restore recreates the empty table and
  it rehydrates from the lake. Only the tiny `alt_data_provider_summary` rollup carries data.

The single gap is **monitoring** (see Canary), not the backup itself.

## What runs, and proof it is running

| Fact | Evidence |
|---|---|
| Script exists | `apps/engine/cosmu/data/pg_backup.py` (`run_backup`), tested by `apps/engine/tests/test_pg_backup.py`. Local twin: `scripts/ops_backup_pg_to_r2.py`. |
| Scheduled on Modal | `apps/engine/remote/app.py::daily_backup` decorated `@app.function(schedule=modal.Cron("0 5 * * *"), **_HEAVY)`, body `_run(["cosmu.data.pg_backup"])`. |
| Image can dump | `remote/app.py` installs **`postgresql-client-17`** from the PGDG apt repo (Supabase runs PG 17.x; default Debian client is v15 and would be refused) and `pip install '[lake,ops]'` brings `boto3` (R2 upload) + `duckdb`. |
| **Deploy is current** | `modal app history cosmu-engine` → deployed **v15 @ commit `065933b`** (2026-06-25 17:01 CEST), which **is the current `main` HEAD** — so the deployed code contains this `daily_backup` schedule. App state = `deployed`. |
| **Cron actually fired** | R2 shows **14 contiguous daily dumps**, one per day from 2026-06-15 (the Free-downgrade day) through **2026-06-26 today**, all at ~05:00 UTC. No gaps. |
| Retention works | Exactly **14** `.dump` objects retained (`_KEEP = 14` in `pg_backup.py`); older ones are pruned. |

Newest objects in `backups/pg/` (newest first):

```
cosmu_pg_20260626T050010Z.dump  29.94 MB  age  2.0h   <- today, restorable, verified
cosmu_pg_20260625T050004Z.dump  17.15 MB  age 26.0h
cosmu_pg_20260624T050002Z.dump  14.99 MB  age 50.0h
cosmu_pg_20260623T050005Z.dump  12.70 MB  age 74.0h
...  (14 total, contiguous daily, back to 2026-06-15)
cosmu_pg_20260615T163106Z.dump   1.02 MB  age 254.5h  <- first backup, Free-downgrade day
```

Note the dump is **growing 1 MB → 30 MB** over 11 days — consistent with a real, accreting
experiment ledger (not a stuck/empty dump).

## Restore procedure (validated path)

```bash
# 1. download the newest dump from R2
aws s3 cp r2://cosmu-lake/backups/pg/cosmu_pg_<UTC>.dump ./restore.dump   # (S3-compatible client w/ R2 creds)
# 2. restore into a SESSION DSN (:5432, NOT the :6543 transaction pooler — pg_dump/restore need a session conn)
pg_restore --no-owner --clean --if-exists -d '<DATABASE_URL with :5432, query stripped>' restore.dump
# 3. alt_data restores EMPTY by design — rehydrate from the R2 DuckLake lake (catalog is in the dump).
```

`pg_dump`/`pg_restore` must be **v17+** (PG-server-version rule). The Modal image already ships v17;
locally use Homebrew `libpq` (`/opt/homebrew/opt/libpq/bin/pg_restore`).

## The one gap — backup freshness is UNMONITORED (the canary)

The dead-man's-switch `cosmu/ops/heartbeat.py` watches `ingest / tick / mark / exec` — all
**DB-query** signals — but has **no `backup` signal**. If the backup cron silently dies (Modal Free
evicts a schedule, PGDG/`pg_dump` version drift after a base-image bump, R2 creds rotate, Supabase
bumps past PG 17), **nothing pages** — the exact silent-death class the heartbeat exists to catch.
The backup is healthy *today* but its liveness rides on nobody noticing for days.

This is the only follow-up. Low effort, high value: add a `backup` signal to the heartbeat that
probes the **R2 newest-object age** under `backups/pg/`.

### Canary design

- **Signal:** `backup` = hours since the newest object under `r2://<bucket>/backups/pg/*.dump`.
- **Threshold:** **~30 h** (2× the daily cadence — a single missed 05:00 run won't page; a dark
  backup job will). Matches the existing `mark`/`exec` 30 h ceilings.
- **Stale ⇒ page:** missing creds / empty prefix / age > 30 h ⇒ Slack `:red_circle:` once + the
  Modal `heartbeat` run exits non-zero (same contract as the other four signals).
- **Degrade keyless:** if R2 creds are absent, return `None` (treated as stale by `check`) — but in
  prod the `cosmu-engine` secret always carries `R2_*`, so this only no-ops in offline tests, which
  pass `thresholds`/inject to avoid the network. Keep the R2 list-objects call **best-effort**
  (wrap in try/except → `None`) so a transient R2 blip pages rather than crashes the probe.
- **Cadence:** heartbeat already runs hourly (`30 * * * *`) — no new Modal schedule needed (Free
  caps at 5; all 5 slots are used: `ingest`, `heartbeat`, `tick`, `cold_tier_maintenance`,
  `daily_backup`).

### Code sketch (NOT wired — design only)

```python
# cosmu/ops/heartbeat.py

# add "backup" to the ceilings (hours):
DEFAULT_THRESHOLDS_H = {"ingest": 3.0, "tick": 9.0, "mark": 30.0, "exec": 30.0, "backup": 30.0}

def _newest_backup_age_h(settings: Settings, now: datetime) -> float | None:
    """Hours since the newest r2://<bucket>/backups/pg/*.dump. None ⇒ stale (missing/empty/error)."""
    if not all((settings.r2_account_id, settings.r2_access_key_id,
                settings.r2_secret_access_key, settings.r2_bucket)):
        return None  # keyless degradation (offline tests); prod secret always has R2_*
    try:
        import boto3
        s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name="auto",
        )
        objs = s3.list_objects_v2(
            Bucket=settings.r2_bucket, Prefix="backups/pg/"
        ).get("Contents", [])
        dumps = [o for o in objs if o["Key"].endswith(".dump")]
        if not dumps:
            return None
        newest = max(dumps, key=lambda o: o["LastModified"])
        return (now - newest["LastModified"]).total_seconds() / 3600.0
    except Exception:           # transient R2 error ⇒ page (None), never crash the probe
        return None

# in check(), thread settings through and add the signal:
def check(store, *, settings=None, now=None, thresholds=None):
    now = now or datetime.now(UTC)
    settings = settings or store.settings        # Store already carries Settings
    th = {**DEFAULT_THRESHOLDS_H, **(thresholds or {})}
    ages = {
        "ingest": _age_hours(...),
        "tick":   _age_hours(...),
        "mark":   _age_hours(...),
        "exec":   _age_hours(...),
        "backup": _newest_backup_age_h(settings, now),   # NEW — R2 freshness
    }
    stale = {k: ages[k] for k in ages if ages[k] is None or ages[k] > th[k]}
    ...
```

Tests would mirror `test_heartbeat.py`: inject a fake `_newest_backup_age_h` (or a stub S3 lister)
— fresh (2 h) ⇒ silent, stale (40 h) / empty / no-creds ⇒ pages once + exit 1. Offline, no network.

## Bottom line

- **Backup fresh & restorable?** **YES** — newest dump **2.0 h** old, valid `pg_dump -Fc` (739
  TOC entries), moat tables + DuckLake catalog captured with data, alt_data correctly excluded.
- **Gap:** backup liveness is **unmonitored** — no `backup` signal in the heartbeat, so a silent
  cron death would go unnoticed for days. (Not a P0 — the backup IS running; this is defense in
  depth against future silent failure.)
- **Fix:** add the `backup` R2-freshness signal to `cosmu/ops/heartbeat.py` (~30 h threshold) per
  the sketch above — no new Modal schedule, rides the hourly heartbeat.
