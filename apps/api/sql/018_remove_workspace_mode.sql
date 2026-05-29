-- Remove legacy workspace-mode and promotion vocabulary.
-- Venue is the source of truth for execution context; research candidates link
-- directly to the disabled venue bot they create.

alter table if exists bots
  drop column if exists workspace_mode;

drop index if exists bots_workspace_mode_idx;

alter table if exists research_candidates
  add column if not exists bot_id uuid references bots(id) on delete set null;

do $$
begin
  if exists (
    select 1 from information_schema.columns
    where table_name = 'research_candidates' and column_name = 'promoted_bot_id'
  ) then
    update research_candidates
    set bot_id = coalesce(
      bot_id,
      promoted_bot_id,
      nullif(metrics->>'venueBotId', '')::uuid,
      nullif(metrics->>'paperBotId', '')::uuid
    )
    where bot_id is null
      and (
        promoted_bot_id is not null
        or nullif(metrics->>'venueBotId', '') is not null
        or nullif(metrics->>'paperBotId', '') is not null
      );
  else
    update research_candidates
    set bot_id = coalesce(
      bot_id,
      nullif(metrics->>'venueBotId', '')::uuid,
      nullif(metrics->>'paperBotId', '')::uuid
    )
    where bot_id is null
      and (
        nullif(metrics->>'venueBotId', '') is not null
        or nullif(metrics->>'paperBotId', '') is not null
      );
  end if;
end $$;

alter table if exists research_candidates
  drop column if exists promoted_bot_id;

drop index if exists research_candidates_promoted_bot_idx;
drop index if exists approval_requests_live_promotion_candidate_idx;
