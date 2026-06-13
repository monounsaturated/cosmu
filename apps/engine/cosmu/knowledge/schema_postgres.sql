-- Cosmu v2 — Supabase (Postgres + pgvector) schema.
-- Paste this whole file into the Supabase SQL editor and run it once.
-- Mirrors the SQLite control-plane schema (schema.sql), ported to Postgres:
--   • INTEGER PRIMARY KEY AUTOINCREMENT  -> BIGINT GENERATED ALWAYS AS IDENTITY
--   • booleans kept as INTEGER (0/1) to match the app's writes — no app change needed
--   • timestamps kept as TEXT (app stores ISO-8601 strings)
--   • adds pgvector for the graveyard/research RAG and a central alt_data snapshot table

create extension if not exists vector;

create table if not exists venues (
  id text primary key,
  name text not null unique,
  kind text not null,
  adapter text not null,
  fee_schedule text not null,
  constraints text not null,
  enabled integer not null default 1
);

create table if not exists instruments (
  id text primary key,
  venue_id text not null references venues(id),
  symbol text not null,
  asset_class text not null,
  tick_size numeric not null,
  lot_size numeric not null,
  min_notional numeric not null,
  listed_at text,
  delisted_at text,
  active integer not null default 1
);

create table if not exists strategies (
  id text primary key,
  name text not null,
  thesis text not null,
  origin text not null,
  created_at text not null
);

create table if not exists strategy_versions (
  id text primary key,
  strategy_id text not null references strategies(id),
  parent_id text references strategy_versions(id),
  spec text not null,
  generated_code text not null,
  code_hash text not null,
  params text not null,
  mutation_operator text,
  mutation_rationale text,
  origin text not null,
  status text not null,
  created_at text not null,
  killed_at text,
  kill_reason text
);

create table if not exists backtests (
  id text primary key,
  strategy_version_id text not null references strategy_versions(id),
  kind text not null,
  is_start text, is_end text, oos_start text, oos_end text,
  oos_return numeric not null,
  sharpe numeric not null,
  sortino numeric not null,
  deflated_sharpe numeric not null,
  max_dd numeric not null,
  win_rate numeric not null,
  num_trades integer not null,
  pbo numeric not null,
  trials_counted integer not null,
  regime_label text,
  folds_positive integer not null,
  passed_gates integer not null,
  holdout_passed integer not null,
  -- Survival-model feature row (ml/survival.py), persisted off the screen. Nullable: pre-migration rows stay
  -- valid (the reader coalesces NULL -> neutral) and non-screen backtest kinds may leave them unset.
  sharpe_per_obs numeric,
  skew numeric,
  kurtosis numeric,
  n_obs integer,
  regime_spread integer,
  created_at text not null
);

create table if not exists runs (
  id text primary key,
  strategy_version_id text,
  mode text not null,
  venue_id text,
  seed integer not null,
  started_at text not null,
  ended_at text,
  status text not null
);

create table if not exists executions (
  id text primary key,
  run_id text not null references runs(id),
  strategy_version_id text,
  instrument_id text,
  venue_id text,
  side text not null,
  qty numeric not null,
  price numeric not null,
  fee numeric not null,
  slippage numeric not null,
  order_type text not null,
  is_paper integer not null,
  ts text not null,
  fill_log text not null
);

create table if not exists portfolio_snapshots (
  id text primary key,
  scope text not null,
  ref_id text not null,
  ts text not null,
  equity numeric not null,
  cash numeric not null,
  positions_value numeric not null,
  pnl numeric not null,
  drawdown numeric not null
);

create table if not exists positions (
  id text primary key,
  strategy_version_id text,
  instrument_id text not null,
  symbol text not null,
  venue text not null,
  qty numeric not null,
  avg_price numeric not null,
  realized_pnl numeric not null default 0,
  last_was_loss integer not null default 0,
  updated_at text not null
);

create table if not exists tracks (
  id text primary key,
  strategy_version_id text not null unique references strategy_versions(id),
  starting_capital numeric not null default 100000,
  equity numeric not null,
  return_pct numeric not null,
  updated_at text not null
);

