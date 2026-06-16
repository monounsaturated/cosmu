-- Reclassify the legacy 'validating' orphan(s).
--
-- 'validating' was a NON-CANONICAL status written ONLY by the spine demo lane (_ensure_sample_strategy), which
-- had no transition-out path — so a gate-FAILED demo version ("Funding-aware BTC swing") sat there for 13 days
-- instead of being killed. The spine now writes 'killed' on gate failure directly (see spine/engine.py), so this
-- migration only cleans up rows created before that fix. Applied by hand in Supabase, same convention as
-- 2026-06-11_forward_test_to_paper.sql. Idempotent + safe to re-run.
--
-- Canonical lifecycle vocabulary (single source of truth): see cosmu/knowledge/lifecycle_status.py —
-- {screened, paper, live, killed}. 'validating' is not in it.

-- Gate-FAILED orphans → killed (terminal), mirroring finder.py / evolution/loop.py kill-on-fail.
UPDATE strategy_versions
   SET status = 'killed',
       kill_reason = COALESCE(kill_reason, 'legacy_validating_gate_fail'),
       killed_at = COALESCE(killed_at, now()::text)
 WHERE status = 'validating'
   AND id IN (SELECT b.strategy_version_id FROM backtests b WHERE b.passed_gates = 0);

-- Any remaining 'validating' row WITHOUT a failing backtest (none expected today) → 'screened' so it is at
-- least canonical and re-enters the funnel rather than sitting in a dead state.
UPDATE strategy_versions SET status = 'screened' WHERE status = 'validating';
