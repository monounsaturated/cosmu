-- Rename the legacy "formatter" phase to its real name: "trader".
-- The phase-2 prompt was always the trader prompt; "formatter" was a misnomer.
-- This migration is idempotent and non-destructive.

-- 1. Allow the new prompt_type value. We keep 'formatter' permitted too so older
--    idempotent seed migrations remain safe to re-run; new writes use 'trader'.
alter table venue_prompt_versions
  drop constraint if exists venue_prompt_versions_prompt_type_check;
alter table venue_prompt_versions
  add constraint venue_prompt_versions_prompt_type_check
  check (prompt_type in ('formatter', 'trader'));

-- 2. Migrate existing rows to the new value.
update venue_prompt_versions set prompt_type = 'trader' where prompt_type = 'formatter';

-- 3. Rename the runs FK column that tracked which prompt version a run used.
do $$
begin
  if exists (
    select 1 from information_schema.columns
    where table_name = 'runs' and column_name = 'formatter_prompt_version_id'
  ) and not exists (
    select 1 from information_schema.columns
    where table_name = 'runs' and column_name = 'trader_prompt_version_id'
  ) then
    alter table runs rename column formatter_prompt_version_id to trader_prompt_version_id;
  end if;
end $$;
