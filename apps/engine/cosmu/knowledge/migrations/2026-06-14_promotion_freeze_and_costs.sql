-- Migration: the live-replication FREEZE + per-backtest cost assumptions + author provenance.
-- Additive — nothing renamed, nothing dropped. Brings an EXISTING prod Postgres (Supabase) database up to the
-- shape schema.sql / schema_postgres.sql now declare. Local SQLite/tests get these directly from schema.sql.
-- Apply in the Supabase SQL editor (Postgres schema is applied out-of-band; see knowledge/store.py:migrate).
--
-- WHY (three coherent additions, all in service of "go from paper to live, fees correct"):
--   1. backtests.{venue_id,fee_bps,slippage_bps,impact_bps} — the COST ASSUMPTIONS a backtest was scored under.
--      Without them, live reads FRESH fees with no idea what the gate assumed, so a venue repricing silently
--      trades an edge that was never proven at that fee. Nullable; writers (lab/finder, research/*_arm) set them
--      and readers coalesce NULL → unknown (the prior behaviour).
--   2. strategy_promotions — the single FROZEN promotion record. One row per promoted version captures the fitted
--      params + hash, the venue fee model, the data/feature-registry version, the universe, the gate score, and
--      the proven-regime passport. master/promotion.freeze_promotion writes it at every promotion site; live
--      eligibility + the live step read it as the one source of truth (no scattered reconstruction).
--   3. strategy_versions.authored_by — "human" | "agent" | "import" provenance so the flywheel can grade winners
--      by who wrote them. Nullable; pre-migration rows read as unknown.
--
-- ORDERING: the writers set these columns, so APPLY THIS MIGRATION BEFORE (or together with) deploying the
-- matching code. Every reader is defensive (coalesces NULL / treats a missing promotion row as "not frozen"),
-- so nothing errors if the code ships first either.

alter table if exists backtests add column if not exists venue_id text;
alter table if exists backtests add column if not exists fee_bps numeric;
alter table if exists backtests add column if not exists slippage_bps numeric;
alter table if exists backtests add column if not exists impact_bps numeric;

alter table if exists strategy_versions add column if not exists authored_by text;

create table if not exists strategy_promotions (
  id text primary key,
  strategy_version_id text not null unique references strategy_versions(id),
  lane text not null,
  params_hash text not null,
  params text not null,
  feature_registry_version text,
  universe_snapshot text,
  fee_model_snapshot text,
  gate_score text,
  proven_regimes text,
  forward_clock_origin text,
  net_return_pct numeric,
  promoted_at text not null
);

create index if not exists idx_strategy_promotions_version on strategy_promotions(strategy_version_id);
