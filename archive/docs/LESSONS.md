# Lessons from mistakes

A short, blunt list of mistakes we have actually made and the rule that prevents the repeat.
Append a one-liner whenever a mistake costs real time. Keep it lean.

## Worktree-isolation discipline
- **Mistake:** agents (and sessions) writing to `main`/the orchestrator checkout via absolute
  `/Users/device/cosmu/…` paths from inside a worktree → commits landed on the wrong branch and
  drifted `main`.
- **Rule:** in a worktree, do **all** git/edit work **inside that worktree**, with relative paths.
  One branch per agent; never two agents in one working tree. The orchestrator rebases before
  committing `main` and watches for stray untracked files.

## Don't re-run the full pytest suite repeatedly
- **Mistake:** running the whole `engine:test` suite serially on the M2 — slow, and it OOMs under
  memory pressure (same for `next build`).
- **Rule:** run **affected files first**, `-n auto --dist=loadfile`, redirect output to a file
  (never `| tail`). Run the full `pnpm verify` once before pushing (that local pass is the gate —
  CI is manual-dispatch only). If RAM is tight, offload `next build` to Actions via
  `gh workflow run verify.yml`.

## Idempotent / incremental ingest
- **Mistake:** re-ingesting overlapping windows inflated counts and re-did work; non-incremental
  pulls were slow and risked autocorrelation/look-ahead bleaks.
- **Rule:** ingest is **append-only + point-in-time** (`available_at` / `read_asof`), idempotent,
  and incremental — re-running a pass must be a no-op where data already exists. Stride-sample
  non-overlapping windows for honest stats.

## Verify metric renames end-to-end
- **Mistake:** renaming a metric/field in one layer left the other layers (engine model → OpenAPI →
  generated `contracts-ts` → UI) out of sync, silently breaking a surface.
- **Rule:** a rename is done only when it is green **end-to-end** — add the field on the engine
  Pydantic model first, regenerate contracts (`pnpm contracts:generate`), and confirm the UI reads
  the generated type. Never hand-type TS models; the pre-push hook fails on contracts drift.
