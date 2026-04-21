-- Per-bot position ledger. Replaces reliance on Binance OCO state for SL/TP and
-- per-bot P&L attribution. Multiple bots can hold the same symbol simultaneously;
-- each row is a bot's own slice with its own SL/TP.

create table if not exists bot_positions (
  id uuid primary key default gen_random_uuid(),
  bot_id uuid not null references bots(id) on delete cascade,
  symbol text not null,

  -- Open state
  quantity numeric not null,                 -- remaining open qty
  avg_entry_price numeric not null,
  cost_basis_usd numeric not null,           -- fees included, used for realized P&L
  stop_loss_price numeric not null,
  take_profit_price numeric not null,

  -- Guardian-placed Binance safety net (STOP_LOSS at a wider level than app SL)
  safety_stop_price numeric,
  safety_stop_order_id text,

  -- Lifecycle
  status text not null check (status in ('active', 'closed')) default 'active',
  opened_at timestamptz not null default now(),
  closed_at timestamptz,
  close_reason text check (close_reason in ('take_profit', 'stop_loss', 'safety_stop', 'run_sell', 'manual')),
  realized_pnl_usd numeric,
  realized_fees_usd numeric,

  -- Audit trail
  buy_execution_id uuid references executions(id) on delete set null,
  close_execution_id uuid references executions(id) on delete set null,

  created_at timestamptz not null default now()
);

create index if not exists bot_positions_bot_status_idx on bot_positions (bot_id, status);
create index if not exists bot_positions_symbol_status_idx on bot_positions (symbol, status);
create index if not exists bot_positions_active_idx on bot_positions (status) where status = 'active';
