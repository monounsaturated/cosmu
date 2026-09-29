-- Migration: per-symbol VISIBILITY columns on backtests (2026-06-17).
--
-- The backtest already computes per-symbol results (data/backtest.py BacktestResult.per_symbol) then DROPS them,
-- persisting only the POOLED metric — so a real single-symbol edge gets averaged away and is invisible. These
-- columns surface the granular truth the operator asked for ("voir les perfs PnL de chaque stratégie pour chaque
-- symbole, et pas poolé"):
--   best_symbol  = the symbol with the highest OOS return among those tested
--   best_pnl_pct = that symbol's OOS return (fraction, net of fees)
--   per_symbol   = the full {symbol:{return,sharpe,max_drawdown,trades}} JSON
--
-- DISPLAY-ONLY: the deflated POOLED gate (master/scorer.py, master/cohort.py) STILL decides pass/fail — funding
-- the best-of-N symbol would be a multiple-testing hole the gate exists to deflate. Acting on a symbol-specific
-- edge is a separate, DESIGN-FIRST "honest per-symbol gate" (deflate for the N symbols tried). Gate untouched here.
--
-- All nullable: pre-migration rows + non-screen backtest kinds stay valid. Additive, idempotent, no data loss.
ALTER TABLE backtests ADD COLUMN IF NOT EXISTS best_symbol TEXT;
ALTER TABLE backtests ADD COLUMN IF NOT EXISTS best_pnl_pct NUMERIC;
ALTER TABLE backtests ADD COLUMN IF NOT EXISTS per_symbol TEXT;
