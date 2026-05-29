# Cosmu

Internal investment operating system for agent research, data capture, venue execution, and outcome review.

## What is built

- `apps/api`: Node API for agent runs, Signals, Research, venue execution, scheduler/guardian jobs, and audit traces
- `apps/web`: internal command center for agents, Signals, Research, Settings, and optional modules
- `packages/shared`: shared schemas, defaults, runtime, execution, and dashboard contracts
- `apps/api/sql`: schema, seeds, and migrations

## Product Flow

```text
Source -> Record -> Signal -> Index -> Research -> Strategy -> Decision -> Execution -> Outcome
```

- **Bots** run the venue-aware loop: research prompt, trader prompt, deterministic validator, execution, guardian, dashboard.
- **Signals** convert records from X, web, news, market, APIs, or manual QA into small standardized interpretations that bots can consume.
- **Research** runs natural-language experiments, data-source scouting, strategy candidates, backtests/evaluations, and anti-noise review.
- **Index** (future) is a scheduled bot that monitors Sources and applies a standardized prompt to quantify a topic over time.
- **Venues** are the single source of truth for testnet vs live, shown by actual name: `Binance` and `Binance Testnet`. No generic paper/live/testnet-mode labels.

## Current loop

1. scheduler hits `POST /internal/scheduler/tick`
2. API finds due enabled bots from runtime config
3. API loads prompt version, model profile, and runtime config
4. Binance adapter fetches balances, prices, and tradability metadata
5. xAI returns strict structured JSON decision
6. backend validates the decision with shared Zod schemas and runtime rules
7. Binance adapter executes normalized spot intents on the configured venue
8. API stores runs, decisions, executions, and portfolio snapshots
9. dashboard reads the latest state from the API
10. Slack gets non-blocking run alerts

## Local Setup

1. Copy `.env.example` to `.env.local` and fill in the values needed for the surface you want to test.
2. Install dependencies with `pnpm install`.
3. Apply SQL files in order from `apps/api/sql`.
4. Start API + web together with `pnpm dev`, or separately with `pnpm --filter @cosmu/api dev` and `pnpm --filter @cosmu/web dev`.
5. Open the web app and test the path: Dashboard -> Signals QA capture -> Research session -> candidate -> bot.

QA helper:

```bash
pnpm typecheck
pnpm build:all
```

SQL helper:

```bash
set -a && source .env.local && set +a && node scripts/apply-sql.mjs apps/api/sql/<file>.sql
```

Local/test reset helper:

```bash
set -a && source .env.local && set +a && ALLOW_DB_RESET=true pnpm db:reset:local
```

The reset helper is destructive and guarded. It refuses to run without `ALLOW_DB_RESET=true` and refuses remote-looking URLs unless explicitly overridden.

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
```

### 2. Vercel Web

Deploy `apps/web` to Vercel. The web app has no cron jobs and can run on Hobby.

Set these Vercel env vars:

```
API_BASE_URL=https://<railway-api-service>.up.railway.app
API_SECRET_KEY=<same-32+-char-secret-as-railway>
```

`API_BASE_URL` is server-only. Do not use `NEXT_PUBLIC_API_URL` for the backend secret path.

### GitHub auto-deploy

Once connected, every `git push origin main` triggers a new Railway deploy automatically. Railway builds, health-checks (`/health`), and swaps with zero downtime. Rollback from the dashboard if needed.

## Environment

- `DATABASE_URL`: Supabase Postgres connection string
- `DATABASE_SSL`: optional, set `false` for local Postgres
- `XAI_API_KEY`: optional xAI API key for research/trader model profiles using `provider = 'xai'`
- `NOUS_API_KEY`: optional Nous Portal API key for model profiles using `provider = 'nous'`
- `NOUS_BASE_URL`: optional Nous/OpenAI-compatible base URL, defaults to `https://portal.nousresearch.com/v1`
- `BINANCE_TESTNET_API_KEY`: Binance Spot testnet key for Binance Testnet venue runs
- `BINANCE_TESTNET_API_SECRET`: Binance Spot testnet secret
- `BINANCE_API_KEY`: Binance Spot live key for Binance venue runs
- `BINANCE_API_SECRET`: Binance Spot live secret
- `SLACK_WEBHOOK_URL`: optional Slack webhook
- `API_SECRET_KEY`: shared secret between the Next.js BFF routes and this API (header `x-api-key`)
- `API_BASE_URL`: Vercel-only server env pointing at the Railway API

Minimum useful local tests:

- Dashboard shell only: `DATABASE_URL`, `API_SECRET_KEY`
- Research with real LLM: add `XAI_API_KEY` or `NOUS_API_KEY`
- Binance Testnet venue run: add Binance testnet keys
- Binance venue run: add Binance live keys and keep execution limits conservative

### Railway background jobs

The API starts one in-process background loop on Railway:

- Bot scheduler: always on; checks due bots every 15 seconds.
- Market data cache: refreshes Binance prices and balances every minute so dashboard requests stay fast.
- LLM pricing sync: refreshes provider pricing assumptions hourly.
- Model catalog sync: fetches available models hourly.
- Venue symbol sync: refreshes tradable Binance symbols hourly.
- Guardian: always on; checks open positions and safety-stop state.

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
- Product UI should show actual venue names, for example Binance and Binance Testnet. Older internal mode fields may remain temporarily for compatibility.
- `spot` is the only supported asset class in V1.
- External repos are references, not runtime owners. See `docs/EXTERNAL_REPOS.md`.
