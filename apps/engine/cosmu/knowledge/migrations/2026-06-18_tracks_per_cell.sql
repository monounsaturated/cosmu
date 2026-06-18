-- Migration: tracks become BRUT per-cell (2026-06-18). NOT YET APPLIED — holds for the operator.
--
-- The brut per-combo gate funds one tradeable cell at a time — a triple (strategy_version × symbol × venue), each
-- judged AND forward-tested on its OWN data, never pooled across symbols, never compared to siblings. A `tracks`
-- row is one cell's forward-proof, so the table grows two cell columns and the old UNIQUE(strategy_version_id) —
-- which capped a version at ONE track — is replaced by a per-CELL UNIQUE so a version can hold one track per
-- passing cell. The per-cell forward-proof readers (master/live_eligibility) + the auto-defund (master/drift)
-- key off (version, symbol, venue) with a version-only LEGACY fallback, so pre-migration version-wide rows stay
-- valid (symbol/venue_id NULL).
--
-- Additive + idempotent. Postgres flavour (prod). DO NOT APPLY TO PROD from this branch — author only.

-- 1. Cell columns (nullable → legacy version-wide rows remain valid; the readers fall back to the version key).
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS symbol TEXT;
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS venue_id TEXT;

-- 2. Backfill each existing track's cell from the version's funded position. Recover the REAL catalog venue from
--    the instrument id (order-path fills persist venue='sim', a ledger label that is NOT a catalog venue): the
--    instrument id is kebab `<symbol-parts>-<venue>` (e.g. btc-usdt-binance), so the venue is the segment AFTER
--    the LAST '-'. symbol comes straight off the position. Only backfills rows still NULL (idempotent), and only
--    when the version holds exactly one symbol (the pre-brut invariant — one track per version), so the backfill
--    can never mis-pair a multi-symbol version. A track with no position is left NULL (legacy version-wide).
UPDATE tracks t SET
    symbol = p.symbol,
    venue_id = substring(p.instrument_id from '[^-]+$')
FROM (
    SELECT strategy_version_id, MIN(symbol) AS symbol, MIN(instrument_id) AS instrument_id
    FROM positions
    WHERE strategy_version_id IS NOT NULL
    GROUP BY strategy_version_id
    HAVING COUNT(DISTINCT symbol) = 1
) p
WHERE t.strategy_version_id = p.strategy_version_id
  AND t.symbol IS NULL AND t.venue_id IS NULL;

-- 3. Drop the version-wide UNIQUE so a version can hold one track per cell. The constraint Postgres auto-named
--    when the column was declared `unique` is <table>_<col>_key. IF EXISTS keeps this a no-op when already dropped.
ALTER TABLE tracks DROP CONSTRAINT IF EXISTS tracks_strategy_version_id_key;

-- 4. The per-CELL UNIQUE: one track per (version, symbol, venue). Postgres treats NULLs as distinct, so legacy
--    version-wide rows (symbol/venue_id NULL) never collide with each other or with cell rows.
CREATE UNIQUE INDEX IF NOT EXISTS uq_tracks_cell ON tracks(strategy_version_id, symbol, venue_id);
