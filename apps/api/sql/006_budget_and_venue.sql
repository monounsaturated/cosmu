-- Add budget_usdt to bot_runtime_configs
alter table bot_runtime_configs add column if not exists budget_usdt numeric not null default 100;

-- Allow 'binance-testnet' as a venue value
alter table bot_runtime_configs drop constraint if exists bot_runtime_configs_venue_check;
alter table bot_runtime_configs add constraint bot_runtime_configs_venue_check
  check (venue in ('binance', 'binance-testnet'));

-- Same for executions table
alter table executions drop constraint if exists executions_venue_check;
alter table executions add constraint executions_venue_check
  check (venue in ('binance', 'binance-testnet'));
