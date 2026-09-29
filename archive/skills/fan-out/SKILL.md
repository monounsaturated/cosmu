---
name: fan-out
description: Orchestrator playbook — turn one big feature request into parallel sub-agents that don't collide (one branch each), then run a merge train into main. Use when a feature is large enough to split across multiple agents.
---

# fan-out

The **orchestrator** playbook. The lead chat decomposes a big request into independent work-streams, launches one agent per stream, then merges their PRs into `main` one at a time. Hard-won rule: agents collide unless each owns its own branch and (when heavy) its own worktree.

**This is the speed unlock — reach for it generously, not only for "big" features.** Independent work should run *concurrently*, not in sequence; if a task splits cleanly along file/dir boundaries, fan it out. Tokens are flat-rate (Max sub) — **burn them freely**; the only real cost is local RAM (heavy compute → cloud/Modal) and the merge-train serialization point. Pair fan-out with adversarial verification: a second agent that tries to *refute* the first's output beats trusting one pass.

## Steps
1. **Decompose into independent work-streams.** Cut the request along **file boundaries** — each stream touches a different set of files/dirs with minimal overlap. Overlapping streams are not parallel; sequence them or merge them into one stream.
2. **One branch per agent — `feat/<stream>`.** This is the hard rule: **NEVER run two agents in the same working directory/branch** (proven to cause branch-stomping — one agent's commits clobber the other's). Heavy or many-file streams get their **own git worktree** so their builds and edits never touch a sibling's tree.
3. **Write a focused prompt per stream.** Delegate to `/split-tasks`, which writes `.claude/tasks/*.md` — goal, exact in-scope files, acceptance check, branch name. Tag each: **cloud/local** + **opus/sonnet/haiku** + **est time** (heavy compute → cloud; deep reasoning → opus; mechanical/UI → sonnet).
4. **Each agent runs the same contract:** branch off the **latest `main`** → implement only its scoped files → `pnpm verify` (must be green) → push → open a PR. **Never push to `main` directly.**
5. **Merge train (orchestrator-only).** Merge PRs into `main` **one at a time**. After each merge, **re-check the next PR's mergeability** (`gh pr view <n> --json mergeable`), resolve any conflicts the merge introduced, and only then merge the next. Don't batch-merge — a clean PR can go stale the instant the one before it lands.
6. **Confirm the deploy after each merge.** Run `/deploy-iterate` to verify the deploy is healthy (push = deploy) before merging the next PR. A red deploy halts the train until it's green.
7. **Clean up.** `gh pr merge --delete-branch` on every merged PR. **Never merge a branch that's far behind `main`** (a zombie that would silently revert newer work) — rebase it or **close** the PR and re-cut the stream from fresh `main`.

## Dispatch modes (how the streams actually run)
Pick per situation; both end in the orchestrator merge-train.
- **Mode A — orchestrator drives (default, least owner effort).** The lead chat spawns each stream as a **background agent in its own worktree** (`isolation: worktree`, `run_in_background: true`), then merges all PRs itself. Best for "go fast, I'll handle it." Proven: many PRs/session, zero stomping.
- **Mode B — owner launches separate cloud chats.** The lead chat hands the owner one copy-paste prompt per stream; the owner opens **one fresh cloud Claude Code chat per prompt** (separate chats = separate checkouts → **no worktree needed**). Each chat PRs; the owner relays PR numbers back; the lead chat merge-trains. Best for owner visibility.

**Dependency rounds (the speed unlock).** Streams that share core files are NOT parallel — they form a chain. Maximize parallelism by running **independent tracks concurrently** and **chaining only what truly depends**: e.g. `Round 1 = foundation (solo) + unrelated tracks (UI, MCP) in parallel → Round 2 = the burst that needed the foundation → Round 3 = the run`. Never put two streams that edit the same core file in the same round. Run `/groom` **alone between rounds**, never concurrently (it touches everything).

**Per-stream prompt template (Mode B, copy-paste):**
```
Read AGENTS.md + docs/MASTER_PLAN.md [+ the relevant plan/skill]. <one-paragraph goal + exact in-scope files>. Constraints: <non-negotiables that apply>. Branch feat/<stream> off origin/main. `pnpm install && pnpm verify` MUST pass. Push, open PR "<title>", DO NOT merge. Report the PR URL + <what to report>.
```
Tag every stream: **cloud/local · opus/sonnet/haiku · worktree?**.

## Verify
- Every stream has its own `feat/<stream>` branch; no two agents share a working tree.
- Each PR passed `pnpm verify` before opening; none pushed to `main`.
- PRs merged one at a time with a mergeability re-check + `/deploy-iterate` between each; merged branches deleted; no zombie branches merged.

Cross-references: `/split-tasks` (writes the per-stream prompts) · `/deploy-check` (the per-agent pre-push gate) · `/deploy-iterate` (post-merge health).
