-- Cosmu v2 fresh control-plane schema. Market bars/features live in Parquet, not Postgres.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS venues (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL,
  adapter TEXT NOT NULL,
  fee_schedule TEXT NOT NULL,
  constraints TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS instruments (
  id TEXT PRIMARY KEY,
  venue_id TEXT NOT NULL REFERENCES venues(id),
  symbol TEXT NOT NULL,
  asset_class TEXT NOT NULL,
  tick_size NUMERIC NOT NULL,
  lot_size NUMERIC NOT NULL,
  min_notional NUMERIC NOT NULL,
  listed_at TEXT,
  delisted_at TEXT,
  active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS strategies (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  thesis TEXT NOT NULL,
  origin TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS strategy_versions (
  id TEXT PRIMARY KEY,
  strategy_id TEXT NOT NULL REFERENCES strategies(id),
  parent_id TEXT REFERENCES strategy_versions(id),
  spec TEXT NOT NULL,
  generated_code TEXT NOT NULL,
  code_hash TEXT NOT NULL,
  params TEXT NOT NULL,
  mutation_operator TEXT,
  mutation_rationale TEXT,
  origin TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  killed_at TEXT,
  kill_reason TEXT
);

CREATE TABLE IF NOT EXISTS backtests (
  id TEXT PRIMARY KEY,
  strategy_version_id TEXT NOT NULL REFERENCES strategy_versions(id),
  kind TEXT NOT NULL,
  is_start TEXT,
  is_end TEXT,
  oos_start TEXT,
  oos_end TEXT,
  oos_return NUMERIC NOT NULL,
  sharpe NUMERIC NOT NULL,
  sortino NUMERIC NOT NULL,
  deflated_sharpe NUMERIC NOT NULL,
  max_dd NUMERIC NOT NULL,
  win_rate NUMERIC NOT NULL,
  num_trades INTEGER NOT NULL,
  pbo NUMERIC NOT NULL,
  trials_counted INTEGER NOT NULL,
  regime_label TEXT,
  folds_positive INTEGER NOT NULL,
  passed_gates INTEGER NOT NULL,
  holdout_passed INTEGER NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  strategy_version_id TEXT,
  mode TEXT NOT NULL,
  venue_id TEXT,
  seed INTEGER NOT NULL,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS executions (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES runs(id),
  strategy_version_id TEXT,
  instrument_id TEXT,
  venue_id TEXT,
  side TEXT NOT NULL,
  qty NUMERIC NOT NULL,
  price NUMERIC NOT NULL,
  fee NUMERIC NOT NULL,
  slippage NUMERIC NOT NULL,
  order_type TEXT NOT NULL,
  is_paper INTEGER NOT NULL,
  ts TEXT NOT NULL,
  fill_log TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
  id TEXT PRIMARY KEY,
  scope TEXT NOT NULL,
  ref_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  equity NUMERIC NOT NULL,
  cash NUMERIC NOT NULL,
  positions_value NUMERIC NOT NULL,
  pnl NUMERIC NOT NULL,
  drawdown NUMERIC NOT NULL
);

-- Live/paper open positions per strategy sleeve, marked-to-market by master/portfolio.py. avg_price is the
-- memoryless basis; venue distinguishes paper/testnet/live mechanics. Net-zero rows are kept for audit.
CREATE TABLE IF NOT EXISTS positions (
  id TEXT PRIMARY KEY,
  strategy_version_id TEXT,
  instrument_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  venue TEXT NOT NULL,
  qty NUMERIC NOT NULL,
  avg_price NUMERIC NOT NULL,
  realized_pnl NUMERIC NOT NULL DEFAULT 0,
  last_was_loss INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sleeves (
  id TEXT PRIMARY KEY,
  strategy_version_id TEXT NOT NULL UNIQUE REFERENCES strategy_versions(id),
  starting_capital NUMERIC NOT NULL DEFAULT 100000,
  equity NUMERIC NOT NULL,
  return_pct NUMERIC NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS allocations (
  id TEXT PRIMARY KEY,
  strategy_version_id TEXT NOT NULL REFERENCES strategy_versions(id),
  weight NUMERIC NOT NULL,
  capital NUMERIC NOT NULL,
  kelly_fraction NUMERIC NOT NULL,
  correlation_group TEXT NOT NULL,
  cycle_ts TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS live_toggle (
  id TEXT PRIMARY KEY CHECK (id = 'global'),
  enabled INTEGER NOT NULL DEFAULT 0,
  enabled_at TEXT,
  enabled_by TEXT
);

CREATE TABLE IF NOT EXISTS live_caps (
  id TEXT PRIMARY KEY,
  scope TEXT NOT NULL,
  ref_id TEXT,
  max_notional NUMERIC NOT NULL,
  max_daily_loss NUMERIC NOT NULL
);

CREATE TABLE IF NOT EXISTS skills (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  recipe TEXT NOT NULL,
  grade NUMERIC NOT NULL,
  lineage TEXT NOT NULL,
  success_count INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  pruned_at TEXT,
  embedding TEXT  -- JSON float[]: keyless deterministic embedding for skill-recall priors (pgvector on Postgres)
);

CREATE TABLE IF NOT EXISTS sources (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  uri TEXT,
  raw TEXT NOT NULL,
  extracted TEXT NOT NULL,
  claims TEXT NOT NULL,
  veracity TEXT NOT NULL DEFAULT 'na',
  ingested_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_notes (
  id TEXT PRIMARY KEY,
  strategy_version_id TEXT,
  kind TEXT NOT NULL,
  body_md TEXT NOT NULL,
  structured TEXT NOT NULL,
  created_at TEXT NOT NULL,
  embedding TEXT  -- JSON float[]: keyless deterministic point-in-time embedding for graveyard/research RAG (pgvector on Postgres)
);

CREATE TABLE IF NOT EXISTS recommendations (
  id TEXT PRIMARY KEY,
  ts TEXT NOT NULL,
  kind TEXT NOT NULL,
  body TEXT NOT NULL,
  state TEXT NOT NULL,
  payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS policies (
  id TEXT PRIMARY KEY,
  ts TEXT NOT NULL,
  source TEXT NOT NULL,
  raw_text TEXT NOT NULL,
  parsed TEXT NOT NULL,
  scope TEXT NOT NULL,
  applied INTEGER NOT NULL,
  applied_at TEXT
);

CREATE TABLE IF NOT EXISTS costs (
  id TEXT PRIMARY KEY,
  ts TEXT NOT NULL,
  vendor TEXT NOT NULL,
  category TEXT NOT NULL,
  amount NUMERIC NOT NULL,
  currency TEXT NOT NULL,
  strategy_version_id TEXT,
  meta TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS llm_calls (
  id TEXT PRIMARY KEY,
  ts TEXT NOT NULL,
  tier TEXT NOT NULL,
  model_id TEXT NOT NULL,
  task TEXT NOT NULL,
  tokens_in INTEGER NOT NULL,
  tokens_out INTEGER NOT NULL,
  cost NUMERIC NOT NULL,
  latency_ms INTEGER NOT NULL,
  confidence NUMERIC,
  strategy_version_id TEXT,
  trace_id TEXT
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  actor TEXT NOT NULL,
  kind TEXT NOT NULL,
  ref_type TEXT,
  ref_id TEXT,
  payload TEXT NOT NULL
);

-- Asset-class gate: a class can be switched off while its venues keep their individual tick state
-- (effective = venue.enabled AND class.active). Absent row defaults to active.
CREATE TABLE IF NOT EXISTS asset_class_gates (
  kind TEXT PRIMARY KEY,
  active INTEGER NOT NULL DEFAULT 1
);

-- One-shot holdout: each strategy version may be evaluated against the untouched holdout exactly once.
CREATE TABLE IF NOT EXISTS holdout_ledger (
  version_id TEXT PRIMARY KEY,
  verdict TEXT NOT NULL,
  evaluated_at TEXT NOT NULL
);

-- Edge-gate verdicts: each run of the stop-or-go research gate, for monitoring from the UI.
CREATE TABLE IF NOT EXISTS gate_verdicts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  decision TEXT NOT NULL,
  data_source TEXT NOT NULL,
  payload TEXT NOT NULL
);

-- Global multiple-testing ledger: every hypothesis ever scored, for trial-count deflation.
CREATE TABLE IF NOT EXISTS trials (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  source TEXT NOT NULL,
  label TEXT,
  sharpe_per_obs NUMERIC NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_ref ON events(ref_type, ref_id);
CREATE INDEX IF NOT EXISTS idx_backtests_version_kind ON backtests(strategy_version_id, kind);
CREATE INDEX IF NOT EXISTS idx_executions_run ON executions(run_id);
CREATE INDEX IF NOT EXISTS idx_executions_ts ON executions(ts);
CREATE INDEX IF NOT EXISTS idx_strategy_versions_status ON strategy_versions(status);
CREATE INDEX IF NOT EXISTS idx_research_notes_created ON research_notes(created_at);
CREATE INDEX IF NOT EXISTS idx_skills_pruned ON skills(pruned_at);

