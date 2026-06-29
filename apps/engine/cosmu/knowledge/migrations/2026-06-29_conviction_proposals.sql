-- Migration: the AUTHORITY-CONVICTION review queue — propose-only conviction trade proposals built from a
-- high-authority account's fresh asset-call (cosmu/conviction). Additive, idempotent, forward-only. Brings an
-- EXISTING prod Postgres (Supabase) up to the shape schema.sql / schema_postgres.sql now declare; local
-- SQLite/tests get this directly from schema.sql.
--
-- WHY: the Authority feature SCORES accounts by whether their asset-calls precede price moves. This table is the
-- CONSUMER's output: when a followed account (authority composite above threshold) posts a fresh, actionable,
-- non-echo directional call, the producer (out-of-band, in the voices pass) sizes a capped conviction bet and
-- upserts ONE row here for a HUMAN to review + arm. Sizing is authority × EV (profit > hit-rate); the max-loss is
-- always <= the lane's hard cap.
--
-- SAFETY: this lane is PROPOSE-ONLY. `status` is 'proposed' — nothing in the conviction lane arms a proposal or
-- moves money; arming is a separate, explicit human action off this path. The table is out of any LLM's reach and
-- never gates or funds anything on its own.
--
-- Schema-probe gated (knowledge/store.conviction_proposals_available): a pre-migration prod has NO such table, so
-- the producer's upsert NO-OPS and the /conviction API serves the honest-empty queue — byte-identical to before
-- this change. Apply this in the Supabase SQL editor (Postgres schema is applied out-of-band; see
-- knowledge/store.py::migrate), then redeploy Modal so the voices pass starts producing proposals.

CREATE TABLE IF NOT EXISTS conviction_proposals (
  proposal_id TEXT PRIMARY KEY,
  account TEXT NOT NULL,
  asset TEXT NOT NULL,
  direction TEXT NOT NULL,           -- 'long' | 'short'
  size_usd NUMERIC NOT NULL,
  max_loss_usd NUMERIC NOT NULL,
  authority_score REAL NOT NULL,
  expiry TEXT NOT NULL,
  thesis TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'proposed',
  source TEXT NOT NULL DEFAULT 'authority-conviction',
  evidence TEXT NOT NULL,            -- JSON: the AuthorityEvidence (composite + EV + top-3 movers + source post)
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conviction_proposals_authority ON conviction_proposals(authority_score DESC);
