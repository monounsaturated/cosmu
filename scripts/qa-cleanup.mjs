#!/usr/bin/env node
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const postgres = require(
  "../node_modules/.pnpm/postgres@3.4.9/node_modules/postgres/cjs/src/index.js"
);

const url = process.env.DATABASE_URL;
if (!url) { console.error("DATABASE_URL not set"); process.exit(1); }

const sql = postgres(url, { max: 1, ssl: "require" });

try {
  // Delete QA test bots created during local verification.
  const deleted = await sql`
    delete from bots
    where slug like 'qa-%'
       or name ilike 'QA %'
    returning id, name, slug
  `;
  console.log("Deleted:", deleted);

  // Delete QA experiments + cascade candidates/approvals
  const experiments = await sql`
    delete from research_experiments
    where title ilike 'QA %'
       or hypothesis ilike 'QA %'
    returning id, title
  `;
  console.log("Deleted experiments:", experiments);

  const approvals = await sql`
    delete from approval_requests
    where title ilike '%QA %'
    returning id, title
  `;
  console.log("Deleted approvals:", approvals);
} catch (err) {
  console.error(err.message);
  process.exitCode = 1;
} finally {
  await sql.end({ timeout: 5 });
}
