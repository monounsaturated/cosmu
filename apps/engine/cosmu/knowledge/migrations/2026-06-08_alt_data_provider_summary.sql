-- Migration: add the alt_data_provider_summary rollup table (additive — nothing renamed, nothing dropped).
-- Brings an EXISTING prod Postgres (Supabase) database up to the schema the alt-data freshness fast-path needs.
--
-- WHY: /intelligence (data-freshness) and /scores (source-trust) used to GROUP BY over the ~17M-row alt_data
-- table on EVERY request — a full seq-scan that took ~24s / ~22s and timed out the SSR fetch ("Engine not
-- connected"). They now read this tiny per-(provider, metric) rollup (≤ a few hundred rows) instead.
--
-- The rollup is refreshed INCREMENTALLY by the ingest path (an upsert from the just-written rows, never a full
-- re-aggregate). Local SQLite/tests get this directly from schema.sql; this file is for prod data already on disk.
-- Apply in the Supabase SQL editor (Postgres schema is applied out-of-band; see knowledge/store.py:migrate).
--
-- SAFE TO RUN BEFORE OR AFTER DEPLOY: the summary writer is best-effort (a failed upsert NEVER aborts an ingest
-- pass), and the readers fall back to honest-empty when the table is absent. To backfill the rollup from the
-- existing alt_data once, after creating the table, run the one-off aggregate below (commented out by default —
-- it is a single GROUP BY over alt_data, run it ONCE manually, not on the request path):
--
--   insert into alt_data_provider_summary (provider, metric, n_rows, latest_available_at, updated_at)
--   select provider, metric, count(*), max(available_at), now()::text
--   from alt_data group by provider, metric
--   on conflict (provider, metric) do update set
--     n_rows = excluded.n_rows,
--     latest_available_at = excluded.latest_available_at,
--     updated_at = excluded.updated_at;

create table if not exists alt_data_provider_summary (
  provider text not null,
  metric text not null,
  n_rows integer not null default 0,
  latest_available_at text,
  updated_at text not null,
  primary key (provider, metric)
);