create table if not exists live_toggle (
  id text primary key check (id = 'global'),
  enabled integer not null default 0,
  enabled_at text,
  enabled_by text
);

create table if not exists live_caps (
  id text primary key,
  scope text not null,
  ref_id text,
  max_notional numeric not null,
  max_daily_loss numeric not null
);

create table if not exists skills (
  id text primary key,
  name text not null,
  recipe text not null,
  grade numeric not null,
  lineage text not null,
  success_count integer not null,
  created_at text not null,
  pruned_at text,
  embedding vector(1536)            -- pgvector: keyless deterministic embedding for skill-recall priors
);
create index if not exists idx_skills_embedding on skills using hnsw (embedding vector_cosine_ops);

create table if not exists sources (
  id text primary key,
  kind text not null,
  uri text,
  raw text not null,
  extracted text not null,
  claims text not null,
  veracity text not null default 'na',
  ingested_at text not null
);

create table if not exists research_notes (
  id text primary key,
  strategy_version_id text,
  kind text not null,
  body_md text not null,
  structured text not null,
  created_at text not null,
  embedding vector(1536)            -- pgvector: RAG over notes + graveyard (text-embedding-3-small dim)
);
create index if not exists idx_research_notes_embedding on research_notes using hnsw (embedding vector_cosine_ops);
-- recall()/novelty always filter `where kind = ?` before the vector scan; index the predicate.
create index if not exists idx_research_notes_kind on research_notes(kind);

create table if not exists recommendations (
  id text primary key, ts text not null, kind text not null, body text not null, state text not null, payload text not null
);

create table if not exists policies (
  id text primary key, ts text not null, source text not null, raw_text text not null,
  parsed text not null, scope text not null, applied integer not null, applied_at text
);

create table if not exists costs (
  id text primary key, ts text not null, vendor text not null, category text not null,
  amount numeric not null, currency text not null, strategy_version_id text, meta text not null
);

create table if not exists llm_calls (
  id text primary key, ts text not null, tier text not null, model_id text not null, task text not null,
  tokens_in integer not null, tokens_out integer not null, cost numeric not null, latency_ms integer not null,
  confidence numeric, strategy_version_id text, trace_id text
);

create table if not exists events (
  id bigint generated always as identity primary key,
  ts text not null, actor text not null, kind text not null, ref_type text, ref_id text, payload text not null
);

-- Asset-class gate (effective = venue.enabled AND class.active). Absent row defaults to active.
create table if not exists asset_class_gates (
  kind text primary key,
  active integer not null default 1
);

-- One-shot holdout: each strategy version may be evaluated against the untouched holdout exactly once.
create table if not exists holdout_ledger (
  version_id text primary key,
  verdict text not null,
  evaluated_at text not null
);

-- Edge-gate verdicts (monitoring).
create table if not exists gate_verdicts (
  id bigint generated always as identity primary key,
  ts text not null, decision text not null, data_source text not null, payload text not null
);

-- Global multiple-testing ledger (trial-count deflation).
create table if not exists trials (
  id bigint generated always as identity primary key,
  ts text not null, source text not null, label text, sharpe_per_obs numeric not null
);

-- Correlation ledger: every correlation_scan finding, TRACKED over time (one row per run × feature × source ×
-- asset × horizon). PROPOSE-ONLY — a finding is a candidate hypothesis, never an edge (the Gate disposes).
-- deflated_note honestly flags known non-causal features; the read path drives the UI + IC decay-tracking.
create table if not exists correlation_findings (
  id bigint generated always as identity primary key,
  run_id text not null,
  ts text not null,
  feature text not null,
  source text not null,
  asset text not null,
  horizon integer not null,
  ic numeric not null,
  n integer not null,
  p numeric not null,
  fdr_survived integer not null,
  deflated_note text not null,
  data_source text not null
);
create index if not exists idx_correlation_findings_feature on correlation_findings (feature, ts);
create index if not exists idx_correlation_findings_run on correlation_findings (run_id);

