# Cosmu

Lean autonomous trading and research platform built from `SYSTEM.md`.

## What is built

- `apps/api`: Node API for Light trading, Signal Sentinel, Research experiments, agent observability, and Pro approvals
- `apps/web`: internal command center with `Light | Signals | Research | Pro` modes
- `packages/shared`: shared decision, runtime, execution, and dashboard contracts
- `apps/api/sql`: schema, seeds, agentic foundation, and workspace-mode migrations

## Product Modes

- **Cosmu Light** keeps the current Binance spot loop: research prompt, trader prompt, deterministic validator, execution, guardian, dashboard.
- **Cosmu Signals** converts hot observations from X, web, news, market, or manual QA into small standardized signals that agents can consume.
- **Cosmu Research** is the paper-only lab: natural-language experiments, data-source scouting, candidate creation, testnet paper bots, and anti-noise review.
- **Cosmu Pro** is the approval-gated live workspace: Research candidates can be promoted into disabled-live Pro bots, then manually enabled when risk policy allows it.

## Current loop

1. scheduler hits `POST /internal/scheduler/tick`
2. API finds due enabled bots from runtime config
3. API loads prompt version, model profile, and runtime config
4. Binance adapter fetches balances, prices, and tradability metadata
5. xAI returns strict structured JSON decision
6. backend validates the decision with shared Zod schemas and runtime rules
7. Binance adapter executes normalized spot intents on testnet or live
8. API stores runs, decisions, executions, and portfolio snapshots
9. dashboard reads the latest state from the API
10. Slack gets non-blocking run alerts

## Local Setup

1. Copy `.env.example` to `.env.local` and fill in the values needed for the surface you want to test.
2. Install dependencies with `pnpm install`.
3. Apply SQL files in order from `apps/api/sql`. For the current three-mode branch, make sure `017_agentic_foundation.sql` and `018_workspace_mode.sql` have been applied.
4. Start API + web together with `pnpm dev`, or separately with `pnpm --filter @cosmu/api dev` and `pnpm --filter @cosmu/web dev`.
5. Open the web app and test the path: Light dashboard → Signals QA capture → Research session → paper candidate → Pro approval.

QA helper:

```bash
pnpm typecheck
pnpm build:all
```

SQL helper:

```bash
set -a && source .env.local && set +a && node scripts/apply-sql.mjs apps/api/sql/017_agentic_foundation.sql
set -a && source .env.local && set +a && node scripts/apply-sql.mjs apps/api/sql/018_workspace_mode.sql
```

Set `DATABASE_SSL=false` in `.env.local` for local non-SSL Postgres. Leave it empty/true for Supabase pooler.

## Deployment

Current production stack:

- **Vercel** runs `apps/web` only.
- **Railway** runs `apps/api`, the bot scheduler, guardian, and background sync jobs.
- **Supabase Postgres** stores app state.

Do not add Vercel cron for bot scheduling. Railway is the always-on runtime owner.
The repo includes `.nvmrc` and a Node 22+ `engines` range; keep Railway and Vercel on that runtime family.

### 1. Railway API

```
railway login
railway init          # or link to existing project
railway up            # first deploy — uses railway.toml
```

Then in Railway dashboard → Settings → Source:
- Connect your GitHub repo
- Branch: `main`
- Root directory: `/` (monorepo root)
- Auto-deploy: ON

Add these env vars in Railway dashboard (Variables tab):

```
DATABASE_URL=<supabase-connection-string>
DATABASE_SSL=true
API_SECRET_KEY=<32+-char-secret>
XAI_API_KEY=<your-key>
BINANCE_TESTNET_API_KEY=<your-key>
BINANCE_TESTNET_API_SECRET=<your-secret>
BINANCE_API_KEY=<your-key>           # for live trading
BINANCE_API_SECRET=<your-secret>
SLACK_WEBHOOK_URL=<your-webhook>
SCHEDULER_ENABLED=true
GUARDIAN_ENABLED=true
```

### 2. Vercel Web

Deploy `apps/web` to Vercel. The web app has no cron jobs and can run on Hobby.

Set these Vercel env vars:

```
API_BASE_URL=https://<railway-api-service>.up.railway.app
API_SECRET_KEY=<same-32+-char-secret-as-railway>
```

`API_BASE_URL` is server-only. Do not use `NEXT_PUBLIC_API_URL` for the backend secret path.

