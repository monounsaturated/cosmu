-- Normalize research vocabulary after removing workspace/pro/live/paper modes.
-- Existing rows are preserved and mapped to the venue-neutral status names.

alter table if exists agent_steps
  drop constraint if exists agent_steps_scope_type_check;

update agent_steps
set scope_type = case scope_type
  when 'light_run' then 'bot_run'
  when 'paper_bot_run' then 'bot_run'
  when 'pro_run' then 'bot_run'
  when 'research_experiment' then 'research'
  else scope_type
end;

alter table if exists agent_steps
  add constraint agent_steps_scope_type_check check (scope_type in ('bot_run', 'research'));

alter table if exists research_experiments
  add column if not exists progress_status text not null default 'none';

do $$
begin
  if exists (
    select 1 from information_schema.columns
    where table_name = 'research_experiments' and column_name = 'promotion_status'
  ) then
    update research_experiments
    set progress_status = case promotion_status
      when 'paper_auto' then 'candidate_created'
      when 'live_pending_approval' then 'bot_created'
      when 'live_approved' then 'bot_created'
      when 'live_rejected' then 'rejected'
      else progress_status
    end;
  end if;
end $$;

alter table if exists research_experiments
  drop constraint if exists research_experiments_status_check;

update research_experiments
set status = case status
  when 'paper_candidate' then 'candidate'
  when 'live_candidate' then 'candidate'
  else status
end;

alter table if exists research_experiments
  add constraint research_experiments_status_check check (status in ('draft', 'running', 'rejected', 'candidate'));

alter table if exists research_experiments
  drop constraint if exists research_experiments_promotion_status_check;
alter table if exists research_experiments
  drop constraint if exists research_experiments_progress_status_check;
alter table if exists research_experiments
  add constraint research_experiments_progress_status_check
  check (progress_status in ('none', 'candidate_created', 'bot_created', 'rejected'));

alter table if exists research_experiments
  drop column if exists promotion_status;

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
  drop constraint if exists research_candidates_status_check;

update research_candidates
set status = case status
  when 'paper_ready' then 'ready'
  when 'paper_running' then 'bot_created'
  when 'paper_rejected' then 'rejected'
  when 'live_candidate' then 'bot_created'
  else status
end;

update research_candidates
set name = replace(name, ' paper candidate', ' research candidate')
where name like '% paper candidate%';

update research_candidates
set risk_notes = replace(risk_notes, 'live approval', 'execution is enabled')
where risk_notes like '%live approval%';

update research_candidates
set metrics = (
  coalesce(metrics, '{}'::jsonb)
  - 'paperBotId'
  - 'paperBotStatus'
  - 'liveEligible'
) || jsonb_strip_nulls(jsonb_build_object(
  'venueBotId', coalesce(metrics->>'venueBotId', metrics->>'paperBotId', bot_id::text),
  'venueBotStatus', coalesce(metrics->>'venueBotStatus', case when metrics ? 'paperBotStatus' then 'created_disabled' else null end),
  'executionEligible', case
    when metrics ? 'liveEligible' then (metrics->>'liveEligible')::boolean
    else null
  end
))
where metrics is not null
  and (metrics ? 'paperBotId' or metrics ? 'paperBotStatus' or metrics ? 'liveEligible');

alter table if exists research_candidates
  add constraint research_candidates_status_check check (status in ('ready', 'bot_created', 'rejected'));

alter table if exists research_candidates
  drop column if exists promoted_bot_id;

drop index if exists research_candidates_promoted_bot_idx;
drop index if exists bots_workspace_mode_idx;
drop index if exists approval_requests_live_promotion_candidate_idx;

alter table if exists bots
  drop column if exists workspace_mode;

update approval_requests
set request_type = 'dangerous_action'
where request_type = 'live_promotion';

alter table if exists approval_requests
  drop constraint if exists approval_requests_request_type_check;
alter table if exists approval_requests
  add constraint approval_requests_request_type_check check (request_type in ('dangerous_action', 'connector_permission'));

alter table if exists evaluation_jobs
  drop constraint if exists evaluation_jobs_kind_check;
update evaluation_jobs
set kind = 'backtest'
where kind = 'paper_backtest';
alter table if exists evaluation_jobs
  add constraint evaluation_jobs_kind_check check (kind in ('backtest', 'ml_validation'));

alter table if exists paper_bot_runs rename to research_bot_runs;
alter index if exists paper_bot_runs_candidate_idx rename to research_bot_runs_candidate_idx;

alter table if exists paper_portfolios rename to simulation_portfolios;
alter index if exists paper_portfolios_session_idx rename to simulation_portfolios_session_idx;

alter table if exists paper_trades rename to simulation_trades;
alter index if exists paper_trades_portfolio_idx rename to simulation_trades_portfolio_idx;

update research_data_sources
set name = replace(name, ' paper data', ' data'),
    config = case
      when config->>'mode' = 'paper_data_first' then jsonb_set(config, '{mode}', '"data_first"'::jsonb, false)
      else config
    end,
    updated_at = now()
where name like '% paper data%'
  or config->>'mode' = 'paper_data_first';
