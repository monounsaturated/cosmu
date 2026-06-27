-- Migration: the HONEST TRIAL-COUNT LEDGER — one row per LOOK the machine ever took, so the Gate's Deflated
-- Sharpe / expected-max-Sharpe deflation can use the TRUE number of trials, not an undercounted one.
--
-- THE FLAW THIS CLOSES (docs/reports/cross-disciplinary-playbook-2026-06-26.md bridge #2 + red-team #1, the
-- "scariest self-deception flaw"): the deployed funding path is BRUT (lab/finder.py + evolution/loop.py →
-- master/cohort.promote_brut). Each (strategy × symbol × venue) cell is deflated only by its OWN per-combo
-- PARAM-grid count (metrics.trials_counted) and the brut path deliberately registers NO global trial. So the N
-- fed into expected_max_sharpe for a survivor EXCLUDES the seeder sweep, the exit-envelope sweep, every cell
-- replayed for a signal family, and abandoned tunes — the Gate is rigorously strict on a DISHONEST, undercounted
-- N (the single most likely way an honest-looking machine self-deceives at scale).
--
-- THIS TABLE is the complete record. The legacy `trials` table (the cohort-FAMILY counter the research/FDR gate
-- reads) is left untouched, so applying this migration changes NO existing gate verdict or funding decision: it
-- only ADDS a table the survivor-realness audit (master/trial_ledger.effective_n / recompute_dsr_at_honest_n)
-- deflates against. The locked Gate CONSTANTS (DSR 0.95 / min-trades / PBO / FDR-q) are unchanged — only N is
-- made honest.
--
-- `family` is the key looks DECORRELATE within (the spec / signal family): a dense correlated grid of one family
-- is NOT K independent tests, so effective_n collapses it via the scorer's correlation haircut N/(1+(N-1)·ρ̄).
-- `rho_bar` is that family's measured average pairwise return correlation (NULL ⇒ unmeasured ⇒ no haircut ⇒
-- counted as full independent trials, the conservative / stricter direction).
--
-- Schema-probe gated (knowledge/store.trial_ledger_available): a pre-migration prod table has NO such table, so
-- every ledger write no-ops (byte-identical to before) until this migration is applied. Append-only; out of any
-- LLM's reach; never gates or moves money on its own.
CREATE TABLE IF NOT EXISTS trial_ledger (
  id INTEGER PRIMARY KEY AUTOINCREMENT,  -- bigint generated always as identity on Postgres
  ts TEXT NOT NULL,
  lane TEXT NOT NULL,                    -- 'finder' | 'farmloop' | 'seeder' | 'exit_sweep' | 'research' ...
  family TEXT NOT NULL,                  -- the signal-family key looks decorrelate within
  symbol TEXT,                           -- the cell's canonical symbol (NULL for a non-cell look)
  venue TEXT,                            -- the cell's venue (NULL for a non-cell look)
  sharpe_per_obs NUMERIC NOT NULL,
  rho_bar NUMERIC                        -- the family's measured avg pairwise return corr (NULL ⇒ no haircut)
);
CREATE INDEX IF NOT EXISTS idx_trial_ledger_family ON trial_ledger(family);
