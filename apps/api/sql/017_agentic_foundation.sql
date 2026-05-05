-- Agentic foundation: product-level agent observability, research experiments,
-- paper candidates, lightweight memory, and approval inbox primitives.

create table if not exists agent_steps (
  id uuid primary key default gen_random_uuid(),
  scope_type text not null check (scope_type in ('light_run', 'research_experiment', 'paper_bot_run', 'pro_run')),
  scope_id uuid not null,
  agent_key text not null,
  agent_label text not null,
  status text not null check (status in ('queued', 'running', 'success', 'failure', 'skipped')) default 'queued',
  input_json jsonb,
  output_text text,
  output_json jsonb,
  tool_calls jsonb,
  model_provider text,
  model text,
  input_tokens integer,
  output_tokens integer,
  latency_ms integer,
  error text,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists agent_steps_scope_idx on agent_steps (scope_type, scope_id, started_at asc);
create index if not exists agent_steps_status_idx on agent_steps (status, started_at desc);

create table if not exists research_experiments (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  hypothesis text not null,
  status text not null check (status in ('draft', 'running', 'rejected', 'paper_candidate', 'live_candidate')) default 'draft',
  promotion_status text not null check (promotion_status in ('none', 'paper_auto', 'live_pending_approval', 'live_approved', 'live_rejected')) default 'none',
  plan_json jsonb,
  result_json jsonb,
  skeptic_verdict text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists research_experiments_status_idx on research_experiments (status, updated_at desc);

create table if not exists research_data_sources (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  kind text not null check (kind in ('market', 'news', 'web', 'social', 'weather', 'astro', 'tradingview', 'csv', 'custom_api', 'ibkr', 'polymarket')),
  enabled boolean not null default true,
  config jsonb not null default '{}'::jsonb,
  health_status text not null check (health_status in ('unknown', 'ok', 'warning', 'error')) default 'unknown',
  last_checked_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists research_data_sources_name_idx on research_data_sources (lower(name));

create table if not exists research_candidates (
  id uuid primary key default gen_random_uuid(),
  experiment_id uuid not null references research_experiments(id) on delete cascade,
  name text not null,
  status text not null check (status in ('paper_ready', 'paper_running', 'paper_rejected', 'live_candidate')) default 'paper_ready',
  thesis text not null,
  metrics jsonb,
  risk_notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists research_candidates_experiment_idx on research_candidates (experiment_id, created_at desc);
create index if not exists research_candidates_status_idx on research_candidates (status, updated_at desc);

create table if not exists paper_bot_runs (
  id uuid primary key default gen_random_uuid(),
  candidate_id uuid not null references research_candidates(id) on delete cascade,
  status text not null check (status in ('running', 'success', 'failure', 'rejected')) default 'running',
  metrics jsonb,
  result_json jsonb,
  error text,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists paper_bot_runs_candidate_idx on paper_bot_runs (candidate_id, created_at desc);

create table if not exists lessons (
  id uuid primary key default gen_random_uuid(),
  scope_type text not null check (scope_type in ('bot', 'symbol', 'strategy', 'experiment', 'agent', 'incident')),
  scope_key text not null,
  lesson_text text not null,
  evidence_json jsonb,
  confidence numeric not null default 0.5 check (confidence >= 0 and confidence <= 1),
  created_from_scope_type text,
  created_from_scope_id uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists lessons_scope_idx on lessons (scope_type, scope_key, created_at desc);

create table if not exists approval_requests (
  id uuid primary key default gen_random_uuid(),
  request_type text not null check (request_type in ('live_promotion', 'dangerous_action', 'connector_permission')),
  status text not null check (status in ('pending', 'approved', 'rejected', 'cancelled')) default 'pending',
  title text not null,
  body text,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  resolved_at timestamptz
);

create index if not exists approval_requests_status_idx on approval_requests (status, created_at desc);

insert into research_data_sources (name, kind, enabled, config, health_status)
values
  ('Binance market data', 'market', true, '{"venue":"binance","mode":"read_only"}'::jsonb, 'unknown'),
  ('Web/news research', 'web', true, '{"mode":"search_reference"}'::jsonb, 'unknown'),
  ('Weather signals', 'weather', false, '{"mode":"placeholder"}'::jsonb, 'unknown'),
  ('Astro signals', 'astro', false, '{"mode":"placeholder"}'::jsonb, 'unknown'),
  ('TradingView scripts', 'tradingview', false, '{"mode":"manual_import"}'::jsonb, 'unknown'),
  ('IBKR stocks paper data', 'ibkr', false, '{"mode":"paper_data_first"}'::jsonb, 'unknown'),
  ('Polymarket paper data', 'polymarket', false, '{"mode":"paper_data_first"}'::jsonb, 'unknown')
on conflict do nothing;
