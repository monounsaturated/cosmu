-- Migration: the AUTHORITY feature — PROPRIETARY DATA, not a strategy (see cosmu/authority/). A lean store of
-- (mostly Twitter) accounts + a COMPOSITE authority score derived from whether each account's past directional
-- asset CALLS corroborated the later tape. A high-score account LATER powers an LLM strategy that obeys its
-- signals — that is a SEPARATE lane (out of scope here); this only SCORES (it never funds or fires an order).
--
-- Two additive tables. Apply in the Supabase SQL editor (Postgres applies migrations OUT-OF-BAND); both reads
-- are DEFENSIVE in code (a DB without these tables yields the honest empty state, never a 500), so deploying the
-- code before applying this migration is safe.
--
--   authority_calls       the deduped RAW corpus of account calls the data-agnostic ingest seam fills (a
--                         pasted/JSON dump, an xAI/Grok fetch, a Claude-in-Chrome scrape). The LLM only EXTRACTS
--                         this shape; the composite score downstream is PURE MATH (no hallucination on the number).
--   authority_scoreboard  ONE flat composite row per account — the dashboard surface, served PRECOMPUTED (never a
--                         live recompute on the request path). UNTESTED accounts (no resolved calls yet) carry
--                         NULL metrics, never a fabricated 0.
--
-- This REPLACES the retired autonomous voice-panel / citation-PageRank machinery (cosmu/ingest/voices_pass.py,
-- now quarantined; its voice_claims/voice_scoreboard tables are left in place, no longer written).

create table if not exists authority_calls (
  id bigserial primary key,
  account text not null,
  platform text not null,
  asset text not null,                       -- UPPERCASE ticker the call is about
  direction text not null,                   -- up | down | flat
  ts text not null,                          -- when the call was MADE == availability (PIT, UTC ISO)
  conviction double precision not null default 0.5,
  call_id text not null default '',          -- stable per-platform id (tweet id / url) — dedup
  text text not null default '',             -- verbatim call (provenance / display only — NEVER scored)
  url text not null default '',
  source text not null default 'manual',     -- json | xai | chrome | manual
  ingested_at text not null,
  unique (account, platform, call_id, asset, direction, ts)
);
create index if not exists idx_authority_calls_account on authority_calls (account, ts);

create table if not exists authority_scoreboard (
  account text not null,
  platform text not null,
  n_calls integer not null default 0,        -- calls attributed (volume, NOT skill)
  n_resolved integer not null default 0,     -- calls old enough to be scored against the tape
  n_echo integer not null default 0,         -- of the resolved, how many were late/echo (discounted)
  hit_rate double precision,                 -- fraction of resolved calls that were right
  base_hit_rate double precision,            -- unconditional base rate over the same horizon
  brier double precision,                    -- mean Brier of conviction forecasts (lower = better)
  brier_skill_score double precision,        -- >0 beats the base rate; <=0 does not
  calibration_error double precision,        -- expected calibration error (0 = perfectly calibrated)
  ev double precision,                       -- cumulative return trading each call small (the payoff headline)
  avg_move_when_right double precision,      -- mean |move| on correct calls (magnitude)
  avg_lead_days double precision,            -- foresight: days the call led the confirmed move
  consistency double precision,              -- [0,1] gain spread; low = one spike carries the account
  composite double precision,                -- [0,1] headline authority score
  top_movers text not null default '[]',     -- JSON: the top-3 calls by payoff
  last_call_ts text,
  updated_at text not null,
  primary key (platform, account)
);
