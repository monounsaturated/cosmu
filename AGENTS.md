# Cosmu Repo Index

## Product Shape
- `apps/web`: Next.js web app. Main surfaces are Dashboard (`/`), Agents (`/bots`), AI Hedge Fund (`/trading-agents`), Settings (`/settings`), and optional modules gated by feature toggles.
- `apps/api`: Express API and persistent app data access.
- `apps/trading-agents`: Local FastAPI wrapper that exposes TradingAgents through `/trading-agents/*` endpoints.
- `packages/shared`: Shared Zod schemas, types, and app defaults used by web and API.
- `TradingAgents-main`: Local upstream TradingAgents source copy for inspection/version checks. Keep it manually updatable from upstream unless the project later chooses a formal submodule/subtree workflow.

## Frontend Map
- `apps/web/app/sidebar.tsx`: Primary navigation, desktop drawer, mobile tab bar, and optional module visibility.
- `apps/web/app/control-header.tsx`: Global command/search header.
- `apps/web/app/settings/settings-console.tsx`: Model defaults, product switches, data source settings, and secret-management guidance.
- `apps/web/app/trading-agents/page.tsx`: AI Hedge Fund frontend for running local TradingAgents analyses, viewing reports/history, and checking upstream version.
- `apps/web/app/api/trading-agents/*`: Next.js proxy routes to the local FastAPI TradingAgents wrapper plus the version metadata endpoint.
- `apps/web/app/globals.css`: Shared design system and feature-specific page styles.

## TradingAgents Integration
- The web UI calls Next routes under `/api/trading-agents/*`.
- The Next proxy routes forward to `TRADING_AGENTS_API_URL` when configured, otherwise the local wrapper default.
- The version route reads `TradingAgents-main/pyproject.toml` and compares it to `TauricResearch/TradingAgents` latest GitHub release.
- Do not add trading execution to the frontend. Treat results as research output unless explicit backend execution support and risk controls exist.

## Settings And Secrets
- Store API keys in `.env.local` for local development and server environment variables in deployment.
- Store non-secret configuration in the database: model profiles, default models, feature toggles, prompt versions, data source metadata, and runtime limits.
- Do not put provider keys, exchange keys, or TradingAgents secrets in the database until encryption, rotation, audit logs, and per-user scopes are implemented.
- Background automation runs with the API process by default. Surface runtime status in Settings instead of gating scheduler or guardian with env variables.

## Feature Toggles
- Default toggles are defined in `packages/shared/src/index.ts`.
- Web copies of defaults exist in `apps/web/app/sidebar.tsx`, `apps/web/app/control-header.tsx`, `apps/web/app/settings/settings-console.tsx`, and `apps/web/app/bot-form-modal.tsx`.
- Optional modules should stay off by default so the primary product remains lean.

## Verification
- For web changes, run `pnpm --filter @cosmu/web typecheck`.
- For cross-package schema/default changes, run `pnpm typecheck` when practical.
- For UI changes, verify desktop and mobile widths in the browser before handing off.
