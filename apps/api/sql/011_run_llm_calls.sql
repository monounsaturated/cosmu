-- Per-LLM-call tracing: append-only log linked to each run
create table if not exists run_llm_calls (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references runs(id) on delete cascade,
  phase text not null check (phase in ('research', 'trader')),
  provider text not null,
  model text not null,
  input_messages jsonb not null,
  output_text text,
  input_tokens integer,
  output_tokens integer,
  latency_ms integer,
  attempt integer not null default 1,
  strategy text,
  error text,
  created_at timestamptz not null default now()
);

create index if not exists run_llm_calls_run_id_idx on run_llm_calls (run_id, created_at);

-- Global kill switch (uses existing app_settings table)
insert into app_settings (key, value)
values ('global_kill_switch', 'off')
on conflict (key) do nothing;
