#!/usr/bin/env node
/**
 * Destructive local/test helper.
 *
 * Usage:
 *   set -a && source .env.local && set +a && ALLOW_DB_RESET=true node scripts/reset-local-db.mjs
 *
 * Refuses to run unless ALLOW_DB_RESET=true. Also refuses Supabase-like URLs unless
 * ALLOW_REMOTE_DB_RESET=true is explicitly set.
 */
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const postgres = require(
  "../node_modules/.pnpm/postgres@3.4.9/node_modules/postgres/cjs/src/index.js"
);

const url = process.env.DATABASE_URL;
if (!url) {
  console.error("DATABASE_URL not set");
  process.exit(1);
}

if (process.env.ALLOW_DB_RESET !== "true") {
  console.error("Refusing to reset DB. Set ALLOW_DB_RESET=true for local/test resets.");
  process.exit(1);
}

const looksRemote = /supabase|pooler|aws|railway|render|neon|cloud/i.test(url);
if (looksRemote && process.env.ALLOW_REMOTE_DB_RESET !== "true") {
  console.error("Refusing to reset a remote-looking DATABASE_URL without ALLOW_REMOTE_DB_RESET=true.");
  process.exit(1);
}

const client = postgres(url, {
  max: 1,
  ssl: process.env.DATABASE_SSL === "false" ? false : "require"
});

const sqlDir = join(process.cwd(), "apps/api/sql");
const files = readdirSync(sqlDir)
  .filter((file) => file.endsWith(".sql"))
  .sort();

try {
  console.log("Dropping and recreating public schema...");
  await client.unsafe("drop schema if exists public cascade; create schema public;");

  for (const file of files) {
    const fullPath = join(sqlDir, file);
    console.log(`Applying ${file}`);
    await client.unsafe(readFileSync(fullPath, "utf8"));
  }

  console.log("Local/test database reset complete.");
} catch (error) {
  console.error("Reset failed:", error instanceof Error ? error.message : error);
  process.exitCode = 1;
} finally {
  await client.end({ timeout: 5 });
}
