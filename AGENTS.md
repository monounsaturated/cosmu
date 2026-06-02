# Cosmu — Agent Entry Point

> New chat? Start here. Read this file, then build. That's the whole prompt.

## What Cosmu is
Autonomous quant money machine. Python engine (`apps/engine/`) on Railway. Next.js web (`apps/web/`) on Vercel. Supabase Postgres + pgvector. The deterministic scorer/gate decides what lives — LLMs only propose, never score or move money.

## North star
Simple to use. Powerful. Agentic-first — use skills for common tasks, don't improvise. Buy > build. The one metric: risk-adjusted profit net of every cost. Live stays OFF by default.

## Read order (one doc, not all)
1. **This file** — invariants, skills, task queue
2. **`docs/IMPLEMENTATION.md`** — what's built, what's next (read the last 3 "### Built" sections)
3. **The module's `# intent:` header** — every file opens with purpose/inputs/outputs/invariants
4. **`rg` for the exact symbol** — don't crawl the repo

## Self-route
Check state, then pick the highest-impact unblocked task:
1. Tests green? `cd apps/engine && python3 -m pytest -x -q --tb=line`
2. Web green? `pnpm --filter @cosmu/web typecheck`
3. Engine deployed? See `docs/OWNER_SETUP.md §F`
4. Pick from **Task queue** below. **Use a skill if one matches.**

## Skills (use these — don't improvise)
| Skill | Trigger phrases |
|-------|----------------|
| `/create-strategy` | "new strategy", "add a thesis", "draft a Version" |
| `/add-data-source` | "add X data", "wire Y source" |
| `/add-venue` | "add X exchange", "wire Y venue" |
| `/deploy-check` | "check deploy", "is engine up", "fix deploy" |
| `/run-gate` | "run the gate", "test the edge" |
| `/debug-strategy` | "why did X die", "post-mortem on Y" |

## Non-negotiables
- **Scorer + money** = deterministic, out of any LLM path. LLM only PROPOSES.
- **No magic numbers** in specs (thresholds in `param_space`). Point-in-time, no look-ahead.
- **Live OFF** by default. Nothing autonomous moves real money.
- **Generated types**: `@cosmu/contracts-ts` from OpenAPI — never hand-type TS models.
- **LLM-optional** + offline-testable everywhere (mock network, inject providers).
- **One gateway** = OpenRouter. Model IDs from `lab/router.py` config. Secrets server-side only.
- **Ask first**: schema changes, new vendor/spend, live-execution changes, broad renames.
- **Never**: LLM fires a live order, agent defines its own fitness, hand-maintain Python↔TS types, commit secrets, martingale/revenge sizing.

## Standards
Follow `docs/CODING_STANDARDS.md` exactly. Key patterns:
- Every module: `# intent:` header (purpose · inputs · outputs · invariants)
- Data source: `DataSourceRegistry` + numeric + point-in-time `available_at` + pinned `transform_version` + offline fixture + certifi SSL
- Test: `tests/test_<area>.py`, deterministic + offline, inject providers/mock HTTP
- Persistence: typed Postgres table + `events` ledger. Web types generated from OpenAPI.

## Task queue
Highest impact first. Completed items are deleted, not checkmarked.
1. **Deploy verification** — owner: Railway Root Dir = `apps/engine`, Vercel: `API_BASE_URL` + `NEXT_PUBLIC_API_BASE_URL`. See `docs/OWNER_SETUP.md §F`.
2. **Web polish** — make the 6 surfaces feel complete (real Recharts/Tremor charts, Settings key-status, strategy lifecycle tabs, costs merged into Paper).
3. **More data sources** — FRED expansion (VIX, fed funds), DeFiLlama TVL, CoinGecko — via `/add-data-source` skill.

## Architecture
```
apps/engine/cosmu/     Python 3.12, FastAPI, Pydantic, pytest
apps/web/              Next.js 16, Tailwind v4, shadcn, Tremor
packages/contracts-ts/ Generated from engine OpenAPI (never hand-typed)
.claude/skills/        Claude Code skill definitions
strategies/inbox/      Drop specs here — scanned on deploy
```
Hosting: **Railway** (engine API + 6h cron) · **Vercel** (web) · **Supabase** (Postgres + pgvector)

## Prior art
`TradingAgents-main` is reference only, not product code. Gitignored.
