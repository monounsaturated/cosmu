-- Migration: add the Mind reflections table (additive — nothing renamed, nothing dropped).
-- Brings an EXISTING prod Postgres (Supabase) database up to the schema the Mind needs to persist a
-- point-in-time record of the agent's analyst-panel debate (consensus · conviction · agreement) over time.
-- Local SQLite/tests get this directly from schema.sql; this file is for prod data already on disk.
-- Apply in the Supabase SQL editor (Postgres schema is applied out-of-band; see knowledge/store.py:migrate).
--
-- SAFE TO RUN BEFORE OR AFTER DEPLOY: the engine's reflect() writer is defensive — it records the reflection as
-- an audit event regardless, and only persists this richer row when the table exists. So a deploy that lands
-- before this migration degrades gracefully; running this migration simply turns on the reflection timeline.

create table if not exists mind_reflections (
  id bigint generated always as identity primary key,
  ts text not null,
  as_of text,
  consensus text not null,
  conviction numeric not null,
  agreement numeric not null,
  payload text not null
);

create index if not exists idx_mind_reflections_ts on mind_reflections(ts);
