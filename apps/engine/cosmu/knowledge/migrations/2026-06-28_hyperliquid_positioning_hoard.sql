-- Migration: prepare the alt_data store for the Hyperliquid LONG-TAIL POSITIONING forward-hoard
-- (next-data-axis #1, 2026-06-28). ADDITIVE ONLY — nothing renamed, nothing dropped, no data mutated.
--
-- *** NOT APPLIED. The operator applies this in the Supabase SQL editor (Postgres DDL is applied out-of-band;
--     see knowledge/store.py:migrate). It is fully reversible (the index can be dropped; no row is touched). ***
--
-- WHY a migration at all (the rows themselves need NO schema change):
--   The positioning poller writes through the EXISTING alt_data table with the standard
--   (provider, symbol, metric, ts, available_at, value, ingested_at) shape — provider = 'hyperliquid_positioning',
--   symbol = the coin (e.g. 'ZEC'), metric = one of the raw/derived positioning metrics. So no column or table
--   is added; alt_data already absorbs it under the existing uq_alt_data_pit unique index.
--   BUT this is a HIGH-CADENCE forward hoard (≈20 coins × ~10 metrics × up to 6 captures/hr ≈ 1.2k rows/hr) on the
--   Supabase-FREE hot tier. A PARTIAL index scoped to just this provider keeps its point-in-time as-of reads fast
--   (the correlation scan + the BRUT harness query read_asof per (coin, metric)) WITHOUT bloating the global
--   alt_data btree. The cold-tier maintenance cron (cosmu.data.age_out → R2 DuckLake) already ages these rows out
--   of Postgres on the normal ≥90d window, so the hot footprint stays bounded; this index only covers the hot tail.
--
-- SAFE BEFORE OR AFTER DEPLOY: the poller never depends on this index (reads just get slower without it), and the
-- alt_data_provider_summary rollup is refreshed incrementally by the ingest path (best-effort; a failed upsert
-- never aborts a hoard pass). Drop with:  DROP INDEX IF EXISTS ix_alt_data_hl_positioning;

-- Partial index for fast PIT reads of the forward-hoarded positioning series (hot tier only).
-- CONCURRENTLY so it never locks the live alt_data writers (run OUTSIDE a transaction block in the SQL editor).
create index concurrently if not exists ix_alt_data_hl_positioning
  on alt_data (symbol, metric, available_at)
  where provider = 'hyperliquid_positioning';

-- Optional one-time rollup backfill once rows exist (keeps /intelligence + /scores fast for the new provider).
-- Run ONCE manually after the first hoard pass — NOT on the request path:
--
--   insert into alt_data_provider_summary (provider, metric, n_rows, latest_available_at, updated_at)
--   select provider, metric, count(*), max(available_at), now()::text
--   from alt_data where provider = 'hyperliquid_positioning' group by provider, metric
--   on conflict (provider, metric) do update set
--     n_rows = excluded.n_rows,
--     latest_available_at = excluded.latest_available_at,
--     updated_at = excluded.updated_at;
