alter table bot_runtime_configs
  add column if not exists killed_at timestamptz;

alter table executions
  add column if not exists stop_loss_price numeric,
  add column if not exists take_profit_price numeric;
