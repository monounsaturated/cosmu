-- Signal Sentinel core
-- Raw hot data stays separate from LLM-standardized signals so humans can audit
-- what was collected, what was inferred, and what agents consumed.

create table if not exists raw_observations (
  id uuid primary key default gen_random_uuid(),
  source_kind text not null check (source_kind in ('x', 'web', 'news', 'market', 'manual')),
  source_name text not null,
  source_url text,
  observed_at timestamptz not null default now(),
  captured_at timestamptz not null default now(),
  title text not null,
  content text not null,
  raw_json jsonb,
  content_hash text
);

create index if not exists raw_observations_recent_idx
  on raw_observations (observed_at desc, captured_at desc);

create unique index if not exists raw_observations_content_hash_idx
  on raw_observations (content_hash)
  where content_hash is not null;

create table if not exists standardized_signals (
  id uuid primary key default gen_random_uuid(),
  observation_id uuid references raw_observations(id) on delete set null,
  asset text not null,
  symbol text,
  topic text not null,
  direction text not null check (direction in ('bullish', 'bearish', 'neutral', 'mixed')),
  sentiment_score numeric not null default 0 check (sentiment_score >= -1 and sentiment_score <= 1),
  confidence numeric not null default 0.5 check (confidence >= 0 and confidence <= 1),
  urgency text not null default 'medium' check (urgency in ('low', 'medium', 'high')),
  horizon text,
  summary text not null,
  evidence_json jsonb not null default '[]'::jsonb,
  reasoning_summary text,
  status text not null default 'new' check (status in ('new', 'watching', 'used', 'dismissed')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists standardized_signals_status_recent_idx
  on standardized_signals (status, created_at desc);

create index if not exists standardized_signals_asset_recent_idx
  on standardized_signals (asset, created_at desc);

create index if not exists standardized_signals_confidence_idx
  on standardized_signals (confidence desc, urgency, created_at desc);
