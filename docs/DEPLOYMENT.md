# Deployment

Cosmu's current stack is intentionally simple:

- **Vercel** hosts the Next.js web app only.
- **Railway** hosts the Express API, scheduler, guardian, and background jobs.
- **Supabase Postgres** is the database.

## Vercel

Vercel should not run cron jobs for Cosmu. Keep it as the frontend and server-side BFF.

Required env vars:

```
API_BASE_URL=https://<railway-api-service>.up.railway.app
API_SECRET_KEY=<same secret as Railway>
```

## Railway

Railway runs the always-on backend from the repo root with `railway.toml`.

Required core env vars:

```
DATABASE_URL=<supabase connection string>
DATABASE_SSL=true
API_SECRET_KEY=<32+ chars>
SCHEDULER_ENABLED=true
GUARDIAN_ENABLED=true
```

Provider and exchange keys also belong on Railway, not in Vercel or the DB.

## Background Jobs

Railway owns recurring work:

- Bot scheduler: every 15 seconds.
- Market data cache: every minute.
- Pricing, model catalog, and venue symbol sync: hourly.

Use `GET /internal/background-jobs` with `x-api-key` to verify the loop is running.
