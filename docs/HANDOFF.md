# Cosmu — Handoff & Overview (read this first in a fresh chat)

> One screen to pick up the project without re-explaining. Pair with [AGENTS.md](../AGENTS.md), [MASTER_PLAN.md](MASTER_PLAN.md), [KEYS.md](KEYS.md).

## North star
Autonomous, **honest, LEAN** crypto money-machine. LLM **proposes** strategies; a deterministic **FDR gate disposes** (out of any LLM reach). Profit net of fees. Internal tool — Claude Code is part of the product. Stack: pure-Python engine (Railway) · Next web cockpit (Vercel) · Supabase.

## State (2026-06-04)
- **Engine = lean pure-Python** (deps: ccxt/fastapi/pydantic/sqlalchemy only). Deflated-Sharpe, CSCV-PBO, BH-FDR, backtester are **hand-rolled on purpose** (auditable, low-RAM). Real Binance bars · FDR-gated funding · forward-mark clock.
- **Discovery is now TRUSTWORTHY** — `finder.py` significance leaks FIXED in pure-Python (#51): true trial-count, effective-N correlation haircut, real CSCV-PBO, purged+embargoed WFO, per-symbol min_trades, dedupe-before-FDR + a permutation-null regression test.
- **Data:** funding deep (**20 symbols × 2yr**). Most alt sources free + wired; multi-asset (stocks via Stooq, etc.) wired. Add a key → that source un-greys.
- **UI:** 4-tab cockpit — **Overview · Strategies · Scores · Mind** — honest empty states, dynamic "What to do next", per-source index scores, Settings→Keys status page. Synthetic verdicts killed. **No API auth** (internal tool).
- **0 survivors = honest "no edge found yet"** (data was thin; now deep — re-test pending).

## The plan (focused, in order)
1. **NOW:** hand-author the lucrative set — **funding-carry · cross-sectional momentum · funding-contrarian · vol-regime** → run through the now-honest gate on the deep 20×2yr data → **first real survivor (or honest fail)**.
2. **THEN:** forward-test → **$100 live crypto** (Binance/Kraken) once an edge truly passes → multi-asset.
3. **LATER:** rebase + merge held PRs (#47 evolve flywheel, #48 experiment tracking) onto the honest finder · adopt OpenBB for plug-and-play multi-asset data · bots.

## Locked decisions (do NOT re-litigate)
- **Stay LEAN pure-Python.** NO numpy/scipy/sklearn/skfolio/mlfinlab, **NO QuantConnect/LEAN rewrite** — the hand-rolled honest gate is the moat; heavy frameworks = more LLM error, OOM, lost auditability, huge migration. (QC only ever as an *optional* live-broker adapter, much later.)
- **No pooled wallet** (per-strategy tracks; "live" is a stage, not a separate wallet). No mock wallets.
- **Free-data-first**; pay only after a category proves edge; **≤$200/mo**.
- **No API auth** (internal). **No new hardware** (Fly.io / Mac mini / Pi won't help — see Speed).
- **Buy-not-build COMMODITY infra** (OpenBB data, ccxt) — never the core gate.

## Speed / compute rules (the real cheat codes)
- **Build on local M2.** Cloud Claude only to isolate truly-disjoint parallel agents (cloud terminal is *also* slow — not a magic speed-up).
- **The slowness is verify + LLM latency, not CPU.** `pnpm verify` = full `next build` + full pytest (~6–9 min). Running 2+ verify-agents on one 16GB M2 → contention → 40-min runs.
- **Cheat codes:** during work use **targeted tests** (`pytest -k …`), push with `--no-verify`, run **ONE** full verify at merge. Don't reinstall deps per worktree. Do **big audits at the END**, not 24/7. Engine-only changes skip `next build`.

## How to use it
- **Web cockpit:** Overview (making money? + what to do) · Strategies (lifecycle stages) · Scores (data indexes) · Mind (reasoning). Settings→Keys shows what's plugged.
- **Claude Code:** `/strategize` (chat a vibe → gated strategy) · `/manage-data verify` (data coverage) · `/run-gate` · `/start-session` (orient).

## Human tasks (what YOU connect) → details in [KEYS.md](KEYS.md)
- Add keys in **Railway → Variables** (server-side). The Settings→Keys page shows configured-vs-not; missing = that source greys, **app still works**.
- Required already set. Free recommended: **FRED** ✅. Optional/paid (LunarCrush…): only when a category proves edge. Live (Binance/Kraken keys): only when going live.

## The goal (autonomous machine)
A system that **reads → scrapes → ingests → proposes (LLM, from vibes/weak signals) → verifies on the honest gate (no hallucination) → forward-tests → trades live on your click**, leaning hard on current APIs/LLMs/ML. Vibe → verified → live.
