---
name: deploy-iterate
description: After a push, read Railway/Vercel logs to confirm the deploy is healthy and iterate on failures. Use to debug a deploy, check /health, or chase a runtime error in prod.
---

# deploy-iterate

Push deployed; now confirm it's actually live and healthy, and iterate if not. Tokens in gitignored `.env.local` are for **reading logs while debugging**, not for deploying (push is the only deploy trigger).

## Steps
1. **Engine health:** hit the Railway engine `GET /health` → `{ ok: "true", service: "cosmu-engine" }`. If it 503s, the app failed to boot (often a schema/import error at startup — `cosmu/api/app.py` lifespan).
2. **Engine logs (Railway):** read the deploy + runtime logs. Common boot failures: missing `DATABASE_URL`, a `schema.sql` packaging issue (must ship via `[tool.setuptools.package-data]`), or an ingest source erroring (those are `_safe()`-wrapped and should NOT crash boot).
3. **Web (Vercel):** confirm the build succeeded and the app reads `API_BASE_URL` / `NEXT_PUBLIC_API_BASE_URL` (the engine URL). CORS: the engine needs `CORS_EXTRA_ORIGINS` = the Vercel domain.
4. **Postgres migrations** are applied out-of-band (Supabase SQL editor) — `cosmu/knowledge/store.py:migrate` only ensures the singleton rows on PG. After a schema change, run the matching file in `cosmu/knowledge/migrations/`.
5. **Iterate:** fix → `pnpm verify` → push again. Don't `railway up`/`vercel deploy`.

## Verify
- `/health` is 200, the web renders real engine data (not the offline/empty state), zero console errors.
