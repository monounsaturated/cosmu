import postgres from "postgres";
import { env } from "./env.js";

const databaseUrl = new URL(env.DATABASE_URL);
const usesTransactionPooler =
  databaseUrl.searchParams.get("pgbouncer") === "true" ||
  databaseUrl.hostname.includes("pooler.supabase.com");

export const sql = postgres(env.DATABASE_URL, {
  max: 5,
  // Supabase's PgBouncer transaction pooler can route later statements to a
  // different backend connection, where postgres.js prepared statements do not
  // exist. Disable them only for pooler URLs; direct Postgres keeps defaults.
  prepare: !usesTransactionPooler,
  ssl: env.DATABASE_SSL === "false" ? false : "require"
});
