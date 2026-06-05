-- Migration: persist the survival-model feature row on screen backtests + index research_notes by kind.
-- Additive — nothing renamed, nothing dropped. Brings an EXISTING prod Postgres (Supabase) database up to the
-- shape schema.sql / schema_postgres.sql now declare. Local SQLite/tests get these directly from schema.sql.
-- Apply in the Supabase SQL editor (Postgres schema is applied out-of-band; see knowledge/store.py:migrate).
--
-- WHY: the tabular survival ranker (ml/survival.py) reads sharpe_per_obs / skew / kurtosis / n_obs /
-- regime_spread off the screen backtest. They were never persisted, so _labeled_outcomes ZERO-FILLED 4 of 9
-- features and approximated the per-obs Sharpe from the annualized one — the trained model saw a degraded row.
-- These columns let it train on the real feature vector (train-time == serve-time). Nullable: pre-migration
-- rows stay valid and the reader coalesces NULL -> neutral (exactly the old zero-filled behaviour).
--
-- ORDERING: the screen-backtest WRITER (evolution/loop.py, lab/finder.py) now SETS these columns, so on
-- Postgres APPLY THIS MIGRATION BEFORE (or together with) deploying the matching code. The READER is defensive
-- (it falls back to the legacy column set if these are absent), so survival ranking never errors either way.

alter table if exists backtests add column if not exists sharpe_per_obs numeric;
alter table if exists backtests add column if not exists skew numeric;
alter table if exists backtests add column if not exists kurtosis numeric;
alter table if exists backtests add column if not exists n_obs integer;
alter table if exists backtests add column if not exists regime_spread integer;

-- recall()/novelty always filter `where kind = ?` before the vector scan; index the predicate (perf only,
-- no code depends on it existing — safe before or after deploy).
create index if not exists idx_research_notes_kind on research_notes(kind);
