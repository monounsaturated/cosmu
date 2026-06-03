# Cosmu — Agent Entry Point

> **This is the single canonical entry doc.** It is agent-agnostic — Claude Code, OpenAI Codex, and Cursor all drive from this file. New chat? Read this, then build. That's the whole prompt.

## What Cosmu is
A self-learning autonomous quant money machine on Binance spot. The one metric: profit, net of every fee. LLMs only **propose** strategies — a deterministic gate decides what gets funded and what moves money. Live trading stays **OFF** by default.

Stack:
- **Engine** — Python 3.12 FastAPI (`apps/engine/cosmu`) on **Railway**.
- **Web** — Next.js (`apps/web`) on **Vercel**.
- **Data** — Postgres / Supabase.
- **LLM** — via **OpenRouter**, free `:free` tier by default. One gateway only; secrets server-side.

## How it actually runs (read this twice)
- **Honest loop.** The deployed autonomous tick runs on **REAL Binance bars** (`edge_market=False`). Synthetic edge-bearing fixtures are quarantined to **CI/tests ONLY** — they must NEVER be shown in the app or run in prod. *Do not display synthetic things — hard rule.*
- **Local-first compute.** Heavy discovery (grid-search, walk-forward, backtest sweeps) runs **locally on the owner's M2 Mac** and emits only winning `StrategySpec`s to Postgres. Backtests are deterministic + offline-capable, so the whole test/verify loop runs locally for $0.
- **Cloud runs only:** the always-on API for the UI, gate disposition on authored specs, a mark-to-market cron, and (eventually) live execution.
- **Forward-test clock.** Funded paper sleeves are **held and marked-to-market across bars**. A sleeve must show positive net-of-fee paper P&L over **N ≥ 30 forward days** before it is live-eligible.
- **Deterministic funding gate.** A deterministic scorer — not any LLM — is the only judge that funds paper sleeves: deflated Sharpe, CSCV-PBO, holdout, regime folds. *Hardening in progress:* route the funding cohort through the global trial ledger + Benjamini-Hochberg FDR + `must_beat_buy_and_hold` (the rigorous `research/gate.py:PREREGISTERED_BAR`), so the rigorous bar — not the lighter cohort scorer — is what authorizes capital.

## Lifecycle
**Discover (Lab)** → **Paper / forward-test (Incubate)** → **Live (capital ramp).**
Live is OFF by default behind **5 interlocks**: toggle on + real keys + gate passed + caps available + no kill-switch. All five, or nothing moves.

## Dev gate (before every push)
```
pnpm verify          # = contracts:generate && engine:test && typecheck
```
All offline, no keys required. **Run `pnpm verify` before every push.**

**Push = deploy.** Railway (engine) and Vercel (web) auto-deploy on push to the working branch. One trigger only: `git push`. Never also run `railway up` / `vercel deploy` (double-deploy race). Tokens in `.env.local` (gitignored) are for **reading logs while debugging**, not for deploying.

## Environment (canonical names)
| Var | Value |
|-----|-------|
| `API_BASE_URL` | the Railway engine URL — `https://cosmu.up.railway.app` |
| `NEXT_PUBLIC_API_BASE_URL` | same Railway engine URL (web reads the engine here) |

## Skills (any agent)
Skills are **runnable playbooks** — the canonical procedure for each common task. Use one whenever it matches; don't improvise.
- **Claude Code:** type the slash command (e.g. `/run-gate`).
- **Any other agent (Codex, Cursor, …):** open `.claude/skills/<name>/SKILL.md` and follow it.

| Skill | Path |
|-------|------|
| scan-signals | `.claude/skills/scan-signals/SKILL.md` |
| groom | `.claude/skills/groom/SKILL.md` |
| create-strategy | `.claude/skills/create-strategy/SKILL.md` |
| add-data-source | `.claude/skills/add-data-source/SKILL.md` |
| add-venue | `.claude/skills/add-venue/SKILL.md` |
| run-gate | `.claude/skills/run-gate/SKILL.md` |
| deploy-check | `.claude/skills/deploy-check/SKILL.md` |
| deploy-iterate | `.claude/skills/deploy-iterate/SKILL.md` |
| debug-strategy | `.claude/skills/debug-strategy/SKILL.md` |
| import-pine | `.claude/skills/import-pine/SKILL.md` |

## Non-negotiables
- **Gate + money** = deterministic, out of any LLM path. The LLM only PROPOSES; the FDR gate funds.
- **Never display synthetic data** in the app or run it in prod. Synthetic fixtures live in CI/tests only.
- **Never collapse the model decision and the venue execution** — keep them as distinct fields/rows. The signal (what the model decided) and the fill (how the venue executed) are separate records, always.
- **No magic numbers** in specs (thresholds in `param_space`). Point-in-time, no look-ahead.
- **Live OFF** by default; the 5 interlocks are the only path to real orders.
- **Generated types**: `@cosmu/contracts-ts` from OpenAPI — never hand-type TS models.
- **LLM-optional** + offline-testable everywhere (mock network, inject providers).
- **Ask first**: schema changes, new vendor/spend, live-execution changes, broad renames.
- **Never**: LLM fires a live order, agent defines its own fitness, hand-maintain Python↔TS types, commit secrets, martingale/revenge sizing.

## Read order (one doc, not all)
1. **This file** — invariants, env, skills.
2. **`docs/IMPLEMENTATION.md`** — what's built, what's next (last 3 "### Built" sections).
3. **The module's `# intent:` header** — every file opens with purpose · inputs · outputs · invariants.
4. **`rg` for the exact symbol** — don't crawl the repo.

## Architecture
```
apps/engine/cosmu/     Python 3.12, FastAPI, Pydantic, pytest
apps/web/              Next.js, Tailwind, shadcn
packages/contracts-ts/ Generated from engine OpenAPI (never hand-typed)
.claude/skills/        Runnable playbooks (this repo's source of truth for procedures)
strategies/inbox/      Drop specs here — scanned on deploy
```
Hosting: **Railway** (engine API + cron) · **Vercel** (web) · **Supabase** (Postgres + pgvector).
