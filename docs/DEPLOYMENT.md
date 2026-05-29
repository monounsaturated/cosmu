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
The repo includes `.nvmrc` and an `engines` range so Railway, Vercel, and local builds stay on the same Node 22+ runtime family.

Required core env vars:

```
DATABASE_URL=<supabase connection string>
DATABASE_SSL=true
API_SECRET_KEY=<32+ chars>
```

Provider and exchange keys also belong on Railway, not in Vercel or the DB.

Required Binance testnet env vars for paper/testnet venues:

```
BINANCE_TESTNET_API_KEY=<binance spot testnet key>
BINANCE_TESTNET_API_SECRET=<binance spot testnet secret>
```

Do not rely on `BINANCE_API_KEY` / `BINANCE_API_SECRET` for testnet. The backend intentionally keeps live and testnet credentials separate so expired live keys cannot break testnet.

If Binance keys use an IP allowlist, allow the Railway backend's outbound IP. Vercel does not own venue connectivity; the web app only proxies venue checks to Railway.

## Background Jobs

Railway owns recurring work:

- Bot scheduler: every 15 seconds.
- Market data cache: every minute.
- Guardian: position safety checks every 10 seconds.
- Pricing, model catalog, and venue symbol sync: hourly.

Use `GET /internal/background-jobs` with `x-api-key` to verify the loop is running.
