-- Migration: the UNIVERSAL PRICE LAYER alignment ledger (Stage 0 — reference resolver + cross-venue check).
-- price_alignment persists ONE inspectable UNIFY/FALLBACK verdict per (canonical pair × venue), with the two
-- stats it was decided from (Pearson corr of bar RETURNS + median |relative close-spread| in bps) and the
-- shared-bar overlap count. UNIFY ⇒ that venue's (strategy × symbol × venue) cell reuses the pair's SINGLE
-- reference series (price computed once, per-venue fee/depth overlaid) — the de-collapse of the venue axis.
-- FALLBACK ⇒ the venue keeps its OWN bars (the SAFE default; a false-unify is a leakage bug upstream of the Gate).
-- Persisted (not recomputed per screen run) so the decision is queryable + auditable per (pair, venue).
-- Additive + idempotent: CREATE TABLE IF NOT EXISTS, no data loss, no cascade. Safe before or after deploy.
create table if not exists price_alignment (
  id text primary key,                          -- "pair:venue", e.g. "BTC/USDT:kraken"
  pair text not null,                           -- canonical pair, e.g. "BTC/USDT"
  venue text not null,
  verdict text not null,                        -- UNIFY | FALLBACK
  corr numeric not null default 0,              -- Pearson corr of bar RETURNS on the common timestamps
  median_spread_bps numeric not null default 0, -- median |relative close-spread| (bps) on the common timestamps
  n_overlap integer not null default 0,         -- shared-bar count behind the two stats
  decided_at text not null
);
create index if not exists idx_price_alignment_pair on price_alignment(pair);
create index if not exists idx_price_alignment_verdict on price_alignment(verdict);
