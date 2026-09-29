-- Migration: backtest_symbols — the QUERYABLE per-(strategy,symbol,venue) unit of truth (2026-06-17).
--
-- The backtest computes per-symbol results; PR #306 cached them as a JSON blob on backtests (a display dead-end —
-- can't be sorted/joined/recomputed in SQL). This first-class child table makes (strategy × symbol × VENUE) the
-- unit: one row per backtest×symbol, carrying venue_id (the fee axis). A real single-symbol edge is now visible,
-- joinable, and outlier-sortable, never averaged away by the pooled mean. `verdict` is filled later by the HONEST
-- per-symbol gate (effective-N, robust-not-max); NULL = persisted-but-not-yet-judged.
--
-- The deterministic POOLED Gate (DSR/PBO/BH-FDR, master/scorer.py + cohort.py) stays the locked funding authority
-- — this table is granular VISIBILITY + the fuel for the recompute and the /lab front. Additive, idempotent.
CREATE TABLE IF NOT EXISTS backtest_symbols (
  id TEXT PRIMARY KEY,
  backtest_id TEXT NOT NULL REFERENCES backtests(id),
  strategy_version_id TEXT NOT NULL REFERENCES strategy_versions(id),
  symbol TEXT NOT NULL,
  venue_id TEXT,
  return_pct NUMERIC,
  sharpe NUMERIC,
  max_drawdown NUMERIC,
  trades INTEGER,
  verdict TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_backtest_symbols_version ON backtest_symbols(strategy_version_id);
CREATE INDEX IF NOT EXISTS idx_backtest_symbols_symbol ON backtest_symbols(symbol);
