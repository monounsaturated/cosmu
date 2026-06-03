---
name: fan-out
description: Orchestrator playbook — turn one big feature request into parallel sub-agents that don't collide (one branch each), then run a merge train into main. Use when a feature is large enough to split across multiple agents.
---

# fan-out

The **orchestrator** playbook. The lead chat decomposes a big request into independent work-streams, launches one agent per stream, then merges their PRs into `main` one at a time. Hard-won rule: agents collide unless each owns its own branch and (when heavy) its own worktree.

## Steps
1. **Decompose into independent work-streams.** Cut the request along **file boundaries** — each stream touches a different set of files/dirs with minimal overlap. Overlapping streams are not parallel; sequence them or merge them into one stream.
2. **One branch per agent — `feat/<stream>`.** This is the hard rule: **NEVER run two agents in the same working directory/branch** (proven to cause branch-stomping — one agent's commits clobber the other's). Heavy or many-file streams get their **own git worktree** so their builds and edits never touch a sibling's tree.
3. **Write a focused prompt per stream.** Delegate to `/split-tasks`, which writes `.claude/tasks/*.md` — goal, exact in-scope files, acceptance check, branch name. Tag each: **cloud/local** + **opus/sonnet/haiku** + **est time** (heavy compute → cloud; deep reasoning → opus; mechanical/UI → sonnet).
4. **Each agent runs the same contract:** branch off the **latest `main`** → implement only its scoped files → `pnpm verify` (must be green) → push → open a PR. **Never push to `main` directly.**
5. **Merge train (orchestrator-only).** Merge PRs into `main` **one at a time**. After each merge, **re-check the next PR's mergeability** (`gh pr view <n> --json mergeable`), resolve any conflicts the merge introduced, and only then merge the next. Don't batch-merge — a clean PR can go stale the instant the one before it lands.
6. **Confirm the deploy after each merge.** Run `/deploy-iterate` to verify the deploy is healthy (push = deploy) before merging the next PR. A red deploy halts the train until it's green.
7. **Clean up.** `gh pr merge --delete-branch` on every merged PR. **Never merge a branch that's far behind `main`** (a zombie that would silently revert newer work) — rebase it or **close** the PR and re-cut the stream from fresh `main`.

## Verify
- Every stream has its own `feat/<stream>` branch; no two agents share a working tree.
- Each PR passed `pnpm verify` before opening; none pushed to `main`.
- PRs merged one at a time with a mergeability re-check + `/deploy-iterate` between each; merged branches deleted; no zombie branches merged.

Cross-references: `/split-tasks` (writes the per-stream prompts) · `/deploy-check` (the per-agent pre-push gate) · `/deploy-iterate` (post-merge health).
