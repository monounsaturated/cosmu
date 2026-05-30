// module: Migrate-on-start runner. Applies any not-yet-applied apps/api/sql/*.sql
// files in filename order, tracked in a schema_migrations ledger, then returns.
//
// ─────────────────────────────────────────────────────────────────────────────
// HOW MIGRATIONS WORK IN THIS REPO (read this before adding a schema change):
//
//   1. Add a new file `apps/api/sql/NNN_short_name.sql` (NNN = next number, zero-padded).
//   2. Write it IDEMPOTENTLY — `create table if not exists`, `add column if not exists`,
//      `drop constraint if exists` before re-adding, guard renames with information_schema.
//      It may get re-run, so it must be safe to run twice.
//   3. Commit and deploy. That's it. This runner applies it automatically on the next
//      boot (Railway runs `pnpm start`, which calls runPendingMigrations() before listen).
//
// There is NO manual DB step. Do not hand-run scripts/apply-sql.mjs for production —
// that's only a local convenience. The ledger below is the source of truth.
//
// First run against an already-provisioned database (the `runs` table already exists)
// is "baselined": every migration up to and including BASELINE_THROUGH is recorded as
// applied WITHOUT being re-run, since those were applied by hand before this runner
// existed. Migrations after it run normally. A fresh/empty database runs everything.
// ─────────────────────────────────────────────────────────────────────────────
import { readFileSync, readdirSync, existsSync } from "node:fs";
import { join } from "node:path";
import { sql } from "./db.js";

// Highest migration that was applied manually before the migrate-on-start runner
// was introduced. Everything <= this is baselined (recorded, not re-run) on first
// run against a pre-existing DB. Do NOT change this when adding new migrations.
const BASELINE_THROUGH = "022_sources_indexes.sql";

const resolveSqlDir = (): string => {
  const candidates = [
    join(process.cwd(), "sql"),
    join(process.cwd(), "apps/api/sql"),
    join(process.cwd(), "../sql")
  ];
  const found = candidates.find((dir) => existsSync(dir));
  if (!found) {
    throw new Error(`Could not locate apps/api/sql migrations dir (tried: ${candidates.join(", ")})`);
  }
  return found;
};

export const runPendingMigrations = async () => {
  const sqlDir = resolveSqlDir();
  const files = readdirSync(sqlDir)
    .filter((file) => file.endsWith(".sql"))
    .sort();

  await sql`
    create table if not exists schema_migrations (
      filename text primary key,
      applied_at timestamptz not null default now()
    )
  `;

  const appliedRows = await sql<{ filename: string }[]>`select filename from schema_migrations`;
  const applied = new Set(appliedRows.map((r) => r.filename));

  // Baseline: first run against an already-provisioned DB. Record legacy migrations
  // as applied without re-running them (they were applied by hand previously).
  if (applied.size === 0) {
    const [{ exists }] = await sql<{ exists: boolean }[]>`
      select to_regclass('public.runs') is not null as exists
    `;
    if (exists) {
      const baseline = files.filter((file) => file <= BASELINE_THROUGH);
      for (const file of baseline) {
        await sql`insert into schema_migrations (filename) values (${file}) on conflict do nothing`;
        applied.add(file);
      }
      console.log(`[migrate] baselined ${baseline.length} pre-existing migration(s) through ${BASELINE_THROUGH}`);
    }
  }

  const pending = files.filter((file) => !applied.has(file));
  if (pending.length === 0) {
    console.log("[migrate] schema up to date");
    return { applied: [] as string[] };
  }

  const newlyApplied: string[] = [];
  for (const file of pending) {
    const body = readFileSync(join(sqlDir, file), "utf8");
    console.log(`[migrate] applying ${file}`);
    try {
      await sql.unsafe(body);
      await sql`insert into schema_migrations (filename) values (${file}) on conflict do nothing`;
      newlyApplied.push(file);
    } catch (error) {
      // Abort startup: a half-migrated schema must not start serving traffic.
      const message = error instanceof Error ? error.message : String(error);
      throw new Error(`Migration ${file} failed: ${message}`);
    }
  }

  console.log(`[migrate] applied ${newlyApplied.length} migration(s): ${newlyApplied.join(", ")}`);
  return { applied: newlyApplied };
};
