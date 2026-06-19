-- Migration: add exposure_factor to tracks (crowding / portfolio concentration cap).
-- exposure_factor = per-cell capital scale in (0, 1], set by the crowding overlay (master/crowding.py) at the
-- capital-allocation stage AFTER the per-combo gate. The crowding detector clusters funded+candidate cells by
-- realized-return correlation; a redundant member of a cluster is vol-scaled DOWN (1/cluster_size) so the
-- cluster deploys ~one cell's worth of capital in aggregate, while the cluster's best representative and every
-- decorrelated cell stay at 1.0. NULL → 1.0 (no cap), the back-compatible default. The paper/live executor
-- multiplies the sized fraction by this factor.
-- PORTFOLIO RISK ONLY — never a gate input; the brut per-combo verdict is untouched. Safe before/after deploy:
-- NULL is the no-cap default; no data loss; no cascade.
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS exposure_factor REAL;
