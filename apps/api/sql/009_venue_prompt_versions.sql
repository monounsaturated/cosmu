-- Versioned venue-level prompts (formatter, etc.)
-- Each edit creates a new version; the latest version per (venue, prompt_type) is active.

create table if not exists venue_prompt_versions (
  id uuid primary key default gen_random_uuid(),
  venue text not null,
  prompt_type text not null check (prompt_type in ('formatter')),
  version int not null,
  body text not null,
  created_at timestamptz not null default now(),
  unique (venue, prompt_type, version)
);

create index if not exists idx_venue_prompt_active
  on venue_prompt_versions (venue, prompt_type, version desc);

-- Track which formatter prompt version was used for each run
alter table runs add column if not exists formatter_prompt_version_id uuid references venue_prompt_versions(id);

-- Migrate existing formatter prompts from app_settings into the versioned table
insert into venue_prompt_versions (venue, prompt_type, version, body)
select
  replace(key, 'formatter_', '') as venue,
  'formatter' as prompt_type,
  1 as version,
  value as body
from app_settings
where key like 'formatter_%'
  and length(value) > 0
on conflict do nothing;
