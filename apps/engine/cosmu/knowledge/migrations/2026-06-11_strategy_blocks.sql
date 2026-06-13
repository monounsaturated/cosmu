-- Migration: building-block registry tables (2026-06-11). Additive only — no existing rows touched.
-- How to apply: run in the Supabase SQL editor. Idempotent. Until applied, the deployed engine
-- detects the tables are absent (knowledge/block_registry.blocks_available) and the registry
-- cleanly no-ops: cohorts run exactly as before, with no dedup and no block lineage.
create table if not exists strategy_blocks (
  block_hash text primary key,
  kind text not null,
  label text not null,
  payload text not null,
  first_seen text not null
);
create table if not exists version_blocks (
  strategy_version_id text not null,
  block_hash text not null,
  kind text not null,
  primary key (strategy_version_id, block_hash)
);
create table if not exists version_combos (
  strategy_version_id text primary key,
  combo_hash text not null,
  created_at text not null
);
create index if not exists idx_version_blocks_hash on version_blocks(block_hash);
create index if not exists idx_version_combos_hash on version_combos(combo_hash);
