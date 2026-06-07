#!/usr/bin/env node
/**
 * Destructive local/test helper — resets the SQLite control-plane database.
 *
 * Usage:
 *   ALLOW_DB_RESET=true node scripts/reset-local-db.mjs [--db-path <path>]
 *
 * Refuses to run unless ALLOW_DB_RESET=true.
 * The schema source of truth is apps/engine/cosmu/knowledge/schema.sql (SQLite DDL).
 * The default DB path matches the engine's default: .cosmu/cosmu.sqlite3
 */
import { readFileSync, mkdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, "..");

if (process.env.ALLOW_DB_RESET !== "true") {
  console.error("Refusing to reset DB. Set ALLOW_DB_RESET=true for local/test resets.");
  process.exit(1);
}

// Resolve DB path: CLI arg > env > default
const argIdx = process.argv.indexOf("--db-path");
const dbPath =
  argIdx !== -1
    ? process.argv[argIdx + 1]
    : process.env.COSMU_SQLITE_PATH ?? join(ROOT, ".cosmu", "cosmu.sqlite3");

const schemaPath = join(ROOT, "apps", "engine", "cosmu", "knowledge", "schema.sql");

// Ensure the parent directory exists
mkdirSync(dirname(dbPath), { recursive: true });

// Use Node's built-in SQLite (Node >= 22.5 experimental; Node 25 stable-ish)
let DatabaseSync;
try {
  ({ DatabaseSync } = await import("node:sqlite"));
} catch {
  console.error(
    "node:sqlite not available (requires Node >= 22.5). " +
    "Run: PYTHONPATH=apps/engine python3 -c \"" +
    "import sqlite3, pathlib; " +
    "db=sqlite3.connect('" + dbPath.replace(/'/g, "\\'") + "'); " +
    "db.executescript(pathlib.Path('" + schemaPath.replace(/'/g, "\\'") + "').read_text()); " +
    "db.commit()\"",
  );
  process.exit(1);
}

const schema = readFileSync(schemaPath, "utf8");

console.log(`Resetting SQLite DB at: ${dbPath}`);
console.log(`Schema source: ${schemaPath}`);

const db = new DatabaseSync(dbPath);

// Drop all user tables in dependency order, then reapply the schema
db.exec(`
  PRAGMA foreign_keys = OFF;
  DROP TABLE IF EXISTS experiments;
  DROP TABLE IF EXISTS trials;
  DROP TABLE IF EXISTS gate_verdicts;
  DROP TABLE IF EXISTS holdout_ledger;
  DROP TABLE IF EXISTS asset_class_gates;
  DROP TABLE IF EXISTS mind_reflections;
  DROP TABLE IF EXISTS alt_data;
  DROP TABLE IF EXISTS events;
  DROP TABLE IF EXISTS llm_calls;
  DROP TABLE IF EXISTS costs;
  DROP TABLE IF EXISTS policies;
  DROP TABLE IF EXISTS recommendations;
  DROP TABLE IF EXISTS research_notes;
  DROP TABLE IF EXISTS sources;
  DROP TABLE IF EXISTS skills;
  DROP TABLE IF EXISTS live_caps;
  DROP TABLE IF EXISTS live_toggle;
  DROP TABLE IF EXISTS tracks;
  DROP TABLE IF EXISTS positions;
  DROP TABLE IF EXISTS portfolio_snapshots;
  DROP TABLE IF EXISTS executions;
  DROP TABLE IF EXISTS runs;
  DROP TABLE IF EXISTS backtests;
  DROP TABLE IF EXISTS strategy_versions;
  DROP TABLE IF EXISTS strategies;
  DROP TABLE IF EXISTS instruments;
  DROP TABLE IF EXISTS venues;
  PRAGMA foreign_keys = ON;
`);

db.exec(schema);
db.close();

console.log("Local SQLite database reset complete.");
