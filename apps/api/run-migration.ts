import { sql } from "./src/db.js";

async function main() {
  console.log("Applying migration 016_bot_positions.sql...");
  try {
    await sql`
      create table if not exists bot_positions (
        id uuid primary key default gen_random_uuid(),
        bot_id uuid not null references bots(id) on delete cascade,
        symbol text not null,
        quantity numeric not null,
        avg_entry_price numeric not null,
        cost_basis_usd numeric not null,
        stop_loss_price numeric not null,
        take_profit_price numeric not null,
        safety_stop_price numeric,
        safety_stop_order_id text,
        status text not null check (status in ('active', 'closed')) default 'active',
        opened_at timestamptz not null default now(),
        closed_at timestamptz,
        close_reason text check (close_reason in ('take_profit', 'stop_loss', 'safety_stop', 'run_sell', 'manual')),
        realized_pnl_usd numeric,
        realized_fees_usd numeric,
        buy_execution_id uuid references executions(id) on delete set null,
        close_execution_id uuid references executions(id) on delete set null,
        created_at timestamptz not null default now()
      );
    `;
    await sql`create index if not exists bot_positions_bot_status_idx on bot_positions (bot_id, status);`;
    await sql`create index if not exists bot_positions_symbol_status_idx on bot_positions (symbol, status);`;
    await sql`create index if not exists bot_positions_active_idx on bot_positions (status) where status = 'active';`;
    console.log("Migration applied successfully.");
  } catch (err) {
    console.error("Migration failed:", err);
    process.exit(1);
  }
  process.exit(0);
}

main();
