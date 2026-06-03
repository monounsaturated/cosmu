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
- **Compute — cloud vs local (read before heavy work).** The owner runs a **MacBook Air M2, 16 GB RAM** — it OOMs on the full `engine:test` suite and on `next build` under memory pressure (proven). So:
  - **Local (this Mac):** editing, reading, `rg`, targeted test files, a single skill run, small backtests. Cheap, fast, $0.
  - **Cloud Claude Code session:** anything heavy — the **full `pnpm verify` / `engine:test`**, **`next build`**, **grid-search / walk-forward / backtest sweeps**, broad multi-file refactors. Don't fight OOM locally; switch to cloud.
  - **Cost lever:** heavy *LLM* work (mass authoring, research, judgment) belongs to **Claude Code on the flat Max subscription**, NOT per-token API calls — the sub is already paid. The deployed engine's autonomous loop uses cheap/free OpenRouter models. **Any coding agent: if a task will spike RAM or burn many tokens, say so and recommend a cloud session — don't silently grind locally.**
- **Cloud runs only:** the always-on API for the UI, gate disposition on authored specs, a mark-to-market cron, and (eventually) live execution.
- **Forward-test clock.** Funded SIM tracks are **held and marked-to-market across bars**. A track must show positive net-of-fee SIM P&L over **N ≥ 30 forward days** before it is live-eligible. Each survivor proves itself on its **own standalone track** — there is NO pooled wallet.
- **Deterministic funding gate.** A deterministic scorer — not any LLM — is the only judge that funds SIM tracks: deflated Sharpe, CSCV-PBO, holdout, regime folds, **and a cohort-level Benjamini-Hochberg FDR**. The FDR control is wired into the deployed `FarmLoop.run_cohort` (`GateSettings.fdr_q`, default 0.10): a candidate that clears `score()` but fails BH-FDR across its cohort is demoted (`passed_gates→0`, status `killed`, Track removed) before the orchestrator can fund it — so authoring more candidates per tick can't manufacture a winner. *Still pending:* `must_beat_buy_and_hold` + routing the cohort through the full `research/gate.py:PREREGISTERED_BAR`.

## Lifecycle
**Lab (discover)** → **Strategies (screened)** → **Forward-test (proven, per-strategy, SIM)** → **Live (you launch winners).**
NO pooled wallet — each survivor proves itself on its **own standalone track**. Live is OFF by default behind **5 interlocks**: toggle on + real keys + gate passed + caps available + no kill-switch. All five, or nothing moves.

## Running strategies (cheapest → priciest)
Add strategies via the **inbox** (`strategies/inbox/*.json|*.md|*.pine`, scanned on deploy) or the Lab's autonomous author. To author a batch safely, copy `scripts/seed_inbox_strategies.py` — it **validates every spec against the real compiler** (static_check + `compile_spec`) before writing, so nothing magic-number'd or inert lands. Then to screen/backtest:
1. **Local, $0 (default):** `PYTHONPATH=apps/engine python3 -m cosmu.lab.finder --seed-real` — deterministic, offline-capable (cached Binance bars). Fine for a few specs.
2. **Cloud Claude Code session:** a *full* cohort / walk-forward sweep that would OOM the 16 GB Air. Same command, real compute, **$0 API** (flat Max sub). This is the smart default for anything heavy.
3. **Railway (deployed):** the 4h cron runs the cohort + gate on real bars **automatically** — you don't trigger it. Railway is the small always-on box, NOT for heavy sweeps.

Cheapest path = author+validate locally → screen locally or in a cloud session → push only the spec files. The gate decides what earns a Track; **ranking ≠ funding**.

## Trading traps the design blocks (don't re-introduce them)
- **Overfitting** → CSCV-PBO + deflated Sharpe + untouched holdout. **Multiple-testing** ("try 1000 ideas, one looks amazing") → cohort Benjamini-Hochberg **FDR**.
- **Look-ahead / survivorship** → point-in-time feature joins; no magic numbers (params fit from data); the **graveyard is kept** (dead strategies stay visible, no survivor bias).
- **Costs hand-waved** → every screen is **net of per-venue fees + slippage**; ranking is net-of-cost profit, never gross Sharpe.
- **Crowded-leverage blowups** → funding/vol gates. **Ruin** → live OFF + 5 interlocks + per-strategy caps, no pooled wallet, **no martingale/revenge sizing**.
- **Curve-fit to one regime** → walk-forward OOS + regime folds; a track must also survive **N ≥ 30 forward days** of real-time SIM before it's live-eligible.

## Dev gate (before every push)
```
pnpm verify          # = naming:check && contracts:generate && engine:test && typecheck && build
```
Mostly offline, no keys required. **Run `pnpm verify` before every push.** It now ends with `build` (the real
`next build`) — that's the step that catches a Vercel-breaking page before you push, e.g. a prerender crash on
a null field. If RAM is tight (see **Compute** below), `next build` and the full `engine:test` are the heavy
parts — run them in a cloud session rather than fighting OOM locally.

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
