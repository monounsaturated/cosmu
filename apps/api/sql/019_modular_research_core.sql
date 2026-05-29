-- Modular Research Core
-- Datasets, sessions, engine runs, experiment specs, evaluations, simulation, and memory.

create table if not exists datasets (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  source_kind text not null check (source_kind in ('upload', 'binance_ohlcv', 'external_api', 'manual')),
  description text,
  tags jsonb not null default '[]'::jsonb,
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists datasets_active_idx on datasets (active, created_at desc);

create table if not exists dataset_versions (
  id uuid primary key default gen_random_uuid(),
  dataset_id uuid not null references datasets(id) on delete cascade,
  version_number integer not null,
  schema_json jsonb not null default '{}'::jsonb,
  metadata_json jsonb not null default '{}'::jsonb,
  row_count integer,
  start_at timestamptz,
  end_at timestamptz,
  content_json jsonb,
  content_hash text,
  created_at timestamptz not null default now(),
  unique (dataset_id, version_number)
);

create index if not exists dataset_versions_dataset_idx on dataset_versions (dataset_id, version_number desc);

create table if not exists research_sessions (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  objective text not null,
  engine text not null check (engine in ('native', 'hermes', 'autoresearch', 'openclaw')) default 'native',
  autonomy_mode text not null check (autonomy_mode in ('manual', 'assisted', 'autonomous')) default 'assisted',
  status text not null check (status in ('draft', 'queued', 'running', 'success', 'failure', 'stopped')) default 'draft',
  model_profile_id uuid references model_profiles(id) on delete set null,
  max_iterations integer not null default 3,
  max_runtime_minutes integer not null default 30,
  max_cost_usd numeric(12,2) not null default 10,
  allowed_tools jsonb not null default '[]'::jsonb,
  stop_reason text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists research_sessions_status_idx on research_sessions (status, updated_at desc);

create table if not exists research_session_datasets (
  session_id uuid not null references research_sessions(id) on delete cascade,
  dataset_version_id uuid not null references dataset_versions(id) on delete restrict,
  created_at timestamptz not null default now(),
  primary key (session_id, dataset_version_id)
);

create table if not exists research_engine_runs (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references research_sessions(id) on delete cascade,
  engine text not null check (engine in ('native', 'hermes', 'autoresearch', 'openclaw')),
  status text not null check (status in ('queued', 'running', 'success', 'failure', 'cancelled')) default 'queued',
  input_json jsonb not null default '{}'::jsonb,
  output_json jsonb,
  logs_text text,
  error text,
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists research_engine_runs_session_idx on research_engine_runs (session_id, created_at desc);

create table if not exists experiment_specs (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references research_sessions(id) on delete cascade,
  version_number integer not null,
  hypothesis text not null,
  spec_json jsonb not null,
  status text not null check (status in ('draft', 'locked', 'superseded')) default 'draft',
  created_by text not null default 'user',
  created_at timestamptz not null default now(),
  unique (session_id, version_number)
);

create index if not exists experiment_specs_session_idx on experiment_specs (session_id, version_number desc);

create table if not exists evaluation_jobs (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references research_sessions(id) on delete cascade,
  spec_id uuid not null references experiment_specs(id) on delete cascade,
  engine_run_id uuid references research_engine_runs(id) on delete set null,
  status text not null check (status in ('queued', 'running', 'success', 'failure', 'cancelled')) default 'queued',
  kind text not null check (kind in ('backtest', 'ml_validation')) default 'backtest',
  dataset_version_ids jsonb not null default '[]'::jsonb,
  config_json jsonb not null default '{}'::jsonb,
  result_id uuid,
  error text,
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists evaluation_jobs_session_idx on evaluation_jobs (session_id, created_at desc);

create table if not exists evaluation_results (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references research_sessions(id) on delete cascade,
  spec_id uuid not null references experiment_specs(id) on delete cascade,
  metrics_json jsonb not null default '{}'::jsonb,
  split_summary_json jsonb not null default '{}'::jsonb,
  artifacts_json jsonb not null default '{}'::jsonb,
  gates_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists evaluation_results_session_idx on evaluation_results (session_id, created_at desc);

alter table evaluation_jobs
  drop constraint if exists evaluation_jobs_result_id_fkey;
alter table evaluation_jobs
  add constraint evaluation_jobs_result_id_fkey
  foreign key (result_id) references evaluation_results(id) on delete set null;

create table if not exists simulation_portfolios (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references research_sessions(id) on delete cascade,
  evaluation_result_id uuid references evaluation_results(id) on delete set null,
  starting_capital_usd numeric(14,2) not null default 10000,
  current_value_usd numeric(14,2) not null default 10000,
  status text not null check (status in ('active', 'closed')) default 'active',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists simulation_portfolios_session_idx on simulation_portfolios (session_id, created_at desc);

create table if not exists simulation_trades (
  id uuid primary key default gen_random_uuid(),
  portfolio_id uuid not null references simulation_portfolios(id) on delete cascade,
  symbol text not null,
  side text not null check (side in ('buy', 'sell')),
  quantity numeric(20,8) not null,
  price numeric(20,8) not null,
  fee_usd numeric(20,8) not null default 0,
  notional_usd numeric(20,8) not null,
  trade_at timestamptz not null,
  rationale text,
  created_at timestamptz not null default now()
);

create index if not exists simulation_trades_portfolio_idx on simulation_trades (portfolio_id, trade_at asc);

create table if not exists research_memories (
  id uuid primary key default gen_random_uuid(),
  session_id uuid references research_sessions(id) on delete set null,
  scope_type text not null check (scope_type in ('strategy', 'dataset', 'symbol', 'agent', 'failure', 'evaluation')),
  scope_key text not null,
  title text not null,
  memory_text text not null,
  evidence_json jsonb not null default '{}'::jsonb,
  confidence numeric not null default 0.5 check (confidence >= 0 and confidence <= 1),
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists research_memories_scope_idx on research_memories (scope_type, scope_key, created_at desc);
