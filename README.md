# Cosmu

Autonomous quant machine. LLMs propose strategies — a deterministic gate decides what
gets funded. Live trading is **OFF by default** behind 5 interlocks.

## What it does

- Authors trading strategies autonomously (or from your ideas)
- Screens them through a deterministic, FDR-controlled gate (deflated Sharpe · CSCV-PBO · holdout · regime folds · cohort Benjamini-Hochberg)
- Runs Paper tracks for survivors — each strategy gets its own standalone SIM track on live data; ≥30 days net of fees is the recommended live-readiness proof (the operator decides when to go live; the 5 interlocks are the hard gate)
- Ingests free alt-data sources for cross-asset signals, surfaced through the Mind (analyst-panel reasoning)

## What it doesn't do

- Trade live without explicit human activation (5 interlocks: toggle on + real keys + gate passed + caps available + no kill-switch)
- Use LLMs in the funding/execution path (the deterministic gate alone disposes)
- Pool money across strategies (each survivor has its own standalone track — no shared wallet)
- Display synthetic data — empty surfaces say so honestly, never fabricate a track record

## Run locally

```bash
pnpm install
pnpm dev          # web on :3000 (regenerates contracts, then next dev --turbopack)
pnpm engine:api   # engine API on :8000 (FastAPI / uvicorn)
```

First clone — also install the Python dev deps so `pytest -n auto` works locally:

```bash
pip install -e "apps/engine[dev]"
```

Point the web app at the engine with `.env.local`:

```
API_BASE_URL=http://127.0.0.1:8000
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

With no engine configured, every surface renders its honest "not connected" state — no fake numbers.

## Verify before pushing

```bash
pnpm verify         # full: naming:check · contracts:generate · engine:test · typecheck · next build
pnpm verify:fast    # skip next build — lint + typecheck + engine tests only (fast local loop)
pnpm verify:remote  # manually dispatch the GitHub Actions 'verify' run → tail it
```

**The pre-push hook (`.githooks/pre-push`) is the gate** — it runs naming + contracts-drift +
the engine test suite + typecheck and BLOCKS the push on any failure (push = deploy, and CI does
not auto-run). It skips a step honestly (loud warning) only when that toolchain isn't installed.
Escape hatches when you own the risk: `COSMU_PREPUSH=fast git push` (naming + drift only) or
`git push --no-verify`. The full `pnpm verify` adds the production `next build` on top — run it
before pushing anything that touches the web app.

CI (`verify.yml`) is `workflow_dispatch`-only — it does NOT auto-run on PRs or pushes (we are not
paying for GitHub Actions). `verify:remote` manually dispatches it (`gh` CLI required) so the heavy
`next build` runs on GitHub instead of your RAM.

`verify:fast` is the tight feedback loop — skips the slow Next.js production build.

## Deploy

Push to your working branch. **Railway** (engine + 7 crons: 15-min ingest · 4h autonomous tick · daily+hourly forward-test/mark clocks · hourly voices · daily rotation re-arm — see `apps/engine/railway.toml`) and **Vercel** (web) auto-deploy.
That's the only trigger — never also run `railway up` / `vercel deploy` (double-deploy race).

## Stack

- **Engine** — Python 3.12, FastAPI, Pydantic, pytest (`apps/engine/cosmu`) on **Railway**
- **Web** — Next.js, Tailwind, shadcn/ui (`apps/web`) on **Vercel**
- **Contracts** — `@cosmu/contracts-ts`, generated from the engine OpenAPI (never hand-typed)
- **Data** — Postgres / Supabase · **Heavy compute** — Modal (scale-to-zero backtests/ML/sweeps)
- **LLM** — OpenRouter (free `:free` tier by default; xAI fallback) · proposals only, gate is deterministic
- **CI** — GitHub Actions (`verify.yml`) is **`workflow_dispatch`-only** (manual, OFF by default — we are not paying for it); the **pre-push hook (naming + drift + engine tests + typecheck) is the gate**

## Docs

- `AGENTS.md` — the single canonical entry point for any coding agent
- `docs/IMPLEMENTATION.md` — what's built, what's next
- `docs/GLOSSARY.md` — vocabulary (the Mind, the Gate, tracks, lifecycle)
- `.claude/skills/` — runnable playbooks (the source of truth for common procedures)
