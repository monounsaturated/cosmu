-- Migration: pooled-wallet rip-out + vocabulary standardization (Lab → Strategies → Forward-test → Live).
-- Brings an EXISTING prod Postgres (Supabase) database to the locked model. Idempotent — safe to re-run.
-- Local SQLite/tests get the new shape directly from schema.sql; this file is for prod data already on disk.
-- Apply in the Supabase SQL editor (Postgres schema is applied out-of-band; see knowledge/store.py:migrate).
--
-- Canonical renames: Sleeve→Track, pooled wallet→standalone tracks, "paper" stage→"forward_test",
-- "paper" money/venue label→"sim", snapshot scope pool→aggregate / sleeve→track. The pooled allocator
-- (allocations table + capped-Kelly cross-strategy sizing) is removed entirely.

-- 1) Per-strategy unit: sleeves → tracks (columns unchanged).
ALTER TABLE IF EXISTS sleeves RENAME TO tracks;

-- 2) Pooled cross-strategy allocator is gone — drop the dead table.
DROP TABLE IF EXISTS allocations;

-- 3) Lifecycle stage value: the dead "paper" stage becomes "forward_test".
UPDATE strategy_versions SET status = 'forward_test' WHERE status = 'paper';

-- 4) Snapshot scopes: the aggregate read-out and the per-track series.
UPDATE portfolio_snapshots SET scope = 'aggregate' WHERE scope = 'pool';
UPDATE portfolio_snapshots SET scope = 'track'     WHERE scope = 'sleeve';

-- 5) Money/venue label on open positions: simulated fills are "sim", not "paper".
UPDATE positions SET venue = 'sim' WHERE venue = 'paper';

-- 6) Audit event kinds renamed alongside the code.
UPDATE events SET kind = 'track_opened'                 WHERE kind = 'sleeve_opened';
UPDATE events SET kind = 'track_defunded'               WHERE kind = 'sleeve_defunded';
UPDATE events SET kind = 'tracks_funded'                WHERE kind = 'wallet_funded';
UPDATE events SET kind = 'tracks_marked'                WHERE kind = 'paper_marked';
UPDATE events SET kind = 'sim_state_reset'              WHERE kind = 'paper_state_reset';
UPDATE events SET kind = 'forward_test_promotion_watch' WHERE kind = 'paper_promotion_watch';

-- 7) Open recommendations carrying the old promotion-watch kind.
UPDATE recommendations SET kind = 'forward_test_promotion_watch' WHERE kind = 'paper_promotion_watch';

-- Note: executions.is_paper (boolean) is intentionally KEPT — it means "this fill was simulated" (== SIM),
-- which is correct and out of the lifecycle-vocabulary surface. live_caps.scope is unrelated cap infra.
