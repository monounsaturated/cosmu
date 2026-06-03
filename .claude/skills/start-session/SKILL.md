---
name: start-session
description: New-chat orientation — read the entry docs, check repo + engine state, and report what to work on (cloud vs local, opus vs sonnet) plus parallel-agent suggestions. Use at the start of any session.
---

# start-session

Orient a fresh session in one pass: read the invariants, read the priorities, snapshot the live state, and recommend the next move. Read-only — this changes nothing.

## Steps
1. **Read `AGENTS.md`** — architecture, invariants, env, compute rules (cloud vs local).
2. **Read `BACKLOG.md`** — current priorities (Now → Next → Later).
3. **Snapshot the repo:** `git status` + `git log --oneline -5` + `gh pr list` (open PRs).
4. **Engine health:** `curl -s $API_BASE_URL/health` (if `API_BASE_URL` is configured; skip silently if not).
5. **Report:** current branch, top 3 `Now` backlog items, any stale/missing data feeds, open PRs.
6. **Recommend:** which backlog items to tackle next, **cloud vs local** (heavy compute → cloud), **opus vs sonnet** (deep reasoning → opus, mechanical/UI → sonnet).
7. **Suggest parallelism:** "These items are independent and could run as separate sub-agents: [list]." Hand off to `/split-tasks` to write the prompts.

## Verify
- Report names the current branch, ≥3 backlog items, and open PRs.
- Each recommendation carries a cloud/local + opus/sonnet tag.