-- Mind reflections: point-in-time record of the agent's standardized market read (the analyst-panel debate),
-- so it accrues a memory of how it thought over time. Append-only. A reasoning record only — never moves money.
create table if not exists mind_reflections (
  id bigint generated always as identity primary key,
  ts text not null,
  as_of text,
  consensus text not null,
  conviction numeric not null,
  agreement numeric not null,
  payload text not null
);

-- Central alt-data store (replaces the JSONL files): append-only, point-in-time.
-- Reads select the latest row per ts with available_at <= as_of, so vendor revisions never rewrite history.
create table if not exists alt_data (
  id bigint generated always as identity primary key,
  provider text not null,
  symbol text not null,
  metric text not null,
  ts text not null,            -- observation time
  available_at text not null,  -- point-in-time: when we'd have known it
  value numeric not null,
  ingested_at text not null default (now()::text)
);
create index if not exists idx_alt_data_lookup on alt_data (provider, symbol, metric, available_at);
-- Covering index for the /scores freshness query: MAX(available_at) per metric across all symbols.
-- Without this the query does a seqscan over millions of rows (LunarCrush per-symbol backfill).
create index if not exists idx_alt_data_metric_avail on alt_data (metric, available_at desc);
-- POINT-IN-TIME uniqueness: collapse exact (provider,symbol,metric,ts,available_at) photocopies at the DB layer,
-- so the 15-min ingest cron can re-append a window idempotently. A genuine vendor revision has a DIFFERENT
-- available_at (when we'd have known the new value) and is still kept as a distinct row — zero information loss.
-- Appends MUST insert ON CONFLICT DO NOTHING (see PgAltDataStore.append) so a racing/repeat insert is a no-op,
-- never a raise.
create unique index if not exists uq_alt_data_pit on alt_data (provider, symbol, metric, ts, available_at);

-- POINT-IN-TIME UNSTRUCTURED-EVENT store (realtime-data-lane epic §5): typed news/tweet/Polymarket/OSINT
-- events with TWO clocks — ts = the event's own publish time (event-study axis), available_at = OUR receipt
-- time (the only honest trading-feature axis; scraped archives are "available at scrape time", never
-- backdated). Append-only, deduped by (provider, content_hash). Title-level text only (small); numeric
-- features derived from events flow into alt_data. Read by the event-study harness + mind/authority.py.
create table if not exists market_events (
  id bigint generated always as identity primary key,
  provider text not null,
  source text not null default '',
  symbols text not null default '[]',     -- JSON array; [] = market-wide
  ts text not null,                       -- the event's own publish/claim time
  available_at text not null,             -- when WE received it (receipt/scrape time)
  title text not null,
  content_hash text not null,
  event_type text,
  root_event_id text,
  novelty real,
  direction integer,
  magnitude real,
  confidence real,
  extractor_version text,
  ingested_at text not null default (now()::text),
  unique (provider, content_hash)
);
create index if not exists idx_market_events_ts on market_events (provider, ts);
create index if not exists idx_market_events_root on market_events (root_event_id);

-- CREDIBILITY pipeline durable storage (realtime-data-lane epic P2). voice_claims = every typed predictive
-- claim Phase 1 extracted (append-only, deduped so a re-extraction never double-counts; ts == the post's own
-- availability — a claim can never read the future). voice_scoreboard = ONE flat, human-readable row per
-- followed voice, upserted each pass — the operator-facing surface (plain columns, no joins needed).
create table if not exists voice_claims (
  id bigint generated always as identity primary key,
  handle text not null,
  platform text not null,
  post_id text not null,
  entity text not null,
  direction text not null,            -- up | down | flat
  horizon text not null,              -- canonical horizon code
  horizon_days integer not null,
  conviction real not null,
  ts text not null,                   -- claim time == the post's availability (PIT)
  quote text not null default '',
  url text not null default '',
  extractor_version text,
  ingested_at text not null default (now()::text),
  unique (post_id, entity, direction, horizon)
);
create index if not exists idx_voice_claims_handle on voice_claims (handle, ts);

create table if not exists voice_scoreboard (
  handle text not null,
  platform text not null,
  n_posts integer not null default 0,        -- timeline posts on record
  n_claims integer not null default 0,       -- typed claims extracted (volume, NOT skill)
  n_resolved integer not null default 0,     -- claims old enough to be scored against the tape
  hit_rate real,                             -- fraction of resolved claims whose direction realized
  base_hit_rate real,                        -- what a coin-at-base-rate would have hit
  excess_hit_rate real,                      -- hit_rate - base_hit_rate (skill above chance)
  brier_skill_score real,                    -- >0 beats the base rate; <=0 does not
  calibration_error real,                    -- |stated conviction - realized| (0 = perfectly calibrated)
  skill real,                                -- the headline [0,1] scalar (sample-shrunk Brier skill)
  authority real,                            -- citation-PageRank anchored to skill (influence != authority)
  primacy_rate real,                         -- how often this voice is FIRST on a claim (breaker vs echo)
  updated_at text not null,
  primary key (platform, handle)
);

-- Per-(provider, metric) rollup of alt_data, refreshed INCREMENTALLY after each ingest pass (an upsert from
-- the just-written rows, NEVER a full re-aggregate). The /intelligence data-freshness panel and the /scores
-- source-trust freshness read this tiny table (≤ a few hundred rows) instead of a GROUP BY over the ~17M-row
-- alt_data table — what made those endpoints ~24s/~22s and timed out the SSR fetch. Sub-second on prod-scale.
-- HONEST: a (provider, metric) with no ingested rows has no summary row, so an empty summary → empty answer
-- (never a fabricated freshness). latest_available_at = MAX(available_at) of rows ingested so far; n_rows = the
-- running count; updated_at = when this row was last touched.
create table if not exists alt_data_provider_summary (
  provider text not null,
  metric text not null,
  n_rows integer not null default 0,
  latest_available_at text,
  latest_value text,
  updated_at text not null,
  primary key (provider, metric)
);

-- Experiments registry: every finder/gate run logs config + seed + data_version + metrics so results are
-- comparable across runs and exactly regenerable; soft_label carries the continuous forward-P&L so the ML
-- ranker has a gradient before any gate-pass (binary survival label) exists. Append-only, LLM-free record.
create table if not exists experiments (
  id text primary key,
  ts text not null,
  kind text not null,
  source text not null,
  label text,
  seed integer not null,
  data_version text not null,
  code_hash text,
  config text not null,
  metrics text not null,
  soft_label numeric,
  gate_passed integer,
  created_at text not null
);
create index if not exists idx_experiments_kind_ts on experiments(kind, ts);
create index if not exists idx_experiments_data_version on experiments(data_version);

create index if not exists idx_events_ts on events(ts);
create index if not exists idx_events_ref on events(ref_type, ref_id);
create index if not exists idx_backtests_version_kind on backtests(strategy_version_id, kind);
create index if not exists idx_executions_run on executions(run_id);
create index if not exists idx_executions_ts on executions(ts);
create index if not exists idx_strategy_versions_status on strategy_versions(status);

-- Building-block registry (2026-06-11): content-hashed reusable blocks + whole-spec combo_hash.
-- Dedup (multiple-testing budget) + observational block stats. Never consulted by the Gate.
create table if not exists strategy_blocks (
  block_hash text primary key,
  kind text not null,
  label text not null,
  payload text not null,
  first_seen text not null
);
create table if not exists version_blocks (
  strategy_version_id text not null,
  block_hash text not null,
  kind text not null,
  primary key (strategy_version_id, block_hash)
);
create table if not exists version_combos (
  strategy_version_id text primary key,
  combo_hash text not null,
  created_at text not null
);
create index if not exists idx_version_blocks_hash on version_blocks(block_hash);
create index if not exists idx_version_combos_hash on version_combos(combo_hash);
