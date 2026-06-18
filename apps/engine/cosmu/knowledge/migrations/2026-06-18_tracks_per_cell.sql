-- Migration: tracks become BRUT per-cell (2026-06-18). NOT YET APPLIED — holds for the operator.
--
-- The brut per-combo gate funds one tradeable cell at a time — a triple (strategy_version × symbol × venue), each
-- judged AND forward-tested on its OWN data, never pooled across symbols, never compared to siblings. A `tracks`
-- row is one cell's forward-proof, so the table grows two cell columns and the old UNIQUE(strategy_version_id) —
-- which capped a version at ONE track — is replaced by a per-CELL UNIQUE so a version can hold one track per
-- passing cell. The per-cell forward-proof readers (master/live_eligibility) + the auto-defund (master/drift)
-- PROBE the live `tracks` schema: PRE-migration (no cell columns) they key by version only — byte-for-byte the
-- pre-brut path, so prod keeps working with this migration HELD; POST-migration they key STRICTLY by the cell
-- ref_id `<version>:<symbol>:<venue>` with NO version-only fallback (so a fresh cell with no own history never
-- inherits a coexisting legacy version-only series as its own forward P&L / live-proof). Because the fallback is
-- dropped once the columns exist, this migration must ALSO re-key the existing version-only forward proof
-- (portfolio_snapshots scope='track' + events kind='track_opened') to the cell key (steps 5-6), or each legacy
-- cell would lose its own forward history the instant the columns go live.
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

-- 5. RE-KEY the legacy version-only FORWARD PROOF to the cell key. Before brut, each track's forward trajectory
--    (portfolio_snapshots scope='track') and its proven-regime passport + clock origin (events kind='track_opened')
--    were keyed by the bare strategy_version_id. The brut readers (master/live_eligibility._ref_ids,
--    master/drift.track_return_series) key a cell STRICTLY by its cell ref_id `<version>:<symbol>:<venue>` once the
--    cell columns exist (NO version-only fallback — that fallback would let a fresh cell INHERIT a coexisting
--    legacy version-only series as its own forward P&L / live-proof). So the existing version-only rows MUST be
--    re-keyed here, the SAME shape the code writes (cohort.py / live_eligibility.cell_id: `vid:symbol:venue_id`),
--    or each legacy cell would silently lose its own forward history the instant the cell columns go live.
--
--    Source of the (symbol, venue) is the row's OWN track, just backfilled in step 2 — so the re-key is exact and
--    self-consistent with the tracks rows the readers match on. Only rows whose ref_id is STILL the bare version
--    (the legacy shape) and whose track now carries non-NULL symbol/venue_id are touched; after the rewrite the
--    ref_id contains ':' and no longer equals the version, so re-running is a no-op (idempotent). A version with no
--    backfilled cell (multi-symbol / position-less — left version-wide in step 2) is intentionally NOT re-keyed:
--    it stays a legacy version-wide series the readers still resolve via the version-only path (symbol/venue None).

UPDATE portfolio_snapshots ps SET ref_id = t.strategy_version_id || ':' || t.symbol || ':' || t.venue_id
FROM tracks t
WHERE ps.scope = 'track'
  AND ps.ref_id = t.strategy_version_id           -- still the legacy version-only key
  AND t.symbol IS NOT NULL AND t.venue_id IS NOT NULL;

-- 6. Same re-key for the proven-regime passport + paper-clock origin events (kind='track_opened'), so a legacy
--    cell keeps BOTH its forward returns (step 5) AND its regime/clock proof under the cell key the readers use.
UPDATE events e SET ref_id = t.strategy_version_id || ':' || t.symbol || ':' || t.venue_id
FROM tracks t
WHERE e.kind = 'track_opened'
  AND e.ref_id = t.strategy_version_id            -- still the legacy version-only key
  AND t.symbol IS NOT NULL AND t.venue_id IS NOT NULL;
