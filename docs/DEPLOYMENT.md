# Deployment

Two services, both auto-deployed on push to the working branch.

## Engine (Railway)

Python FastAPI engine at `apps/engine`. Railway builds from the Dockerfile and starts via (see `apps/engine/railway.toml`):

```bash
python -m uvicorn cosmu.api.app:app --host 0.0.0.0 --port ${PORT:-8000}
```

Live URL: https://cosmu.up.railway.app

## Web (Vercel)

Next.js app at `apps/web`. Set both env vars to the Railway engine URL:

```bash
API_BASE_URL=https://cosmu.up.railway.app
NEXT_PUBLIC_API_BASE_URL=https://cosmu.up.railway.app
```

Push to the working branch auto-deploys both. Run `pnpm verify` first. Live trading is off by default.
