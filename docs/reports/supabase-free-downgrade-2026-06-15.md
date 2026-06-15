# Supabase Pro→Free downgrade — ground-truth verdict (2026-06-15)

> **Supersedes** the earlier cloud-agent analysis, which was built on the stale 2026-06-13 baseline (6.58 GB DB,
> "you must TRUNCATE before downgrading"). That premise is **obsolete and its TRUNCATE recommendation would have
> broken production.** Numbers below are measured live against prod Postgres + the R2 lake (scripts in
> `scripts/ops_*.py`).

## TL;DR
- **Fits Free today, no purge needed.** Live DB is **282 MB** vs the 500 MB Free cap (44 % headroom). The big
  prune (13.6M → 880k `alt_data` rows) already happened — the cloud agent's 6.5 GB is two days dead.
- **Do NOT prune `alt_data` to "make room."** It's unnecessary (already fits) **and currently unsafe** — the
  live read path still reads `alt_data` from Postgres, and no committed code reads the fresh lake.
- **Not yet *sustainably* under the cap.** Ingest still writes `alt_data` to PG and there is **no committed
  age-out cron**, so the table regrows toward GB-scale and will breach 500 MB again.
- **The one real Free blocker (no managed backups) is now solved** — a self-managed `pg_dump → R2` backup is
  built and ran (`scripts/ops_backup_pg_to_r2.py`).

## Measured ground truth (live, 2026-06-15)
| | value |
|---|---|
| **DB total** | **282 MB** (< 500 MB Free cap) |
| `alt_data` heap+idx | 256 MB / **879,754 rows** (was 13.57M / 6.55 GB on 06-13) |
| control plane (30 tables) | **15.5 MB** / 31,651 rows |
| DuckLake catalog (`ducklake_*` in PG) | live, ~1 MB |
| `bars_intraday` | **does not exist** (cloud agent's auto-pause/growth worry is moot) |

## R2 lake parity — PROVEN (the data IS safe in the cold tier)
`r2://cosmu-lake/alt_lake/` (DuckLake), 61 files / **13,585,215 rows** / 71.8 MB, latest snapshot **06-15 14:18 UTC**.
- Aggregate: **every** PG `(provider, metric)` series exists in the lake; none short; none stale; both share the
  same `available_at` frontier (2026-06-14). Lake is a strict superset (13.585M ⊇ 880k).
- Row-level: sampled 6 series (incl. `lunarcrush/social_volume`, exact-match `binance/funding_rate`
  92,703 = 92,703, and three singletons) → **PG ⊆ lake** on `(ts, available_at, value)` in every case.
- The "was-DOUBLE" fear is fixed (13.585M ≈ expected, not 2×).

## Why a prune is unsafe on what's DEPLOYED right now
The supporting code is **already built + tested** — but it lives on an **unpushed branch**
`claude/competent-bartik-4f728e` (7 commits `1cec5ab`→`11da0b7`, ~370 tests green): `ducklake_store.py`,
`tiered_store.py`, `age_out.py`, `resolve_alt_store` routing `pg/parquet/ducklake/tiered`, the weekly Modal
maintenance cron, **and a money-path `COLLATE "C"` look-ahead fix** (`0bdce0d`). It is NOT on `main` and NOT on
Railway. So on *deployed* prod:
1. **Backend is `pg`.** `alt_data.ingested_at` max = **06-14 16:02**; Railway ingest writes to Postgres, which is
   the live read path for the gate/finder/sweep.
2. **The only committed parquet reader points at the WRONG (stale) prefix.** `main`'s `ParquetAltDataStore` globs
   `r2://cosmu-lake/alt_data/...` — the *old* Phase-1 hive export frozen at **06-13 17:12**, not the fresh
   `alt_lake/` DuckLake. The DuckLake reader that *does* read `alt_lake/` is on the unpushed branch.

→ `TRUNCATE alt_data` against deployed prod would silently blind every alt-data strategy: PG reads go empty and
the fresh lake is unreachable from `main`'s code. (The one-time backfill+prune that already shrank the DB to
282 MB was run from the unpushed branch's code via Modal — it does not mean prod can *read* the lake.)

## The real path to a *durable* Free downgrade
The hard work is done; the gating action is a **push + deploy**, not new code:
1. **Push `claude/competent-bartik-4f728e`** (operator action — push = deploy; it ships the tiered/DuckLake
   reader, the weekly age-out maintenance cron, AND the `COLLATE "C"` money-path correctness fix to Railway). CI
   runs `verify`; watch the deploy.
2. **Confirm the weekly Modal `cold_tier_maintenance` cron actually fires** — it's defined on the branch as
   `modal.Cron("0 6 * * 1")` (Mon 06:00 UTC) and a `cosmu-engine` Modal app is **deployed** (today 14:51 UTC), so
   it should be live; verify next Monday's run executes (Modal dashboard / run logs). This cron — not the git
   push — is what keeps PG `alt_data` a bounded ~90d hot window so the 500 MB cap can't creep back. *If it isn't
   running, PG regrows toward GB-scale.*
3. **Self-managed daily `pg_dump → R2`** — done (see below); schedule it as a cron.
4. **Switch the plan to Free.** No further prune needed — the steady state already keeps the DB tiny.

Until step 1 lands, you *can* sit on Free at 282 MB, but PG `alt_data` will regrow with ingest unless the Modal
maintenance cron is confirmed live (step 2) — that cron, not the git push, is what bounds the table.

## Free-tier risk table (what actually changes)
| Free limit | actual | verdict |
|---|---|---|
| DB 500 MB | 282 MB now, **but regrows** (no age-out) | ⚠️ fits today, not sustainable yet |
| File storage 1 GB | 0 (no Supabase Storage buckets) | ✅ irrelevant |
| 50k MAU | 0 (connect via `DATABASE_URL`, no Supabase Auth) | ✅ irrelevant |
| auto-pause after 7d idle | always-on Railway engine keeps it active | ⚠️ low risk; manual restore if a long outage |
| **no managed backups** | **solved**: `pg_dump → R2` | ✅ self-managed |
| 5 GB egress/mo | control-plane reads only | ✅ fine |

## Backup artifact (created this session)
`scripts/ops_backup_pg_to_r2.py` → custom-format `pg_dump`, **excludes the 256 MB `alt_data` rows** (in the lake,
keeps its schema+indexes), includes the DuckLake catalog + all money-truth tables.
- First run: **1.02 MB** → `r2://cosmu-lake/backups/pg/cosmu_pg_20260615T153123Z.dump` (verified).
- Restore: `pg_restore --no-owner --clean --if-exists -d '<session DSN :5432>' <file>` (alt_data restores empty;
  rehydrate from the lake / re-ingest).

## Housekeeping flagged (not done — needs a call)
- **Stale `alt_data/` R2 prefix** (66.9 MB, 06-13) is superseded by `alt_lake/`, but it's the target the
  *committed* `ParquetAltDataStore` reads — deleting it removes the only thing the committed parquet backend can
  read. Resolve as part of step 1 (repoint the reader), not before.
