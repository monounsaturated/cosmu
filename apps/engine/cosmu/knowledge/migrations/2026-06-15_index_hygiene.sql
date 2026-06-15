-- 2026-06-15 · index hygiene for the Supabase→R2 cold-tier migration.
-- Applied OUT-OF-BAND in the Supabase SQL editor (the Postgres schema is hand-applied; store.migrate() only
-- ensures the live_toggle singleton). Mirrors schema_postgres.sql / schema.sql so a fresh DB matches prod.
-- Non-destructive + idempotent (IF [NOT] EXISTS). Reclaims index bloat and adds two missing indexes.

-- 1) idx_alt_data_lookup (provider, symbol, metric, available_at) is a strict LEFT-PREFIX of the unique index
--    uq_alt_data_pit (provider, symbol, metric, ts, available_at), which already serves read_asof's per-series
--    scan. Dropping it reclaims a large slice of alt_data's index bloat (indexes ~1.4x the heap) at zero read cost.
drop index if exists idx_alt_data_lookup;

-- 2) No dedicated funding index: _funding_rate_asof uses the uq_alt_data_pit equality prefix (provider, symbol,
--    metric) to reach a small per-symbol set, then sorts COLLATE "C" — fast; an en_US index can't serve a
--    COLLATE "C" order anyway. (Left intentionally absent.)

-- 3) Unindexed foreign key: strategy_versions.strategy_id references strategies(id) with no index, so
--    strategies→versions joins / lineage walks seq-scan. (Postgres does NOT auto-index FKs.)
create index if not exists idx_strategy_versions_strategy on strategy_versions (strategy_id);

-- 4) alt_data is append-heavy and will see a retention DELETE; tighten autovacuum so dead tuples are reclaimed
--    promptly to the free-space map (keeps bloat bounded without a VACUUM FULL — pg_repack is unavailable on Supabase).
alter table alt_data set (autovacuum_vacuum_scale_factor = 0.02, autovacuum_analyze_scale_factor = 0.01);

-- 5) Watermark table for the incremental alt_data→DuckLake mirror (cosmu.data.age_out.sync_to_lake).
create table if not exists alt_lake_watermark (k text primary key, last_available_at text not null);
