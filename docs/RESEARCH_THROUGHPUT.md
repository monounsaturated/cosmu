# COSMU — Autonomous Research Throughput Engine

> Companion to `docs/HANDOFF_NEXT.md`. The clean, best-practice workflow for **autonomous data
> ingestion + strategy iteration at scale**: kick off by a Claude Code command, then run unattended
> — Railway schedules, Modal computes, Supabase stores, the web/operator reads. Dispatch the build
> prompts only AFTER Wave 0 (integrity) + Wave 1 (router split) — see §5 on why fix-1 is a HARD
> prerequisite here.

## 1. The goal
Run propose → backtest → gate → verdict at scale, unattended: many drafts across the
**strategy × asset × timeframe × view** matrix, computed on Modal, stored point-in-time in the DB,
with **honest global deflation so volume cannot manufacture winners**. Observable end-to-end:
how many drafts are created · scheduled · screened · gated · survived — per matrix cell, per tick.

## 2. Architecture — separate the lanes (the core best practice)
```
        ┌── RAILWAY (orchestrator: light, cron, never heavy compute) ──┐
 cron ─►│  pick under-explored matrix cells · LLM authors N drafts     │
        │  (OpenRouter API) · register trials · enqueue compute jobs    │
        └───────────────────────────┬──────────────────────────────────┘
                                     │  dispatch  (modal run / Modal Function.map)
                                     ▼
        ┌── MODAL (heavy compute, parallel, ephemeral) ────────────────┐
        │  backtest each draft · cheap screen · Gate sweep ·            │
        │  survival ML · cross-asset correlation · stacked composites   │
        └───────────────────────────┬──────────────────────────────────┘
                                     │  write results + trials (PIT, idempotent)
                                     ▼
        ┌── SUPABASE (DB = single source of truth) ────────────────────┐
        │  alt_data (PIT) · runs · backtests · trials ledger ·          │
        │  tracks · verdicts · coverage                                 │
        └───────────────────────────┬──────────────────────────────────┘
                                     │  read-only
                                     ▼
                  WEB (Vercel)  +  CLAUDE CODE (operator-driven)
```
**Laws:**
- **Railway never runs heavy compute.** It orchestrates (decide, author, enqueue, read). The 2.5h
  single-machine lesson generalizes: a small always-on container is for coordination, not number-crunching.
- **Modal owns compute.** Parallel, ephemeral, pay-per-second. Triggered by Railway (autonomous) or by
  Claude Code (`pnpm modal:*`, operator-driven). Secret `cosmu-engine` already synced.
- **DB is the single source of truth.** Everything PIT + idempotent. Web and operator only read.
- **The LLM is always a cloud API** — it proposes, it never computes ML and never touches money.

## 3. The LLM / ML compute decision (answering "API or Claude Code + Modal?")
| Job | Where | Why |
|---|---|---|
| **Autonomous draft generation** (unattended ticks) | **OpenRouter API in-engine** (free-first, cheap) | Claude Code is *interactive* (you driving) — it can't run in an unattended cron. The engine's LLM seam already uses OpenRouter. |
| **Operator-driven heavy features / new strategy families** | **Claude Code** (you) | Big lifts, refactors, new capabilities — your hands on the wheel. |
| **ML (survival ranker, meta-label, correlation)** | **Modal** (deterministic, parallel) | Compute, not generation. LLM proposes the spec/features; the deterministic pipeline computes. No LLM in the ML or money path. |
So: **autonomous loop = OpenRouter + Modal; you = Claude Code + Modal.** You do NOT need a separate ML
API — the deterministic ML runs on Modal; the LLM that *proposes* runs on OpenRouter (and Claude Code
when you drive). Buy a paid OpenRouter model only for steps that are genuinely hard (ROI-gated).

## 4. Data ingestion — best practice (generalize fix-4 to ALL sources)
One managed path (`cosmu.ingest.manage` / `scripts/manage_data.py`): **fetch · backfill · verify · update.**
- **Idempotent:** dedup on `(provider, symbol, metric, ts)` — unique index + `ON CONFLICT DO NOTHING`.
  A re-run writes 0 rows.
- **Incremental:** fetch only since `max(stored ts)` — **never re-pay an API for data we already have**
  (protects the LunarCrush $5/day quota; this is fix-4 generalized).
- **PIT:** `available_at` stamped (no look-ahead); `transform_version` pinned (byte-reproducible survivors).
- **Tagged / scale-ready:** partition-friendly key `(provider, symbol, metric, ts)`; `verify` emits a
  coverage report (what we have, how deep, gaps, staleness).
- **Schedule:** Railway cron = frequent **light incremental** update across all sources; Modal = heavy
  **paginated backfills** on demand. New source = a NEW file in `data/providers/` (after refactor R4) +
  one line in `feature_registry.py` — never a shared-file edit.

