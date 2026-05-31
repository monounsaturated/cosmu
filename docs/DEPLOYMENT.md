# Deployment

Cosmu v2 deploys as three explicit pieces:

- **FastAPI engine/API** on an always-on worker/service such as Render.
- **Next.js web app** on Vercel.
- **Supabase Postgres + pgvector** for the fresh v2 control-plane schema and RAG.

The retired v1 Railway/Express deployment is no longer the active target.

## Engine

Run from `apps/engine` with Python 3.12+.

Required production env vars:

```bash
DATABASE_URL=<supabase postgres connection string>
API_SECRET_KEY=<server-side API secret>
```

Optional vendor/env vars are enabled only when that module is active:

```bash
OPENROUTER_API_KEY=<model router key>
BINANCE_API_KEY=<trade-only key, withdrawals disabled>
BINANCE_API_SECRET=<trade-only secret>
```

Start command:

```bash
PYTHONPATH=apps/engine python3 -m cosmu.api.app
```

Migrations are represented by the v2 schema in `apps/engine/cosmu/knowledge/schema.sql`; the production path should run the equivalent Alembic migration before the worker starts.

## Web

Vercel runs `apps/web`.

Required env vars:

```bash
ENGINE_API_URL=https://<engine-service>
NEXT_PUBLIC_ENGINE_API_URL=https://<engine-service>
```

`ENGINE_API_URL` is used by server components. `NEXT_PUBLIC_ENGINE_API_URL` is used only for the local Console interaction path and must never carry secrets.

## Verification

```bash
pnpm contracts:generate
PYTHONPATH=apps/engine python3 -m pytest apps/engine/tests
pnpm typecheck
pnpm build
```

Live trading remains off by default. Any mutating route that can affect money must stay authenticated server-side and gated by explicit confirmation.
