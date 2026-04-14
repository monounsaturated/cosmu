-- Key/value settings (e.g. per-venue system preprompt for the LLM).
create table if not exists app_settings (
  key text primary key,
  value text not null,
  updated_at timestamptz not null default now()
);

create index if not exists app_settings_updated_at_idx on app_settings (updated_at desc);
