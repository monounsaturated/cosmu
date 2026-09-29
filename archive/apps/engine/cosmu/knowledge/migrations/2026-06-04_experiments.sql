-- Migration: add the experiments registry table (additive — nothing renamed, nothing dropped).
-- Brings an EXISTING prod Postgres (Supabase) database up to the schema the experiment-tracking hook needs:
-- every finder/gate run logs its exact config + seed + data_version + metrics so any result is COMPARABLE
-- across runs and EXACTLY REGENERABLE, and soft_label carries the continuous forward-P&L so the ML ranker has
-- a gradient before any gate-pass (the binary survival label) exists.
-- Local SQLite/tests get this directly from schema.sql; this file is for prod data already on disk.
-- Apply in the Supabase SQL editor (Postgres schema is applied out-of-band; see knowledge/store.py:migrate).
--
-- SAFE TO RUN BEFORE OR AFTER DEPLOY: the registry hook is defensive — a finder/gate run NEVER fails because
-- the experiments table is absent (the log is best-effort, see experiments/registry.py). A deploy that lands
-- before this migration simply skips the log; running this migration turns the registry on.

create table if not exists experiments (
  id text primary key,
  ts text not null,
  kind text not null,
  source text not null,
  label text,
  seed integer not null,
  data_version text not null,
  code_hash text,
  config text not null,
  metrics text not null,
  soft_label numeric,
  gate_passed integer,
  created_at text not null
);
create index if not exists idx_experiments_kind_ts on experiments(kind, ts);
create index if not exists idx_experiments_data_version on experiments(data_version);
