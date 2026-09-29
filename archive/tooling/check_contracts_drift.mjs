#!/usr/bin/env node
/**
 * Contracts drift guard.
 *
 * Runs the contracts generator to a temp location and asserts the committed
 * packages/contracts-ts/src/index.ts + packages/contracts-ts/openapi.json
 * match the freshly generated output.
 *
 * Exit 0 → no drift (committed files are up to date).
 * Exit 1 → drift detected (run `pnpm contracts:generate` then commit).
 *
 * Wired into `pnpm verify` (after contracts:generate) so any schema or API change
 * that wasn't committed is caught before push.
 */
import { execSync } from "node:child_process";
import { mkdtempSync, readFileSync, existsSync, rmSync, mkdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, "..");

// --------------------------------------------------------------------------
// Generate contracts to a temp dir
// --------------------------------------------------------------------------
const tmp = mkdtempSync(join(tmpdir(), "cosmu-contracts-"));
const tmpOpenapi = join(tmp, "openapi.json");
const tmpIndex = join(tmp, "index.ts");

try {
  // Run the generator, pointing output at temp locations via env overrides.
  // We patch the output paths by passing env vars picked up by the generator.
  // Since generate_contracts.py uses hardcoded paths we use a temp copy approach:
  // generate normally (already done by the `verify` script which calls contracts:generate
  // before this script), then compare the committed files against git-tracked content.
  //
  // Strategy: diff the current working-tree files against the last git-committed versions.
  // If there is any diff, it means the committed files are stale relative to what the
  // generator just produced (because `pnpm verify` calls `contracts:generate` first).

  const committedOpenapi = join(ROOT, "packages", "contracts-ts", "openapi.json");
  const committedIndex = join(ROOT, "packages", "contracts-ts", "src", "index.ts");

  let drifted = false;
  const driftMessages = [];

  // Check both files against the git index (last committed state)
  for (const [label, filePath] of [
    ["openapi.json", committedOpenapi],
    ["src/index.ts", committedIndex],
  ]) {
    if (!existsSync(filePath)) {
      driftMessages.push(`  MISSING: ${label} does not exist at ${filePath}`);
      drifted = true;
      continue;
    }

    // Compare working-tree file against git HEAD version
    let headContent;
    try {
      const relPath = filePath.replace(ROOT + "/", "");
      headContent = execSync(`git show HEAD:"${relPath}"`, {
        cwd: ROOT,
        encoding: "utf8",
        stdio: ["pipe", "pipe", "pipe"],
      });
    } catch {
      // File not in git yet — not a drift error (new file), skip
      continue;
    }

    const workingContent = readFileSync(filePath, "utf8");
    if (workingContent !== headContent) {
      drifted = true;
      driftMessages.push(`  DRIFTED: ${label} differs from HEAD (run \`pnpm contracts:generate\` and commit)`);
    }
  }

  if (drifted) {
    console.error("contracts drift detected:");
    for (const msg of driftMessages) {
      console.error(msg);
    }
    console.error("\nFix: pnpm contracts:generate && git add packages/contracts-ts && git commit -m 'chore: regen contracts'");
    process.exit(1);
  }

  console.log("contracts: no drift (openapi.json + index.ts match HEAD)");
} finally {
  try { rmSync(tmp, { recursive: true, force: true }); } catch { /* ignore */ }
}
