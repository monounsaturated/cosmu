#!/usr/bin/env node
/**
 * LEGACY local-only ad-hoc runner (requires psql). Superseded for production by
 * apps/api/src/db-migrate.ts (migrate-on-start). To add a schema change, drop a new
 * idempotent file in apps/api/sql/ and deploy — see AGENTS.md → "Database Migrations".
 *
 * Run: set -a && source .env.local && set +a && node scripts/migrate.mjs
 */
import { execSync } from "node:child_process";

const url = process.env.DATABASE_URL;
if (!url) { console.error("DATABASE_URL not set"); process.exit(1); }

const statements = [
  "ALTER TABLE runs ADD COLUMN IF NOT EXISTS prompt_system text",
  "ALTER TABLE runs ADD COLUMN IF NOT EXISTS prompt_user text"
];

for (const stmt of statements) {
  console.log(`→ ${stmt}`);
  execSync(`psql "${url}" -c "${stmt}"`, { stdio: "inherit" });
}

console.log("Migration complete.");
