# cosmu

Lean V1 autonomous trading loop built from `SYSTEM.md`.

## What is built

- `apps/api`: Node API with one real run loop
- `apps/web`: internal read-only dashboard
- `packages/shared`: shared decision, runtime, execution, and dashboard contracts
- `apps/api/sql`: minimum serious V1 schema plus one seed bot

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

## Setup

1. Copy `.env.example` to `.env` and fill in real values.
2. Create the database schema with `apps/api/sql/001_init.sql`.
3. Seed the first prompt, model profile, bot, and runtime config with `apps/api/sql/002_seed.sql`.
4. Apply follow-up schema changes with `apps/api/sql/003_bot_experiments.sql`.
5. Install dependencies with `pnpm install`.
6. Start the API with `pnpm --filter @cosmu/api dev`.
7. Start the dashboard with `pnpm --filter @cosmu/web dev`.

## Deploy (Railway now, Vercel later)

- Root deploys are API-first: Railway can build and start from repo root without custom commands using `pnpm build` and `pnpm start`.
- Root `build` compiles shared + API only, so Railway does not require Next.js web env vars for backend deploys.
- If you also want web on Railway, create a second service with root directory `apps/web` (its own `build`/`start` scripts already exist).
- If you later move frontend to Vercel, keep Railway on root/API (or `apps/api`) and point Vercel at `apps/web`.

## Environment

- `DATABASE_URL`: Supabase Postgres connection string
- `XAI_API_KEY`: xAI API key for the decision step
- `BINANCE_API_KEY`: Binance Spot API key
- `BINANCE_API_SECRET`: Binance Spot API secret
- `SLACK_WEBHOOK_URL`: optional Slack webhook

## Notes

- Runtime behavior lives in `bot_runtime_configs`, not in prompt text or scheduler code.
- Binance-specific request signing and payload handling stay inside `apps/api/src/adapters/binance.ts`.
- `testnet` and `live` are the only supported modes.
- `spot` is the only supported asset class in V1.