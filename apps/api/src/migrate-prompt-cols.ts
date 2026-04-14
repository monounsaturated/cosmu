import { sql } from "./db.js";

const run = async () => {
  await sql`alter table runs add column if not exists prompt_system text`;
  await sql`alter table runs add column if not exists prompt_user text`;
  console.log("✓ prompt_system and prompt_user on runs");

  await sql`alter table bot_runtime_configs add column if not exists budget_usdt numeric not null default 100`;
  console.log("✓ budget_usdt on bot_runtime_configs");

  await sql`alter table bot_runtime_configs drop constraint if exists bot_runtime_configs_venue_check`;
  await sql`alter table bot_runtime_configs add constraint bot_runtime_configs_venue_check check (venue in ('binance', 'binance-testnet'))`;
  console.log("✓ venue check updated on bot_runtime_configs");

  await sql`alter table executions drop constraint if exists executions_venue_check`;
  await sql`alter table executions add constraint executions_venue_check check (venue in ('binance', 'binance-testnet'))`;
  console.log("✓ venue check updated on executions");

  console.log("All migrations done.");
  await sql.end();
};

run().catch((e) => { console.error(e); process.exit(1); });