### 3. TradingAgents (optional Python AI hedge fund)

If using the Python TradingAgents wrapper:
- Create a third Railway service
- Root directory: `apps/trading-agents`
- Uses its own `Dockerfile` (Python 3.12, FastAPI on port 8100)
- Add `TRADING_AGENTS_URL` to the API service pointing to this service

### GitHub auto-deploy

Once connected, every `git push origin main` triggers a new Railway deploy automatically. Railway builds, health-checks (`/health`), and swaps with zero downtime. Rollback from the dashboard if needed.

## Environment

- `DATABASE_URL`: Supabase Postgres connection string
- `DATABASE_SSL`: optional, set `false` for local Postgres
- `XAI_API_KEY`: optional xAI API key for Light/Research model profiles using `provider = 'xai'`
- `NOUS_API_KEY`: optional Nous Portal API key for model profiles using `provider = 'nous'`
- `NOUS_BASE_URL`: optional Nous/OpenAI-compatible base URL, defaults to `https://portal.nousresearch.com/v1`
- `BINANCE_TESTNET_API_KEY`: Binance Spot testnet key for Research paper bots and testnet Light runs
- `BINANCE_TESTNET_API_SECRET`: Binance Spot testnet secret
- `BINANCE_API_KEY`: Binance Spot live key for live Light/Pro
- `BINANCE_API_SECRET`: Binance Spot live secret
- `SLACK_WEBHOOK_URL`: optional Slack webhook
- `API_SECRET_KEY`: shared secret between the Next.js BFF routes and this API (header `x-api-key`)
- `API_BASE_URL`: Vercel-only server env pointing at the Railway API
- `SCHEDULER_ENABLED`: Railway-only; set `true` to run due bots automatically
- `GUARDIAN_ENABLED`: Railway-only; set `true` to run position safety checks

Minimum useful local tests:

- Dashboard shell only: `DATABASE_URL`, `API_SECRET_KEY`
- Research with real LLM: add `XAI_API_KEY` or `NOUS_API_KEY`
- Testnet bot run: add Binance testnet keys
- Live Light run: add Binance live keys and keep execution limits conservative

### Railway background jobs

The API starts one in-process background loop on Railway:

- Bot scheduler: checks due bots every 15 seconds when `SCHEDULER_ENABLED=true`.
- Market data cache: refreshes Binance prices and balances every minute so dashboard requests stay fast.
- LLM pricing sync: refreshes provider pricing assumptions hourly.
- Model catalog sync: fetches available models hourly.
- Venue symbol sync: refreshes tradable Binance symbols hourly.

Use `GET /internal/background-jobs` with `x-api-key` to inspect status.

### CORS (API ↔ dashboard on Vercel)

You do **not** need to update `WEB_BASE_URL` for every Vercel preview deployment. By default, the API allows browser `Origin` values on `https://*.vercel.app`, plus `http://localhost` / `127.0.0.1` for local dev.

- `WEB_BASE_URL` (optional): single extra origin (e.g. your stable production URL).
- `CORS_EXTRA_ORIGINS` (optional): comma-separated list of full origins, e.g. `https://app.example.com,https://other.com`.
- `CORS_ALLOW_VERCEL_PREVIEWS`: set to `false` only if you want to turn off automatic `*.vercel.app` allowance.
- `CORS_ALLOW_ANY_ORIGIN=true`: restores permissive CORS (equivalent to the old “no `WEB_BASE_URL`” behavior); avoid on public deployments.

### Postman vs Vercel “authentication”

If Postman gets an auth / HTML challenge from `*.vercel.app`, that is usually **Vercel Deployment Protection** (or similar), not CORS. The browser session on the real dashboard can pass; Postman does not. Either test from the deployed UI, temporarily disable deployment protection for previews, or use a Vercel bypass token as Vercel documents for that feature.

## Notes

- Runtime behavior lives in `bot_runtime_configs`, not in prompt text or scheduler code.
- Binance-specific request signing and payload handling stay inside `apps/api/src/adapters/binance.ts`.
- `testnet` and `live` are the only exchange execution modes. Research paper bots use testnet and stay in the Research workspace.
- `spot` is the only supported asset class in V1.
- External repos are references, not runtime owners. See `docs/EXTERNAL_REPOS.md`.
