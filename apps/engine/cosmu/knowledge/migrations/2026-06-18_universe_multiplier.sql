-- Migration: add multiplier column to universe_pairs for futures contract sizing.
-- Futures have a multiplier (USD/EUR per price point per contract) that is CRITICAL for correct
-- position sizing: without it an ES contract ($50/pt × ~4500pt ≈ $225k notional) is sized like a
-- 1-unit equity and the position is over-leveraged by ~225×. The column stores this constant per row
-- at ingest time so the sizing layer can read it without a separate catalog lookup.
-- NULL = spot / equity / perp (unit-qty instruments where notional = qty × price directly).
-- Additive + idempotent: ALTER TABLE … ADD COLUMN IF NOT EXISTS is safe before or after the IBKR
-- universe expansion upsert (existing rows stay valid with NULL; new futures rows set the value).
alter table universe_pairs add column if not exists multiplier numeric;
