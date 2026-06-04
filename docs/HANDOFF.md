# Cosmu — Handoff & Overview (read this first in a fresh chat)

> One screen to pick up the project without re-explaining. Pair with [AGENTS.md](../AGENTS.md), [MASTER_PLAN.md](MASTER_PLAN.md), [KEYS.md](KEYS.md).

## North star
Autonomous, **honest, LEAN** crypto money-machine. LLM **proposes** strategies; a deterministic **FDR gate disposes** (out of any LLM reach). Profit net of fees. Internal tool — Claude Code is part of the product. Stack: pure-Python engine (Railway) · Next web cockpit (Vercel) · Supabase.

## State (2026-06-04 — post 7-PR merge train)
- **The autonomous machine is ON.** Merged to main this session (one integration branch, CI-gated, ONE remote verify): **#47** replicate/evolve flywheel wired into the tick · **#48** experiments registry + soft-labels (cold-start ML gradient) · **#57** adversarial gate proof (no-edge→0, known-edge→pass; *no leak found*) · **#58** SIM→live variance-attribution + `/profile-source` data-trust audit · **#59** modular Notion-vibe cockpit (tool-aligned KPIs, TradingView charts, `/command` hints) · **#60** wider perp universe (~30) + multi-timeframe bars + ML-ready point-in-time panels. (#56 LLM-formatter was dropped as a **duplicate** of the wired `ingest/llm_formatter.py` — see BACKLOG debt note.)
- **Compute strategy is now explicit** — see [COMPUTE.md](COMPUTE.md): CI/verify → GitHub Actions (the remote gate; push=deploy so the gate is **PR CI before merge**); heavy research → **Modal** scale-to-zero later. Do NOT run full `verify` locally — targeted tests + remote CI.
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
A system that **reads → scrapes → ingests → proposes (LLM, from vibes/weak signals) → verifies on the honest gate (no hallucination) → forward-tests → trades live on your click**, leaning hard on current APIs/LLMs/ML. Vibe → verified → live. The leverage: **LLM-formatted, standardized, point-in-time scores/indexes stored with history → train ML on them**.

## Next wave (cloud agents; one master orchestrator merges)
1. **Turn ON the autonomous machine** — rebase + merge **#47 (evolve flywheel)** + **#48 (experiment tracking)** onto the now-honest finder → the machine searches thousands of hypotheses, gate as the brake.
2. **UI rethink** — modular, **Notion-vibe**, data-rich, less clutter; pick-what-to-display; deep-detail on demand; kill the "$ dollars" KPIs for tool-aligned metrics; logic+buttons+hover-modals not walls of text.
3. **Data depth + pipelines** — wider perp universe (carry was INSUFFICIENT-DATA on 5 symbols), more sources, **multiple timeframes**, no duplicates, ML-ready standardized storage.
4. **Inspiration skills** (in IDEAS): `/profile-source` data-trust audit (before) · backtest integrity audit (after) · **SIM→live variance attribution** · Polymarket-only LLM research-desk · adaptive scraper.
5. **Strategy × asset × timeframe matrix** — the core ML feature (tailor each strategy per asset/timeframe).

## Decisions to carry (don't re-litigate)
- **QuantConnect: NO rewrite** (the honest hand-rolled gate is the moat). **But DO offload COMMODITY layers to external services** to maintain less + keep the codebase readable: **OpenBB** (data), **TradingView** (charts/Pine), a **broker SDK** (live exec). Lean core stays ours. *(This is "buy>build, modular, easy-to-read" applied correctly.)*
- **Compute/where things run:** BUILD on **local M2** (now fast — hermetic tests dropped verify 28→12 min) for 1–2 agents; use **cloud Claude chats** only for **3+ truly-parallel** agents (separate VMs → no M2 contention). **AUTONOMOUS RUNNING** (data fetch, the tick, ML) = **Railway crons**, NOT Claude agents. Speed cheat codes: targeted tests during work, `--no-verify` push, ONE verify at merge, big audits at the end.
- **Idea intake:** drop one-liners in `IDEAS.md` → `/triage-ideas` promotes into `BACKLOG.md` → `/fan-out` → PRs. Never break the current plan; prioritize, don't pile.
