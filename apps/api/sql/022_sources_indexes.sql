-- Source/index foundation: data sources create raw observations; indexes turn
-- standardized signals into durable quantitative snapshots.

alter table bot_runtime_configs drop constraint if exists bot_runtime_configs_venue_check;
alter table bot_runtime_configs add constraint bot_runtime_configs_venue_check
  check (venue in ('binance', 'binance-testnet', 'ibkr-paper', 'ibkr'));

alter table executions drop constraint if exists executions_venue_check;
alter table executions add constraint executions_venue_check
  check (venue in ('binance', 'binance-testnet', 'ibkr-paper', 'ibkr'));

alter table bot_runtime_configs drop constraint if exists bot_runtime_configs_asset_class_check;
alter table bot_runtime_configs add constraint bot_runtime_configs_asset_class_check
  check (asset_class in ('spot', 'equity'));

alter table executions drop constraint if exists executions_asset_class_check;
alter table executions add constraint executions_asset_class_check
  check (asset_class in ('spot', 'equity'));

alter table portfolio_snapshots drop constraint if exists portfolio_snapshots_asset_class_check;
alter table portfolio_snapshots add constraint portfolio_snapshots_asset_class_check
  check (asset_class in ('spot', 'equity'));

create table if not exists index_configs (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  slug text not null unique,
  description text,
  status text not null check (status in ('active', 'paused', 'error')) default 'paused',
  cadence_minutes integer not null check (cadence_minutes > 0),
  source_keys jsonb not null default '[]'::jsonb,
  prompt_body text not null,
  output_schema jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists index_configs_status_idx on index_configs (status, updated_at desc);

create table if not exists index_runs (
  id uuid primary key default gen_random_uuid(),
  index_id uuid not null references index_configs(id) on delete cascade,
  status text not null check (status in ('running', 'success', 'failure')) default 'running',
  source_counts jsonb not null default '{}'::jsonb,
  cost_json jsonb not null default '{}'::jsonb,
  error text,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists index_runs_index_recent_idx on index_runs (index_id, created_at desc);

create table if not exists index_snapshots (
  id uuid primary key default gen_random_uuid(),
  index_id uuid not null references index_configs(id) on delete cascade,
  run_id uuid references index_runs(id) on delete set null,
  value numeric,
  label text,
  summary text not null,
  evidence_json jsonb not null default '[]'::jsonb,
  captured_at timestamptz not null default now()
);

create index if not exists index_snapshots_index_recent_idx on index_snapshots (index_id, captured_at desc);
