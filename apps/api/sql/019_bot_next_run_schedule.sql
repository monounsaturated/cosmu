alter table bot_runtime_configs
  add column if not exists next_run_at timestamptz;

update bot_runtime_configs
set next_run_at = case
  when last_run_finished_at is not null then last_run_finished_at + make_interval(secs => frequency_minutes * 60)
  when last_run_started_at is not null then last_run_started_at + make_interval(secs => frequency_minutes * 60)
  else created_at
end
where enabled = true
  and next_run_at is null;

create index if not exists bot_runtime_configs_due_idx
  on bot_runtime_configs (enabled, next_run_at)
  where enabled = true;
