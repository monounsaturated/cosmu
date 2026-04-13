create extension if not exists pgcrypto;

create table if not exists prompts (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,
  slug text not null unique,
  created_at timestamptz not null default now()
);

create table if not exists prompt_versions (
  id uuid primary key default gen_random_uuid(),
  prompt_id uuid not null references prompts(id) on delete cascade,
  version integer not null,
  body text not null,
  created_at timestamptz not null default now(),
  unique (prompt_id, version)
);

create table if not exists model_profiles (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,
  provider text not null,
  model text not null,
  settings jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists bots (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,
  slug text not null unique,
  active_prompt_version_id uuid not null references prompt_versions(id),
  active_model_profile_id uuid not null references model_profiles(id),
  created_at timestamptz not null default now()
);

create table if not exists bot_runtime_configs (
  id uuid primary key default gen_random_uuid(),
  bot_id uuid not null unique references bots(id) on delete cascade,
  enabled boolean not null default false,
  venue text not null check (venue = 'binance'),
  frequency_minutes integer not null check (frequency_minutes in (1, 5, 15, 30, 60)),
  mode text not null check (mode in ('testnet', 'live')),
  asset_class text not null check (asset_class = 'spot'),
  execution_config jsonb not null default '{}'::jsonb,
  context_symbols jsonb not null default '[]'::jsonb,
  last_run_started_at timestamptz,
  last_run_finished_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists runs (
  id uuid primary key default gen_random_uuid(),
  bot_id uuid not null references bots(id) on delete cascade,
  prompt_version_id uuid not null references prompt_versions(id),
  model_profile_id uuid not null references model_profiles(id),
  runtime_config jsonb not null,
  compact_context jsonb not null,
  raw_model_output text,
  parsed_decision jsonb,
  validation_result jsonb,
  status text not null check (status in ('running', 'success', 'failure', 'uncertain')),
  error_state jsonb,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists decisions (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null unique references runs(id) on delete cascade,
  decision_mode text not null check (decision_mode in ('rebalance', 'enter', 'exit', 'hold', 'adjust')),
  rationale_summary text not null,
  global_rationale text not null,
  confidence numeric not null,
  payload jsonb not null,
  created_at timestamptz not null default now()
);

create table if not exists executions (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references runs(id) on delete cascade,
  asset_class text not null check (asset_class = 'spot'),
  venue text not null check (venue = 'binance'),
  status text not null check (status in ('success', 'failure', 'uncertain')),
  symbol text not null,
  side text not null check (side in ('buy', 'sell')),
  order_type text not null check (order_type in ('market', 'limit')),
  requested_quantity numeric not null,
  executed_quantity numeric,
  requested_limit_price numeric,
  average_fill_price numeric,
  fee_amount numeric,
  fee_asset text,
  fee_usd numeric,
  slippage_pct numeric,
  order_intent jsonb not null,
  raw_venue_response jsonb not null,
  created_at timestamptz not null default now()
);

create table if not exists portfolio_snapshots (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references runs(id) on delete cascade,
  asset_class text not null check (asset_class = 'spot'),
  stage text not null check (stage in ('before', 'after')),
  total_usd_value numeric not null,
  gross_pnl_usd numeric,
  net_pnl_usd numeric,
  fee_usd numeric,
  balances jsonb not null,
  prices jsonb not null,
  raw_snapshot jsonb not null,
  created_at timestamptz not null default now()
);

create index if not exists runs_bot_created_at_idx on runs (bot_id, created_at desc);
create index if not exists executions_run_created_at_idx on executions (run_id, created_at desc);
create index if not exists portfolio_snapshots_run_stage_idx on portfolio_snapshots (run_id, stage, created_at desc);
