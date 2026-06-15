-- Migration: the INDEX definition registry (2026-06-15). Additive only — no existing rows touched.
-- How to apply: run in the Supabase SQL editor. Idempotent. Until applied, the deployed engine detects the
-- table is absent (cosmu.indexes.registry.indexes_available) and the /indexes API serves an honest
-- "registry not active yet" state — never a crash, never a fabricated index.
--
-- DEFINITIONS only. Index VALUES are stored point-in-time in the existing alt_data table under
-- provider='index', symbol='MARKET' (market-wide) or the entity, metric=idx_<id>. No new value table.
create table if not exists indexes (
  id text primary key,
  name text not null,
  rationale text not null,
  kind text not null,             -- single_account | social_bucket | event_topic | prompt_rubric
  definition text not null,       -- canonical JSON (handles / topic / prompt)
  entities text not null,         -- canonical JSON list; [] = one MARKET-wide series
  metric text not null,           -- idx_<id>
  market_wide integer not null,   -- 1 = single MARKET series; 0 = per-entity
  transform_version text not null,
  cadence_minutes integer not null,
  status text not null,           -- draft | active | paused
  created_at text not null,
  updated_at text not null
);
create index if not exists idx_indexes_status on indexes(status);
