# Cosmu

Cosmu v2 is an internal autonomous quant system: a deterministic master runs a population of self-improving, LLM-authored swing strategies, farms them in realistic paper, and keeps live capital behind a global toggle that is off by default.

The safety partition is the product: the scorer and the money are deterministic and outside any LLM path. The lab agent can propose strategy structure, code, research, and ML artifacts, but the master owns scoring, allocation, risk, audit, and live promotion.

## Current Shape

- `apps/engine`: Python FastAPI engine, deterministic spine, fresh control-plane schema, strategy spec/compiler checks, risk gauntlet, model-routing policy, and audit store.
- `packages/contracts-ts`: generated TypeScript contract package from the engine OpenAPI.
- `apps/web`: rebuilt Next.js command center with the four product surfaces: Dashboard, Leaderboard, Strategy Detail, Console.
- `docs/VISION.md` and `docs/BUILD_PLAN.md`: the product contract and implementation plan.

The old `apps/api` Node runtime has been retired from the active build path.

## Local QA

Use `.env.local` for local settings and secrets. Secrets stay server-side only.

```bash
pnpm install
pnpm contracts:generate
PYTHONPATH=apps/engine python3 -m pytest apps/engine/tests
pnpm typecheck
pnpm build
```

Run the engine API:

```bash
PYTHONPATH=apps/engine python -m uvicorn cosmu.api.app:app --host 0.0.0.0 --port 8000
```

Run the web app:

```bash
API_BASE_URL=http://127.0.0.1:8000 \
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000 \
pnpm --filter @cosmu/web dev --port 3000
```

Open `http://localhost:3000`.

## Product Surfaces

1. Dashboard: pooled wallet, net P&L, costs, allocation, live gate.
2. Leaderboard: standardized per-strategy sleeves ranked by deterministic evidence.
3. Strategy Detail: spec, compiled artifact, trades, WFO/holdout results, notes.
4. Console: chat/voice/image control surface and proactive recommendations.

Market bars and feature history belong in a columnar catalog, not row-per-bar Postgres. Postgres is the control-plane and money-truth: strategies, runs, executions, sleeves, costs, recommendations, policies, and append-only events.
