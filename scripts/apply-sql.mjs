#!/usr/bin/env node
/**
 * Apply a single SQL file against DATABASE_URL.
 * Usage:
 *   set -a && source .env.local && set +a && node scripts/apply-sql.mjs apps/api/sql/022_sources_indexes.sql
 */
import { readFileSync } from "node:fs";
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

const file = process.argv[2];
if (!file) {
  console.error("Usage: node scripts/apply-sql.mjs <sql-file>");
  process.exit(1);
}

const sql = readFileSync(file, "utf8");

const client = postgres(url, {
  max: 1,
  ssl: process.env.DATABASE_SSL === "false" ? false : "require"
});

try {
  await client.unsafe(sql);
  console.log(`Applied ${file}`);
} catch (err) {
  console.error(`Failed to apply ${file}:`, err.message);
  process.exitCode = 1;
} finally {
  await client.end({ timeout: 5 });
}
