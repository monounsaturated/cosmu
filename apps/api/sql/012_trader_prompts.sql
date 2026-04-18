-- 012: Separate trader prompts table (mirrors research prompts structure)
-- Research prompts = prompts + prompt_versions (already exist)
-- Trader prompts  = trader_prompts + trader_prompt_versions (new)

-- Trader prompts table
create table if not exists trader_prompts (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  slug text not null,
  created_at timestamptz not null default now()
);

create sequence if not exists trader_prompts_prompt_number_seq;

alter table trader_prompts add column if not exists prompt_number integer;

update trader_prompts
set prompt_number = sub.rn
from (
  select id, row_number() over (order by created_at asc) as rn
  from trader_prompts
  where prompt_number is null
) sub
where trader_prompts.id = sub.id;

alter table trader_prompts alter column prompt_number set default nextval('trader_prompts_prompt_number_seq');
alter table trader_prompts alter column prompt_number set not null;

select setval(
  'trader_prompts_prompt_number_seq',
  coalesce((select max(prompt_number) from trader_prompts), 0) + 1,
  false
);

create unique index if not exists trader_prompts_prompt_number_idx on trader_prompts (prompt_number);

-- Trader prompt versions table
create table if not exists trader_prompt_versions (
  id uuid primary key default gen_random_uuid(),
  prompt_id uuid not null references trader_prompts(id) on delete cascade,
  version integer not null,
  body text not null,
  created_at timestamptz not null default now(),
  unique (prompt_id, version)
);

-- Bot references a trader prompt version
alter table bots add column if not exists active_trader_prompt_version_id uuid references trader_prompt_versions(id);

-- Migrate existing venue_prompt_versions into the new table
-- For each unique venue formatter body, create a trader_prompt + version
do $$
declare
  v_prompt_id uuid;
  v_version_id uuid;
  rec record;
begin
  for rec in
    select distinct on (body) id, venue, version, body, created_at
    from venue_prompt_versions
    where prompt_type = 'formatter'
    order by body, created_at asc
  loop
    -- Create the trader prompt
    insert into trader_prompts (name, slug)
    values (
      'Trader Prompt (migrated from ' || rec.venue || ' v' || rec.version || ')',
      'trader-migrated-' || rec.venue || '-v' || rec.version || '-' || substr(rec.id::text, 1, 8)
    )
    returning id into v_prompt_id;

    -- Create the version
    insert into trader_prompt_versions (prompt_id, version, body, created_at)
    values (v_prompt_id, 1, rec.body, rec.created_at)
    returning id into v_version_id;
  end loop;
end
$$;

-- Expand frequency_minutes constraint to support 4h/12h/24h
alter table bot_runtime_configs drop constraint if exists bot_runtime_configs_frequency_minutes_check;
alter table bot_runtime_configs add constraint bot_runtime_configs_frequency_minutes_check
  check (frequency_minutes in (1, 5, 15, 30, 60, 240, 720, 1440));
