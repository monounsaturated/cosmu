-- Migration: stage vocabulary forward_test → paper (operator decision, 2026-06-11).
-- Reverses the STAGE half of 2026-06-03_tracks_rename.sql ('paper' is the stage name again).
-- The MONEY-STATE half of that migration is untouched: positions.venue stays 'sim'/'live',
-- executions.is_paper stays the "this fill was simulated" boolean — those are orthogonal concepts.
--
-- How to apply: run in the Supabase SQL editor (migrations are applied by hand — see the arm modules'
-- "not-yet-applied migration" notes). Idempotent: every statement is a no-op on re-run.
-- Until this runs, deployed readers tolerate both values (status IN ('paper', 'forward_test', ...)).

UPDATE strategy_versions SET status = 'paper' WHERE status = 'forward_test';

-- Event/recommendation kinds: history keeps meaning, vocabulary follows the stage.
UPDATE events SET kind = 'paper_promotion_watch' WHERE kind = 'forward_test_promotion_watch';
UPDATE recommendations SET kind = 'paper_promotion_watch' WHERE kind = 'forward_test_promotion_watch';
UPDATE events SET kind = 'paper_stepped' WHERE kind = 'forward_stepped';
