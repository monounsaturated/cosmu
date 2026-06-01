# Cosmu — Agent Map

Lean pre-prompt for coding agents. The **contract is `docs/VISION.md`** (read its `§0` + INDEX, then the one section you need — never the whole file). This file is the *map + invariants*; the code is the source of detail. Keep this under ~150 lines; prune stale memory before adding.

> **Continuing the build?** `docs/IMPLEMENTATION.md` is current state (what's real vs stubbed + next steps); `docs/PLAN.md` is the gate-first sequencing; `docs/VISION.md` is the ambitious contract. Read IMPLEMENTATION first, then the one section you need. **Doc map (read one, not all):** VISION = what/why · PLAN = build order · IMPLEMENTATION = state + next · this file = invariants + how-we-work.

## What Cosmu v2 is (one paragraph)
An autonomous, multi-venue quant **money machine** for the owner's profit (not a product to sell). A **deterministic master** runs a **population of self-improving, LLM-authored swing strategies**, walk-forward backtested with real per-venue fees, **farming in realistic paper 24/7 with live trading OFF by default** — flip one toggle and gate-passing strategies auto-promote to real capital under hard caps. It competes on **returns, not speed**, and is steered by **plain chat (text or voice)**. The one metric: **risk-adjusted profit net of every cost.**

**The rule that makes autonomy safe:** the **SCORER** (walk-forward OOS + untouched holdout) and the **MONEY** are deterministic and **out of the agent's reach**. The LLM can write/run any code or ML in a sandbox, but cannot define success or move capital.

## Start here (current state)
v2 lives in **`apps/engine/`** (Python) + **`apps/web/`** (Next.js, Overview-led: Overview · Research · Console · Settings). Spine, deterministic scorer/gates, the cross-asset gate (Phase 1.6), free data providers, and the self-sustained ingest/auto-research loop are **built** — see `docs/IMPLEMENTATION.md`. **Gate-first holds:** paid vendors, live execution, and the Phase-2 factory stay deferred until the gate PASSES on real free data.

## Build discipline & where work runs
- **Buy > build; control runtime cost.** Wire a vendor/OSS for every commodity; hand-build ONLY the differentiator (farming loop · deterministic gates · scorer · allocator · spec compiler). The product's own LLM/compute spend is **ROI-throttled** (≤ a % of trailing realized edge): cheap tier by default, frontier only when it earns; daily spend cap respected.
- **Where work runs.** Complicated, must-standardize features → author directly in **Claude Code / Cursor** as typed, reviewed specs (don't hand-roll bespoke generators). **Workflows that don't need 24/7** (research, ingest passes, gate runs, DB migrations) → bounded Claude Code sessions or **scheduled crons**, never always-on services. Only the farm/paper loop is persistent.
- **Auto-research framing:** arrange a *verifiable* metric + boundaries, then remove the human from the loop. Our gate **is** this — expensive LLM/search proposes, the cheap deterministic scorer verifies and gates the money (out of any LLM's reach). Keep instruction files (this file, `# intent:` headers, skills) **lean and agent-readable** — they are the optimizable "program", not human docs.
- **Self-sustained, not cluttered.** Modules compose (never duplicate); delete stale code/docs on sight; structured Postgres is truth, markdown is a lean agent-facing view. Don't accumulate.

## Read order (token-frugal)
1. This file. 2. `docs/VISION.md` `§0` + INDEX → the one relevant section. 3. The module's `# intent:` / `// module:` header. 4. `rg` for the exact symbol. Don't crawl the repo; don't do broad cleanup inside a narrow task.

## Non-negotiables
- **Always:** keep the scorer + money deterministic and outside any LLM path; validate every LLM output with `instructor`/Pydantic before it counts; run every order through the validator gauntlet (§9); audit every decision/fill/model-call/dollar to structured tables; keep secrets server-side only (never in prompts/sandbox).
- **Ask first:** schema/DB changes; new vendor/spend; touching live-execution behavior; product-vocabulary or broad renames; anything that could move real money.
- **Never:** let an LLM fire a live order; let the agent define its own fitness metric; hand-maintain Python↔TS types (generate from OpenAPI); commit secrets; martingale / averaging-down / revenge sizing (size = f(equity, vol, conviction), never f(past losses)).

## Decision tables (do this → not that)
| Task | Do | Not |
|------|----|-----|
| Call a model | OpenRouter, model ID from config, `instructor` for structured out | self-hosted router; raw unvalidated JSON |
| Add market access | Nautilus adapter + per-venue fee/slippage model | bespoke fills; fee-free paper |
| Persist anything | typed Postgres table + append to `events` ledger | free-form markdown as source of truth |
| Observe/trace | OpenTelemetry spans → Langfuse | bespoke logging; audit ledger stays money-truth |
| Enforce a constraint | type/lint/test/CI (the tool *is* the constraint) | restating the rule in prose/docs |
| Score a strategy | deterministic master's walk-forward OOS + holdout | any agent-tunable success metric |

## Toolchain & verify
- **Python (`apps/engine`):** `uv` (deps), `ruff` (lint/format), `pytest` (+ eval gates), Pydantic + `instructor`. FastAPI exposes OpenAPI.
- **Web (`apps/web`):** generate the TS client **from the engine's OpenAPI** (never type twice); Next.js + shadcn/ui + Tremor + TanStack Table; lean Overview-led routes (Overview · Research · Console · Settings) — see `docs/IMPLEMENTATION.md`.
- **Eval-driven (SOTA):** unit evals on agent steps · LLM-judge regression suites · prod-trace sampling. Failed online scores → eval cases; **CI eval gates block bad merges.**
- v1 verify (until retired): `pnpm --filter @cosmu/web typecheck`, `pnpm --filter @cosmu/api typecheck`.

## Conventions
- Every `services/`, `lib/`, `adapters/`, `tools/` file opens with a tiny **intent-spec** (`# intent:` purpose · inputs · outputs · invariants) — read it before the file.
- Two modularities: **code** modules for the coding agent (small packages, intent-specs) and **runtime tool** modules for the agent (each independently callable; tools are read/research/propose only — **execution is deterministic**).
- Structured-first, markdown views generated, INDEX over everything (`§6`). Token-frugal always.
- Use **actual venue names** everywhere (Binance, Binance Testnet, IBKR). No "paper/live/testnet mode" labels — paper vs live is the same code path routed differently, gated by the live toggle.

## Stop & report before
broad renames / vocab changes · schema changes unless requested · destructive commands or data resets · touching unrelated modules · changing live-execution behavior · moving secrets into DB/frontend.

---

## Prior art (reference only)
`TradingAgents-main` (and Freqtrade / Pine libs) are **prior art mined into v2 RAG** (§6) — ingest as reference, never couple live trading to them. The vendored `TradingAgents-main/` tree is gitignored; it is not product code.
