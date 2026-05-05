# Cosmu

Lean autonomous trading and research platform built from `SYSTEM.md`.

## What is built

- `apps/api`: Node API for Light trading, Research experiments, agent observability, and Pro approvals
- `apps/web`: internal command center with `Light | Research | Pro` modes
- `packages/shared`: shared decision, runtime, execution, and dashboard contracts
- `apps/api/sql`: schema, seeds, agentic foundation, and workspace-mode migrations

## Product Modes

- **Cosmu Light** keeps the current Binance spot loop: research prompt, trader prompt, deterministic validator, execution, guardian, dashboard.
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
5. Open the web app and test the path: Light dashboard → Research hypothesis → paper candidate → paper bot → Pro approval.

SQL helper:

```bash
set -a && source .env.local && set +a && node scripts/apply-sql.mjs apps/api/sql/017_agentic_foundation.sql
set -a && source .env.local && set +a && node scripts/apply-sql.mjs apps/api/sql/018_workspace_mode.sql
```

Set `DATABASE_SSL=false` in `.env.local` for local non-SSL Postgres. Leave it empty/true for Supabase pooler.

## Deploy (Railway now, Vercel later)

- Root deploys are API-first: Railway can build and start from repo root without custom commands using `pnpm build` and `pnpm start`.
- Root `build` compiles shared + API only, so Railway does not require Next.js web env vars for backend deploys.
- If you also want web on Railway, create a second service with root directory `apps/web` (its own `build`/`start` scripts already exist).
- If you later move frontend to Vercel, keep Railway on root/API (or `apps/api`) and point Vercel at `apps/web`.

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

Minimum useful local tests:

- Dashboard shell only: `DATABASE_URL`, `API_SECRET_KEY`
- Research with real LLM: add `XAI_API_KEY` or `NOUS_API_KEY`
- Testnet bot run: add Binance testnet keys
- Live Light run: add Binance live keys and keep execution limits conservative

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