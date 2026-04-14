import { sql } from "./db.js";

async function run() {
  const res = await sql`
    update bot_runtime_configs
    set venue = 'binance-testnet'
    where mode = 'testnet' and venue = 'binance'
    returning bot_id, venue, mode
  `;
  console.log(`Migrated ${res.length} bots to binance-testnet`);
  for (const r of res) console.log(r);
  await sql.end();
}

run();
