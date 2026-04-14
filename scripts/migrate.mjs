#!/usr/bin/env node
/**
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