## 5. Strategy iteration engine (the throughput) — and the honesty that makes it valid
**The matrix:** strategy-family × asset (the perp/spot universe) × timeframe (1d/4h/1h) × view
(price/TA · funding · social · pinescript-imported · cross-asset correlation · stacked composites).
Each cell = a hypothesis that MUST carry a pre-registered disconfirmer.

**Per-tick loop:** pick the least-explored cells → LLM authors N typed `StrategySpec` drafts (no magic
numbers) → register EACH as a trial → cheap screen on Modal (parallel) → Gate the screened survivors
with **global deflated-Sharpe + BH-FDR over the whole trial history** → open forward-test tracks for
gate-passers → write verdicts.

> 🔴 **NON-NEGOTIABLE:** Generating MANY drafts is the #1 way to manufacture a fake winner (data
> snooping). The global trial ledger + deflated Sharpe + cohort BH-FDR (**fix-1**) MUST be live before
> you scale volume — otherwise this engine becomes a *false-positive factory*. Every draft is a
> registered trial; the more you try, the higher the bar a survivor must clear. **This is exactly why
> fix-1 (Wave 0) is the hard prerequisite for this workflow.** Volume without global deflation is worse
> than no volume.

## 6. Observability — "how many drafts created / scheduled / tried / survived"
The trials ledger already records every attempt. Add a **throughput read**: per tick and per matrix
cell — drafts *authored → screened → gated → survived*, plus gate efficiency (pass-rate trend) and
the verdict ledger. This turns "is the machine searching, and is it honest about it?" into one glance.

## 7. Build prompts (modular · collision-safe · dispatch AFTER Wave 0 + Wave 1)
> All depend on fix-1 (global deflation) being merged. T1 enables scale; T3 is the engine; do T1→T3
> in order (shared loop/scheduler), T2/T4 parallel.

**T1 — Modal research lane** · opus · `feat/modal-research-lane` (after fix-1, after R1 router split)
> The autonomous cohort backtest must run on MODAL, not in the Railway container. In
> `apps/engine/remote/app.py` add a Modal Function that backtests+screens a batch of StrategySpecs
> (`.map` over drafts, parallel). In `cosmu/evolution/loop.py` / the scheduler, when `MODAL_TOKEN_ID`
> is set, DISPATCH the cohort to Modal and collect results; fall back to local sequential if unset.
> Results (runs/backtests/trials) write to the DB exactly as today — same scorer, same global trial
> ledger (fix-1), same gate. Pure orchestration change: NO change to gate/scorer logic. Tests: a batch
> dispatched + collected matches local results for a fixed seed. pnpm verify + /deploy-check. PR, don't merge.

**T2 — generalize incremental + idempotent ingest to ALL sources** · sonnet · `feat/ingest-incremental-all` (after fix-4)
> fix-4 makes LunarCrush dedup-safe + incremental. Generalize that pattern across every alt source
> (funding binance/okx/kraken, OI, liquidations, netflow, FRED macro, fear/greed, defillama, polymarket,
> reddit/social): all go through `append_dedup`; all fetch `since max(stored ts)`; the unique index +
> ON CONFLICT covers the whole `alt_data` table. `verify --json` reports coverage per source. NEVER
> re-pay an API for data we hold. Tests: re-run writes 0 for each source; since forwarded. PR, don't merge.

**T3 — matrix sweep orchestrator** · opus · `feat/matrix-sweep` (after T1)
> Extend the scheduler/FarmLoop to walk the strategy×asset×timeframe×view matrix: track per-cell
> exploration counts in the trials ledger; each tick pick the least-explored / most-promising cells;
> have the LLM author N drafts per cell (OpenRouter, typed specs, mandatory disconfirmer); register each
> as a trial; screen+gate via the Modal lane (T1) with GLOBAL deflation (fix-1). Cap drafts/tick to a
> budget. Pre-register disconfirmers. NO new gate logic — reuse the honest gate. Tests: matrix coverage
> advances; trial ledger grows by drafts authored. PR, don't merge.

**T4 — throughput observability** · sonnet · `feat/throughput-view` (after R1 routers; parallel to T2/T3)
> Add `GET /throughput` (a router) reading the trials ledger: per tick + per matrix cell — drafts
> authored/screened/gated/survived, gate pass-rate trend. Add a lean web panel on Overview (or Strategies)
> showing the funnel + gate efficiency. Read-only; coerce arrays to []; honest empty states. pnpm verify. PR.

## 8. The honest frame for scaling
This engine's value is **honest throughput**: test many disconfirmable ideas cheaply, and let a gate
that deflates against the FULL history kill ~all of them. The 1% that survives a globally-FDR-corrected
gate is the only thing ever worth funding — and you'd find it faster than testing by hand. Scale the
*volume* only once the *gate is trustworthy* (fix-1). Until then, more drafts = more false positives.
