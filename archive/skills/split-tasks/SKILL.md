---
name: split-tasks
description: Generate focused sub-agent prompts from the backlog and write them to `.claude/tasks/*.md` for parallel launch. Use when independent backlog items can run as separate Claude Code sessions at once.
---

# split-tasks

Turn independent backlog items into ready-to-launch sub-agent prompts. The task `.md` files are **ephemeral** — launch then delete.

## Steps
1. **Read `BACKLOG.md`** — identify items with no shared files / no ordering dependency (safe to run in parallel).
2. **Write a prompt per item** to `.claude/tasks/<name>.md`: goal, the exact files/dirs in scope, acceptance check (usually `pnpm verify`), and a branch name (`feat/<name>`).
3. **Tag each** prompt header: cloud/local, opus/sonnet/haiku, estimated time. Heavy compute → cloud; deep reasoning → opus.
4. **Output a summary table** — task | file | where (cloud/local) | model | est — so the human knows what to launch where.
5. **Clean up:** delete any pre-existing `.claude/tasks/*.md` from an older backlog cycle before writing the new set, and remind the human to delete each task file once its agent is launched.

## Verify
- One `.claude/tasks/<name>.md` per parallelizable item; each names its scoped files + acceptance check.
- Summary table printed; no stale task files left from a prior cycle.
