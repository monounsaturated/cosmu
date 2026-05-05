import postgres from "postgres";
import { env } from "./env.js";

export const sql = postgres(env.DATABASE_URL, {
  max: 5,
  ssl: env.DATABASE_SSL === "false" ? false : "require"
});
