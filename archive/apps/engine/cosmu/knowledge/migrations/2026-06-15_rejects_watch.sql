-- Migration: add the rejects_watch table (additive — nothing renamed, nothing dropped).
-- Brings an EXISTING prod Postgres (Supabase) database up to the schema the REJECTS WATCH-LIST lane needs.
--
-- WHY: the gate is correctly strict (0 survivors = the machine working), but a strict gate has a Type-II /
-- false-negative rate we never measured. The rejects lane is OBSERVE-ONLY: it zero-capital paper-tracks
-- gate-rejected-but-CLOSE candidates (promoted=False AND deflated-Sharpe in [0.90, 0.95) AND survived FDR AND
-- not killed by a critical/risk filter) so we can EMPIRICALLY estimate how often the gate rejects something that
-- would have performed like a survivor. It NEVER changes the gate's pass/fail — a rejects row carries zero
-- capital and is read only for the Type-II report; the money path is untouched.
--
-- One row per (cohort_run, candidate) the rejects lane decided to watch. Zero-capital paper tracking reuses the
-- EXISTING events/tracks/positions tables (a rejects track funds at zero capital and steps via the same SIM
-- path) — this table only records WHICH candidates are on the watch-list and the band evidence that put them
-- there, so the report can join realized paper P&L back to the gate verdict that rejected them.
--
-- Local SQLite/tests get this directly from schema.sql; this file is for prod data already on disk.
-- Apply in the Supabase SQL editor (Postgres schema is applied out-of-band; see knowledge/store.py:migrate).
--
-- SAFE TO RUN BEFORE OR AFTER DEPLOY: persist_rejects_watch is best-effort (a failed write NEVER aborts a gate
-- run — the verdict is already in gate_verdicts), and the report reads honest-empty when the table is absent.

create table if not exists rejects_watch (
  id text primary key,
  cohort_run_id text not null,           -- ties the watched candidate back to its cohort gate run / verdict row
  candidate_id text not null,            -- the gate-rejected candidate (duck-typed Promotion.candidate_id)
  strategy_version_id text,              -- the zero-capital paper track opened for it, if one was funded (else null)
  deflated_sharpe_prob numeric not null, -- the near-miss DSR that landed it in the watch band
  band_min numeric not null,             -- the band that classified it as CLOSE (default 0.90)
  band_max numeric not null,             -- exclusive upper edge (default 0.95)
  net_profit numeric not null default 0, -- the candidate's net-of-cost backtest profit (for the report join)
  reasons text not null default '[]',    -- JSON list: why the gate rejected it (must exclude critical filters)
  created_at text not null,
  unique (cohort_run_id, candidate_id)   -- idempotent: re-running a cohort never double-watches a candidate
);
create index if not exists idx_rejects_watch_cohort on rejects_watch(cohort_run_id);
create index if not exists idx_rejects_watch_version on rejects_watch(strategy_version_id);
