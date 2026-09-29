---
name: triage-ideas
description: Process the product/engineering idea inbox — promote ripe ideas into BACKLOG.md with tags, re-order the backlog, and archive what's been triaged so IDEAS.md stays lean. Use to clear the idea inbox.
---

# triage-ideas

Turn the raw idea inbox into a groomed backlog. Each idea gets a disposition; ripe ones land in `BACKLOG.md` with tags; everything triaged moves to the archive so the inbox never clutters. (Engineering/product ideas only — trading strategies go through `/dump-idea` into `apps/engine/strategies/inbox/`.)

## Steps
1. **Read `IDEAS.md`** — BOTH the free-form `## 🗑️ DUMP ZONE` (raw, unformatted operator dumps) AND the structured `## Inbox`. Treat every line in the dump zone as a real idea: clean it up, classify it (feature/infra → triage here; trading idea → hand to `/strategize`; junk/duplicate → drop), then **clear the dump zone** (leave the markers + empty space).
2. **Decide a disposition per idea:** **promote** (ripe — clear value, actionable now-ish), **defer** (good but not yet — note why), or **drop** (out of scope / superseded).
3. **Promote into `BACKLOG.md`** under **Now / Next / Later** by urgency, tagged `(engine|web|config) + (cloud|local) + (opus|sonnet|haiku)`. Use `-` for a tag that doesn't apply (e.g. a pure decision item).
4. **Re-order the backlog strategically** — pull the highest-leverage / unblocking items up; let polish drift down. Keep it honest about what actually moves profit.
5. **Archive processed ideas:** move every triaged idea **out of the Inbox** into `## Archived` at the bottom of `IDEAS.md`, annotated with its disposition (e.g. `(promoted → Later)`, `(deferred — needs X)`, `(dropped — superseded by Y)`). The Inbox keeps only ideas still awaiting triage.

## Verify
- `IDEAS.md` Inbox contains **only un-triaged ideas**; every triaged idea sits under `## Archived` with a disposition.
- Every **promoted** idea appears in `BACKLOG.md` with its `(engine|web|config)+(cloud|local)+(opus|sonnet|haiku)` tags.

Cross-references: `/fan-out` (turns promoted backlog items into parallel agents) · `/split-tasks` (writes the per-item prompts).
