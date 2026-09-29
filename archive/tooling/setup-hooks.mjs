#!/usr/bin/env node
/**
 * Enable the repo's git hooks by pointing core.hooksPath at ./.githooks.
 *
 * Wired into the `prepare` lifecycle, so a plain `pnpm install` turns on the
 * pre-push gate (naming + contracts drift + engine tests + typecheck — see
 * .githooks/pre-push; push = deploy, so this is THE gate) for every
 * developer — no husky, no extra dependency.
 *
 * Safe to run anywhere: it no-ops when there is no .git directory (Railway /
 * Vercel build images, CI checkouts, tarball installs), so it can never fail an
 * install or a deploy build.
 *
 * Manual equivalent (the one-line local enable step):
 *   git config core.hooksPath .githooks
 */
import { existsSync } from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";

const root = path.resolve(new URL("..", import.meta.url).pathname);
const hooksPath = ".githooks";

if (!existsSync(path.join(root, ".git"))) {
  console.log("[setup-hooks] no .git directory here — skipping (hooks not needed in this context).");
  process.exit(0);
}

try {
  execFileSync("git", ["config", "core.hooksPath", hooksPath], { cwd: root, stdio: "inherit" });
  // A stale per-worktree override (.git/worktrees/<wt>/config.worktree) can SHADOW the value we just set,
  // leaving the pre-push gate silently dead even though the command above succeeded. Verify the EFFECTIVE
  // resolution and surface a shadowing override loudly instead of claiming the gate is on.
  const resolved = execFileSync("git", ["config", "core.hooksPath"], { cwd: root }).toString().trim();
  if (resolved !== hooksPath) {
    console.warn(
      `[setup-hooks] WARNING: core.hooksPath resolves to '${resolved}', not '${hooksPath}' — a per-worktree ` +
      `override is shadowing it, so the pre-push gate is OFF here. Fix: git config --worktree core.hooksPath ${hooksPath}`,
    );
  } else {
    console.log(`[setup-hooks] core.hooksPath -> ${hooksPath} (pre-push gate enabled: naming + drift + engine tests + typecheck).`);
  }
} catch (error) {
  // Never break install/deploy just because hooks couldn't be configured.
  const msg = error instanceof Error ? error.message : String(error);
  console.warn(`[setup-hooks] could not set core.hooksPath (${msg}); skipping.`);
}
