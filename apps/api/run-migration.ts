import { env } from "./src/env.js";
import { sql } from "./src/db.js";

async function main() {
  console.log("Applying migration 007_add_oco_order_id.sql...");
  try {
    await sql`alter table executions add column oco_order_id text;`;
    console.log("Migration applied successfully.");
  } catch (err) {
    if (err instanceof Error && err.message.includes("already exists")) {
      console.log("Migration already applied.");
    } else {
      console.error("Migration failed:", err);
    }
  }
  process.exit(0);
}

main();