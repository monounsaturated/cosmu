import { sql } from "./db.js";

const run = async () => {
  await sql`alter table runs add column if not exists prompt_system text`;
  await sql`alter table runs add column if not exists prompt_user text`;
  console.log("Migration done: added prompt_system and prompt_user to runs");
  await sql.end();
};

run().catch((e) => { console.error(e); process.exit(1); });
