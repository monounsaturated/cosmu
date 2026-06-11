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
  -- The survival-model feature row (ml/survival.py) persisted off the screen: per-obs Sharpe + higher moments
  -- + observation count + regime breadth. Nullable so pre-migration rows stay valid (the reader coalesces
  -- NULL -> neutral, i.e. the old zero-filled behaviour) and other backtest kinds may leave them unset.
  sharpe_per_obs NUMERIC,
  skew NUMERIC,
  kurtosis NUMERIC,
  n_obs INTEGER,
  regime_spread INTEGER,
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

-- Sim/live open positions per strategy track, marked-to-market by master/portfolio.py. avg_price is the
-- memoryless basis; venue distinguishes sim/testnet/live mechanics. Net-zero rows are kept for audit.
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

CREATE TABLE IF NOT EXISTS tracks (
  id TEXT PRIMARY KEY,
  strategy_version_id TEXT NOT NULL UNIQUE REFERENCES strategy_versions(id),
  starting_capital NUMERIC NOT NULL DEFAULT 100000,
  equity NUMERIC NOT NULL,
  return_pct NUMERIC NOT NULL,
  updated_at TEXT NOT NULL
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

-- Correlation ledger: every correlation_scan finding, TRACKED over time (one row per run × feature × source ×
-- asset × horizon). PROPOSE-ONLY — a finding is a candidate hypothesis, never an edge (the Gate disposes). Lets the
-- UI + decay-tracking read how a PIT IC moves run-over-run; deflated_note honestly flags known non-causal features.
CREATE TABLE IF NOT EXISTS correlation_findings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  feature TEXT NOT NULL,
  source TEXT NOT NULL,
  asset TEXT NOT NULL,
  horizon INTEGER NOT NULL,
  ic NUMERIC NOT NULL,
  n INTEGER NOT NULL,
  p NUMERIC NOT NULL,
  fdr_survived INTEGER NOT NULL,
  deflated_note TEXT NOT NULL,
  data_source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_correlation_findings_feature ON correlation_findings (feature, ts);
CREATE INDEX IF NOT EXISTS idx_correlation_findings_run ON correlation_findings (run_id);

-- Central alt-data store (mirrors the Postgres table): append-only, point-in-time. Locally the JSONL
-- AltDataStore is still used by ingest; this table lets the store-backed point-in-time read (and the Mind's
-- "what it knows" freshness) work uniformly on SQLite and Postgres.
CREATE TABLE IF NOT EXISTS alt_data (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider TEXT NOT NULL,
  symbol TEXT NOT NULL,
  metric TEXT NOT NULL,
  ts TEXT NOT NULL,
  available_at TEXT NOT NULL,
  value NUMERIC NOT NULL,
  ingested_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alt_data_lookup ON alt_data (provider, symbol, metric, available_at);

-- POINT-IN-TIME UNSTRUCTURED-EVENT store (realtime-data-lane epic §5): typed news/tweet/Polymarket/OSINT
-- events with TWO clocks — ts = the event's own publish time (event-study axis), available_at = OUR receipt
-- time (the only honest trading-feature axis; scraped archives are "available at scrape time", never
-- backdated). Append-only, deduped by (provider, content_hash). Title-level text only (small); numeric
-- features derived from events flow into alt_data. Read by the event-study harness + mind/authority.py.
CREATE TABLE IF NOT EXISTS market_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT '',
  symbols TEXT NOT NULL DEFAULT '[]',     -- JSON array; [] = market-wide
  ts TEXT NOT NULL,
  available_at TEXT NOT NULL,
  title TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  event_type TEXT,
  root_event_id TEXT,
  novelty REAL,
  direction INTEGER,
  magnitude REAL,
  confidence REAL,
  extractor_version TEXT,
  ingested_at TEXT NOT NULL,
  UNIQUE (provider, content_hash)
);
CREATE INDEX IF NOT EXISTS idx_market_events_ts ON market_events (provider, ts);
CREATE INDEX IF NOT EXISTS idx_market_events_root ON market_events (root_event_id);

-- CREDIBILITY pipeline durable storage (realtime-data-lane epic P2). voice_claims = every typed predictive
-- claim Phase 1 extracted (append-only, deduped so a re-extraction never double-counts; ts == the post's own
-- availability — a claim can never read the future). voice_scoreboard = ONE flat, human-readable row per
-- followed voice, upserted each pass — the operator-facing surface (plain columns, no joins needed).
CREATE TABLE IF NOT EXISTS voice_claims (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  handle TEXT NOT NULL,
  platform TEXT NOT NULL,
  post_id TEXT NOT NULL,
  entity TEXT NOT NULL,
  direction TEXT NOT NULL,            -- up | down | flat
  horizon TEXT NOT NULL,              -- canonical horizon code
  horizon_days INTEGER NOT NULL,
  conviction REAL NOT NULL,
  ts TEXT NOT NULL,                   -- claim time == the post's availability (PIT)
  quote TEXT NOT NULL DEFAULT '',
  url TEXT NOT NULL DEFAULT '',
  extractor_version TEXT,
  ingested_at TEXT NOT NULL,
  UNIQUE (post_id, entity, direction, horizon)
);
CREATE INDEX IF NOT EXISTS idx_voice_claims_handle ON voice_claims (handle, ts);

-- INTRADAY bar store (realtime-data-lane epic P3): closed 1m/5m candles recorded LIVE by the in-process
-- realtime worker (Binance WS). Postgres-first because the Railway filesystem is ephemeral — the recorded
-- history must survive restarts. Retention: 1m rows are rolled up to 5m then deleted after RETENTION_DAYS
-- (epic §6 keeps the table bounded at ~1.3M rows/mo for ~30 symbols). A bar is inserted only AFTER its
-- close (closed-candle invariant); UNIQUE makes reconnect/replay idempotent.
CREATE TABLE IF NOT EXISTS bars_intraday (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  venue TEXT NOT NULL,
  symbol TEXT NOT NULL,
  timeframe TEXT NOT NULL,            -- '1m' (live) | '5m' (rollup)
  ts TEXT NOT NULL,                   -- bar OPEN time (UTC ISO)
  open NUMERIC NOT NULL,
  high NUMERIC NOT NULL,
  low NUMERIC NOT NULL,
  close NUMERIC NOT NULL,
  volume NUMERIC NOT NULL,
  ingested_at TEXT NOT NULL,          -- receipt time (the PIT seam: when WE recorded the closed bar)
  UNIQUE (venue, symbol, timeframe, ts)
);
CREATE INDEX IF NOT EXISTS idx_bars_intraday_lookup ON bars_intraday (symbol, timeframe, ts);

CREATE TABLE IF NOT EXISTS voice_scoreboard (
  handle TEXT NOT NULL,
  platform TEXT NOT NULL,
  n_posts INTEGER NOT NULL DEFAULT 0,        -- timeline posts on record
  n_claims INTEGER NOT NULL DEFAULT 0,       -- typed claims extracted (volume, NOT skill)
  n_resolved INTEGER NOT NULL DEFAULT 0,     -- claims old enough to be scored against the tape
  hit_rate REAL,                             -- fraction of resolved claims whose direction realized
  base_hit_rate REAL,                        -- what a coin-at-base-rate would have hit
  excess_hit_rate REAL,                      -- hit_rate - base_hit_rate (skill above chance)
  brier_skill_score REAL,                    -- >0 beats the base rate; <=0 does not
  calibration_error REAL,                    -- |stated conviction - realized| (0 = perfectly calibrated)
  skill REAL,                                -- the headline [0,1] scalar (sample-shrunk Brier skill)
  authority REAL,                            -- citation-PageRank anchored to skill (influence != authority)
  primacy_rate REAL,                         -- how often this voice is FIRST on a claim (breaker vs echo)
  updated_at TEXT NOT NULL,
  PRIMARY KEY (platform, handle)
);

-- Per-(provider, metric) rollup of alt_data, refreshed INCREMENTALLY after each ingest pass (an upsert from
-- the just-written rows, NEVER a full re-aggregate of alt_data). Reads that only need "how fresh / how much"
-- (the /intelligence data-freshness panel and the /scores source-trust freshness) hit this tiny table
-- (≤ a few hundred rows) instead of a GROUP BY over the ~17M-row alt_data table — sub-second on prod-scale.
-- HONEST: a (provider, metric) with no ingested rows simply has no summary row, so an empty summary → empty
-- answer (never a fabricated freshness). latest_available_at is MAX(available_at) of the rows ingested so far;
-- n_rows is the running count. updated_at is when this summary row was last touched.
CREATE TABLE IF NOT EXISTS alt_data_provider_summary (
  provider TEXT NOT NULL,
  metric TEXT NOT NULL,
  n_rows INTEGER NOT NULL DEFAULT 0,
  latest_available_at TEXT,
  latest_value TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (provider, metric)
);

-- Mind reflections: a point-in-time record of the agent's standardized market read (the analyst-panel debate),
-- so it accrues a memory of HOW IT THOUGHT over time. Append-only. A reasoning record only — never moves money.
CREATE TABLE IF NOT EXISTS mind_reflections (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  as_of TEXT,
  consensus TEXT NOT NULL,
  conviction NUMERIC NOT NULL,
  agreement NUMERIC NOT NULL,
  payload TEXT NOT NULL
);

-- Experiments registry: every finder/gate run logs its exact config + seed + data_version + metrics so any
-- result is COMPARABLE across runs and EXACTLY REGENERABLE (same config+seed+data_version ⇒ same numbers).
-- soft_label carries the continuous forward-P&L so the ML ranker has a GRADIENT before any gate-pass (the
-- binary survival label) exists. Append-only; a record of what the DETERMINISTIC engine ran — out of any LLM
-- path. Parallel to `trials` (which is the deflation counter); this is the reproducibility/soft-label ledger.
CREATE TABLE IF NOT EXISTS experiments (
  id TEXT PRIMARY KEY,
  ts TEXT NOT NULL,
  kind TEXT NOT NULL,          -- 'finder' | 'finder_refine' | 'edge_gate' | 'ablation' | 'cross_asset'
  source TEXT NOT NULL,        -- the engine that ran it (mirrors trials.source)
  label TEXT,                  -- candidate/signal label (config_tag, signal name, arm)
  seed INTEGER NOT NULL,       -- the run seed → exact regeneration
  data_version TEXT NOT NULL,  -- deterministic fingerprint of the input bars → comparable + regenerable
  code_hash TEXT,              -- compiled-code hash where one exists (finder variants)
  config TEXT NOT NULL,        -- JSON: the exact knobs (fitted params / pre-registered bar) to regenerate
  metrics TEXT NOT NULL,       -- JSON: the run's scoreable metrics (BacktestMetrics dump or verdict)
  soft_label NUMERIC,          -- continuous forward-P&L (gradient before any gate-pass exists)
  gate_passed INTEGER,         -- 0/1 (nullable): the deterministic verdict, when known
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_experiments_kind_ts ON experiments(kind, ts);
CREATE INDEX IF NOT EXISTS idx_experiments_data_version ON experiments(data_version);

CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_ref ON events(ref_type, ref_id);
CREATE INDEX IF NOT EXISTS idx_backtests_version_kind ON backtests(strategy_version_id, kind);
CREATE INDEX IF NOT EXISTS idx_executions_run ON executions(run_id);
CREATE INDEX IF NOT EXISTS idx_executions_ts ON executions(ts);
CREATE INDEX IF NOT EXISTS idx_strategy_versions_status ON strategy_versions(status);
CREATE INDEX IF NOT EXISTS idx_research_notes_created ON research_notes(created_at);
-- recall()/novelty always filter `WHERE kind = ?`; without this the append-only graveyard is a full scan.
CREATE INDEX IF NOT EXISTS idx_research_notes_kind ON research_notes(kind);
CREATE INDEX IF NOT EXISTS idx_skills_pruned ON skills(pruned_at);

