-- Migration: the hidden-box BLINDING commit — particle-physics discipline for the holdout.
-- Additive — nothing renamed, nothing dropped. Brings an EXISTING prod Postgres (Supabase) up to the shape
-- schema.sql / schema_postgres.sql now declare. Local SQLite/tests get this directly from schema.sql.
-- Apply in the Supabase SQL editor (Postgres schema is applied out-of-band; see knowledge/store.py:migrate).
--
-- WHY: the one-shot `holdout_ledger` makes a held-out set readable ONCE, but it does NOT pin WHAT recipe was
-- being judged when the holdout was first read. So a version's spec can be mutated IN PLACE after its first
-- holdout read (the same version_id keeps its already-spent holdout) — the holdout becomes blind by convention,
-- not construction (cross-disciplinary playbook bridge #3 + red-team #4). `blinding_commits` freezes the RECIPE
-- hash at first read; the deterministic Gate (cosmu/master/blinding.assert_scoreable) refuses to score a version
-- whose recipe_hash drifted past its LATEST commit until a FRESH commit re-blinds it AND re-arms the holdout.
--
-- recipe_hash = sha256 over the SCIENTIFIC spec (entry/exit/universe/horizon/param_space/setup/direction/...) plus
-- the fitted numeric params — administrative labels (name/rationale/lane/kind) are stripped, so a routing relabel
-- (e.g. explore→gate graduation) is NOT a recipe change, but ANY edit to an entry/exit rule or a fitted value is.
--
-- ORDERING: the reader treats a version with NO commit as "never blinded → nothing to violate" (fail-open for
-- the pre-migration backlog), and the writer commits on first holdout read, so code may ship before or after.

create table if not exists blinding_commits (
  id text primary key,
  version_id text not null,
  recipe_hash text not null,
  reason text not null,
  committed_at text not null,
  unique (version_id, recipe_hash)
);

create index if not exists idx_blinding_commits_version on blinding_commits(version_id);
