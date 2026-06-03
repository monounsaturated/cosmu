# Cosmu

Autonomous quant machine. LLMs propose strategies — a deterministic gate decides what
gets funded. Live trading is **OFF by default** behind 5 interlocks.

## What it does

- Authors trading strategies autonomously (or from your ideas)
- Screens them through a deterministic, FDR-controlled gate (deflated Sharpe · CSCV-PBO · holdout · regime folds · cohort Benjamini-Hochberg)
- Forward-tests survivors on their own standalone SIM tracks — ≥30 forward days net of fees is the recommended live-readiness proof (the operator decides when to go live; the 5 interlocks are the hard gate)
- Ingests free alt-data sources for cross-asset signals, surfaced through the Mind (analyst-panel reasoning)

## What it doesn't do

- Trade live without explicit human activation (5 interlocks: toggle on + real keys + gate passed + caps available + no kill-switch)
- Use LLMs in the funding/execution path (the deterministic gate alone disposes)
- Pool money across strategies (each survivor has its own standalone track — no shared wallet)
- Display synthetic data — empty surfaces say so honestly, never fabricate a track record

## Run locally

```bash
pnpm install
pnpm dev          # web on :3000 (regenerates contracts, then next dev)
pnpm engine:api   # engine API on :8000 (FastAPI / uvicorn)
```

Point the web app at the engine with `.env.local`:

```
API_BASE_URL=http://127.0.0.1:8000
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

With no engine configured, every surface renders its honest "not connected" state — no fake numbers.

## Verify before pushing

```bash
pnpm verify   # naming:check · contracts:generate · engine:test · typecheck · build
```

`build` runs the real `next build` — the step that catches a Vercel-breaking page before you push.
On a RAM-tight machine, run the heavy parts (`engine:test`, `next build`) in a cloud session.

## Deploy

Push to your working branch. **Railway** (engine + 4h cron) and **Vercel** (web) auto-deploy.
That's the only trigger — never also run `railway up` / `vercel deploy` (double-deploy race).

## Stack

- **Engine** — Python 3.12, FastAPI, Pydantic, pytest (`apps/engine/cosmu`)
- **Web** — Next.js, Tailwind, shadcn/ui (`apps/web`)
- **Contracts** — `@cosmu/contracts-ts`, generated from the engine OpenAPI (never hand-typed)
- **Data** — Postgres / Supabase · **LLM** — via OpenRouter (free tier by default; proposals only)

## Docs

- `AGENTS.md` — the single canonical entry point for any coding agent
- `docs/IMPLEMENTATION.md` — what's built, what's next
- `docs/GLOSSARY.md` — vocabulary (the Mind, the Gate, tracks, lifecycle)
- `.claude/skills/` — runnable playbooks (the source of truth for common procedures)
