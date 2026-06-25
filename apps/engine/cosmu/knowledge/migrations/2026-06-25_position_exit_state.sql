-- Migration: per-position EXIT STATE for the paper executor's multi-TP / break-even / runner-trail / standalone
-- trailing-stop / funding parity with the backtest.
--
-- The backtest exit engine (cosmu/data/backtest.py::_run_symbol) is a single in-memory loop that carries mutable
-- per-position state across bars: the live trailing stop level, whether tp1 has filled, which multi-TP legs have
-- filled, the favourable extreme since entry, and the cumulative funding accrued. The PAPER executor
-- (orchestrator/paper_step.py) is STATELESS across ticks — it reconstructs everything from `positions` /
-- `executions` each tick — so without somewhere to persist that runner state it cannot mirror the multi-leg exit
-- physics the Gate screened with. This table is that store, keyed by the same (version, instrument, venue) a
-- position is keyed by.
--
-- Schema-probe gated (knowledge/store.positions_has_exit_state): a pre-migration prod table has NO such table, so
-- the executor degrades to the legacy single stop/take/time/signal close (byte-identical to before). Applying it
-- is safe before or after deploy — it only ADDS a table; no existing row or behaviour changes until the executor
-- starts writing rows for tracks whose spec actually carries an exit plan / trailing / atr stop.
CREATE TABLE IF NOT EXISTS position_exit_state (
  -- (strategy_version_id, instrument_id, venue) — the same key a `positions` row carries.
  strategy_version_id TEXT NOT NULL,
  instrument_id TEXT NOT NULL,
  venue TEXT NOT NULL,
  -- The leg this state belongs to: the entry bar timestamp (ISO) of the CURRENT open leg, so a re-entry after a
  -- full close starts fresh state and never inherits the prior leg's trail/legs-filled.
  entry_ts TEXT,
  -- The original opened qty (base units) — the denominator for sizing partial multi-TP legs.
  entry_qty NUMERIC NOT NULL DEFAULT 0,
  -- The live stop level (price). Raised by break-even-after-tp1 and the trailing stops; never loosened.
  stop_price NUMERIC,
  -- Whether the first TP leg has filled (arms break-even / the post-TP1 runner trail).
  tp1_filled INTEGER NOT NULL DEFAULT 0,
  -- JSON list of multi-TP leg indices already filled (so a partial leg fills exactly once).
  legs_filled TEXT NOT NULL DEFAULT '[]',
  -- The favourable extreme (highest high for a long) since entry — the anchor the trailing stops trail behind.
  extreme NUMERIC,
  -- Cumulative funding cash-flow accrued on the open leg (audit / parity; the realized P&L already books it).
  funding_accrued NUMERIC NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (strategy_version_id, instrument_id, venue)
);
