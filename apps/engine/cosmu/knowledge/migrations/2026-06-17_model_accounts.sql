-- Migration: modular compute-spend registry + failover plumbing (2026-06-17).
--
-- Adds the model_accounts registry (one row per metered model account — e.g. an OpenRouter key with ~$30 free
-- credit), the llm_work_units boundary table (persist-before-issue so a bankroll bust never loses progress), and
-- an account_id column on the llm_calls ledger so spend attributes back to the account that paid.
--
-- key_ref holds the ENV VAR NAME, never the secret — secrets stay in process env, server-side, as everywhere else.
-- spend_used is reconciled from llm_calls; notified_floor is the last $15 stride the operator was pinged at.
--
-- Local SQLite/dev gets this from schema.sql at boot; this file brings an existing prod Postgres (Supabase) up to
-- date. Additive, non-breaking, idempotent — safe to run before or after deploy; no data loss, no cascade.

ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS account_id text;

CREATE TABLE IF NOT EXISTS model_accounts (
  account_id text primary key,
  provider text not null,
  key_ref text not null,
  free_credit_usd numeric not null default 30,
  spend_used numeric not null default 0,
  status text not null default 'active',
  notified_floor integer not null default 0,
  priority integer not null default 0,
  created_ts text not null,
  updated_ts text not null
);

CREATE TABLE IF NOT EXISTS llm_work_units (
  id text primary key,
  ts text not null,
  trace_id text,
  task text not null,
  unit_key text not null,
  status text not null default 'pending',
  account_id text,
  attempts integer not null default 0,
  updated_ts text not null
);
