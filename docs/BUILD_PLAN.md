# Cosmu v2 — V1 Build Plan (definitive)

> **`docs/VISION.md` is the contract (the *what* & *why*). This is the *how* — the deep, agent-followable build of V1.** If they disagree, fix one on purpose. This is a reference doc: read `§0` (index), jump to the one section you need. Don't load it whole.

**V1 in one line:** a fully autonomous, self-improving paper money-machine across **crypto + equities + prediction markets**, realistic fills/fees, deterministic gates, chat+voice control — **live OFF by default**, one global toggle from real money — built **buy-heavy** behind a thin hour-zero spine, then eight parallel workstreams.

---

## 0. Index

| # | Section | Read when… |
|---|---------|-----------|
| 1 | Principles that shape the build | you need the non-negotiable build rules |
| 2 | **Buy-vs-build matrix** | deciding whether to write or wire something |
| 3 | Repo, toolchain, layout, conventions | writing any code |
| 4 | The spine (hour-zero) | bootstrapping the project |
| 5 | Execution modes & engine | anything touching Nautilus / paper / live |
| 6 | Data & ingestion | market data, features, qual sources, RAG |
| 7 | Strategy spec & compiler | the quantamental representation (differentiator) |
| 8 | Evolution loop & scorer | seed→screen→validate→score→gate→allocate |
| 9 | Lab agent & model router | authoring, ML, sandbox, self-improvement |
| 10 | Deterministic master | scheduler, allocator, risk, live gate, policy, audit |
| 11 | Venues | per-venue adapters & paper fills |
| 12 | ML | agent-written + survival model + regime classifier |
| 13 | Risk & security model | money safety + secret/sandbox isolation |
| 14 | API surface | FastAPI → OpenAPI → TS client |
| 15 | Frontend | the 4 surfaces |
| 16 | Observability & evals | tracing, eval layers, CI gates |
| 17 | Costs & ROI accounting | spend capture, attribution, throttle |
| 18 | Deployment topology | where each piece runs |
| 19 | Sequencing & milestones | what's hour-zero vs parallel, per-track DoD |
| 20 | Risk register | technical risks + mitigations |
| 21 | "It wins" + the flywheel | the honest acceptance bar |
| 22 | Hour-zero task list | the first concrete commits |
| **A** | **Appendix — Data model (DDL-level)** | writing migrations / queries |
| **B** | **Appendix — StrategySpec & compiler contract** | the quantamental representation in code |
| **C** | **Appendix — Scorer, gates & walk-forward (concrete defaults)** | implementing the fitness authority |
| **D** | **Appendix — Feature registry v0 (named features)** | building the feature store / the LLM's vocabulary |
| **E** | **Appendix — API contracts** | wiring FastAPI ↔ the generated TS client |
| **F** | **Appendix — Evolution operators (mutation catalog)** | the seeder/mutator |
| **G** | **Appendix — Config schema & spend governor** | settings, caps, the ROI throttle |
| **H** | **Appendix — Acceptance matrix** | proving each track is done |

> Sections 1–22 are the *navigable overview*; the appendices are the *precision layer* — concrete shapes a coding agent implements against. Jump to an appendix only when building that piece.

---

## 1. Principles that shape the build

1. **Buy commodities, build the differentiator.** Default to wiring a managed/OSS piece. The *only* things we hand-build are the **farming loop, the deterministic gates, the scorer, the allocator, and the strategy-spec compiler** — that's the edge and the anti-slop. Everything else is bought/borrowed (§2).
2. **LLM proposes, deterministic disposes.** No LLM ever fires a live order or defines success. The scorer and the money live in the deterministic master, **out of the agent's reach**.
3. **One code path, three modes.** backtest = sandbox (paper, live-shadow) = live are the **same Nautilus node contexts** running the **same strategy code** (§5). Never a separate paper system.
4. **Trusted vs untrusted code split** (security + cost). Compiled `StrategySpec`s run in *our* trusted harness on our infra. The agent's *free-form* ML/feature code runs only in an **E2B/Modal sandbox** with no secrets and no venue network. Only artifacts cross back (§9, §13).
5. **Structured-first, token-frugal.** Typed Postgres rows are truth; markdown + INDEX are cheap views; RAG retrieves only what's relevant. Read the INDEX, then one record.
6. **Profit is the only score.** Every module defends itself by moving net-of-cost profit. If it doesn't, it doesn't ship.
7. **Platform, not script.** Every venue, data feature, strategy template, tool, and model is a **plug-in** — adding one is config + a small module, never a rewrite.
8. **Explore wide, gate hard.** The anti-overfitting rigor gates **capital**, not **ideas**. Generation is cheap and creative; a fixed **exploration budget** funds high-variance wildcards (not just mutations of winners); **luck is allowed to run on a paper sleeve** and is separated from edge over time by holdout + weeks of paper — never pre-judged. Keep the funnel **wide at the top, strict at the money valve**, and apply **diversity pressure** so the population never collapses to one style. The constraints (no hardcoded numbers, single-variable-by-default) are *enablers* of clean search, not a creativity tax.

---

## 2. Buy-vs-build matrix (the heart of "more buy than build")

| Layer | Decision | Choice | Why this, not hand-rolled |
|-------|----------|--------|---------------------------|
| Trading engine (backtest/paper/live) | **BUY** | NautilusTrader | Rust-native, 3-mode parity, native Binance/IBKR/**Polymarket** adapters + sandbox |
| Fast screening backtest | **BUY** | vectorbt | thousands of candidates in seconds (Numba/Rust) |
| Crypto venue breadth | **BUY** | ccxt | free, standard, many venues |
| Equities history | **BUY** | Norgate (survivorship-free daily) + Databento (intraday/breadth) | point-in-time, corp-actions-adjusted |
| Equity fundamentals | **BUY** | Sharadar (Nasdaq Data Link) or SimFin (~$30–50/mo) | point-in-time, pre-parsed — vs building an EDGAR ETL |
| Prediction markets | **BUY/lib** | Polymarket native adapter (+ Kalshi optional) | data + execution via CLOB |
| Model access | **BUY** | OpenRouter | one key, all tiers, config'd IDs |
| Structured LLM output | **BUY (OSS)** | instructor | Pydantic-validated, retried |
| Agent sandbox (untrusted code) | **BUY** | E2B | isolation, ~400ms cold start |
| ML / GPU bursts | **BUY** | Modal | usage-priced CPU/GPU |
| Voice | **BUY** | Deepgram / ElevenLabs | STT/TTS |
| Research / web | **BUY** | Exa or Tavily + news API + youtube-transcript + LunarCrush | per-query, cap-able |
| Embeddings | **BUY** | OpenAI / Voyage API | cheap |
| Vision / screenshot understanding | **BUY** | multimodal model via OpenRouter | no new vendor; powers the Console image path |
| Uploaded-image storage | **BUY/managed** | Supabase Storage | we already run Supabase |
| Param-space optimizer | **BORROW (OSS)** | Optuna | Bayesian/TPE + pruning + multi-objective; fits `param_space` (App. B) |
| Fast dataframe / feature pipeline | **BORROW (OSS)** | Polars | columnar speed over pandas; pairs with the parquet cache |
| Data-quality / look-ahead guard | **BORROW (OSS)** | Pandera | dataframe contracts; asserts point-in-time, no nulls/peeking |
| Equity hours / halts | **BORROW (OSS)** | exchange_calendars | honest equity paper fills |
| Strategy tearsheets | **BORROW (OSS)** | QuantStats | cheap rich analytics for Strategy detail |
| App errors / alerting | **BUY/OSS** | Sentry | 24/7 reliability; complements Langfuse traces |
| Property-based tests | **BORROW (OSS)** | Hypothesis | fuzz the compiler/validator/risk gauntlet |
| DB + RAG | **BUY/managed** | Supabase Postgres + pgvector | one store, a switch not a build |
| Observability + evals | **BUY/OSS** | OpenTelemetry + Langfuse | vendor-neutral; free tier/self-host |
| Hosting | **BUY/managed** | Render (worker+API), Vercel (web) | predictable beats metered |
| Anti-overfit stats | **BORROW (OSS)** | pypbo | deflated Sharpe + PBO |
| Indicators | **BORROW (OSS)** | pandas-ta / ta-lib | standard library |
| Tabular ML | **BORROW (OSS)** | XGBoost / LightGBM | CPU, proven |
| Research *patterns* | **MINE (OSS)** | Qlib/RD-Agent, QuantaAlpha, TradingAgents, Freqtrade, pine | copied into RAG, never coupled to live |
| Generated TS types | **BUY (tool)** | openapi-typescript | kills Python↔TS drift |
| UI building blocks | **BUY (OSS)** | shadcn/ui, Tremor, TanStack Table | assemble, don't handroll |
| Scheduler / job queue | **BUILD-THIN** | APScheduler + Postgres (`FOR UPDATE SKIP LOCKED`) | durable engine (Prefect/Temporal) is overkill at V1; revisit when reliability demands |
| **Farming loop + deterministic gates + scorer** | **BUILD** | ours | **THE differentiator; nobody sells it; reward-hack-safe** |
| **Strategy-spec compiler** | **BUILD** | ours | the quantamental NL→typed→runnable representation |
| **Allocator** (corr-aware capped-Kelly) | **BUILD** | ours | money logic must be ours and audited |
| **Risk gauntlet** | **BUILD** (port v1 `validator.ts`/`guardian.ts`) | ours | the deterministic spend/guardrail layer |

**Rule of thumb for the coding agent:** if it's plumbing, wire a vendor. If it decides success or moves money, we build it and audit it.

---

## 3. Repo, toolchain, layout, conventions

**New home: `apps/engine/` (Python 3.12).** v1 (`apps/api` Node, current `apps/web`) keeps running, untouched, until v2 reaches parity; then retire `apps/api` and rebuild `apps/web`.

```
apps/engine/cosmu/
  config/       # pydantic-settings: model-IDs, spend caps, venue catalog, feature registry, secrets loader
  spine/        # Nautilus node facade (backtest/sandbox/live), VenueCatalog, run lifecycle, seeded determinism
  data/
    venues/     # binance, ibkr, polymarket, ccxt (Nautilus adapters + thin wrappers)
    features/   # tier0/tier1 quant feature source modules → feature store
    market_cache.py  # parquet cache; point-in-time guarantees
  ingest/       # chat, pine, youtube, osint, news, social, vision(images)+veracity → records
  knowledge/    # postgres store (SQLAlchemy), pgvector RAG, INDEX/catalog, skills
  strategy/     # StrategySpec schema, compiler→Nautilus strategy, optimizer, static_check, seed templates
  evolution/    # seeder, mutator, screen(vectorbt), wfo(Nautilus), fold-splitter, holdout-splitter, graveyard
                #   (calls master.scorer for the verdict — does NOT own scoring; see §10)
  lab/          # agent loop, router(openrouter), instructor wiring, sandbox(e2b), ml_runner(modal), curator
                #   tools/  -> the runtime tool bus (read/research/propose only)
  ml/           # survival model (xgb/lgbm), regime classifier, feature store interface
  master/       # scheduler, queue, allocator, risk gauntlet, live gate, venue router, policy engine, audit ledger
  api/          # FastAPI app + routers (emits OpenAPI)
  obs/          # OpenTelemetry + Langfuse wiring
  evals/        # eval suites (unit / judge / trace) + CI gate runner
apps/engine/tests/
apps/engine/pyproject.toml         # uv-managed
apps/web/                          # rebuilt: Next.js + shadcn/Tremor/TanStack
packages/contracts-ts/             # GENERATED from engine OpenAPI (never hand-typed)
```

- **Tooling:** `uv` (deps/venv), `ruff` (lint+format), `pytest` (+eval gates), **Pydantic v2** everywhere, **instructor** on every LLM output, **SQLAlchemy 2.0 + Alembic** for schema/migrations.
- **Intent-spec headers:** every module in `data/ strategy/ evolution/ lab/ master/ ml/` opens with `# intent:` (purpose · inputs · outputs · invariants). Read it before the file.
- **No schema drift:** Pydantic/SQLAlchemy → FastAPI **OpenAPI** → `openapi-typescript` generates `packages/contracts-ts`. Web never re-types a model.
- **Verify:** `uv run ruff check` · `uv run pytest` · `uv run pytest -m evals` (CI gate). Web: regenerate client → `pnpm --filter @cosmu/web typecheck`.

---

## 4. The spine (hour-zero — blocking; nothing parallel starts until this is green)

1. **Engine facade (`spine/`):** thin wrapper over Nautilus exposing `run_backtest`, `run_sandbox` (paper/live-shadow), `run_live`; a `VenueCatalog` (instrument @ venue @ fee schedule @ constraints); seeded determinism. One interface, three modes.
2. **Fresh schema (`knowledge/` + Alembic):** create every VISION §10 table from zero (do **not** extend the v1 DB). Append-only `events` ledger = money-truth. pgvector on. Migrations run on boot.
3. **Tool bus (`lab/tools/`):** each capability a small module with a tiny intent-spec + typed signature, registered to the agent (MCP where it helps). **Read/research/propose only — execution is never on the bus.**
4. **Config + secrets (`config/`):** model IDs, spend caps, venue catalog, feature registry in config; secrets from server env only — **never in prompts, sandbox, or DB**.
5. **OpenAPI→TS pipeline:** FastAPI stub emitting OpenAPI + the generator wired so the web client is always generated.

**Spine DoD:** a seeded Binance-spot backtest runs through the facade, writes `backtests`/`executions`/`events` rows, and a generated TS client compiles. → open the eight tracks.

---

## 5. Execution modes & engine

**Three modes = three Nautilus node contexts, same strategy code:**

| Mode | Nautilus context | Data | Fills | Money |
|------|------------------|------|-------|-------|
| Backtest | BacktestNode | historical, point-in-time | OrderMatchingEngine + fill/fee model | none |
| **Paper (default)** | **Sandbox exec client** | **live-shadow (real-time)** | same OrderMatchingEngine, simulated | none |
| Live | Live exec client | live | venue | real, behind global toggle |

- **Paper is native** (Nautilus sandbox simulates fills against live data with the production matching engine) — we don't hand-build it; we configure fill + fee models per venue.
- **VenueCatalog** drives per-venue maker/taker fees, slippage-vs-size/liquidity/ADV, partial fills, latency, funding (perps), borrow (shorts/margin), spread, market hours/halts (equities), min-notional/lot, **prediction-market resolution/settlement** + book-depth caps.
- **Determinism:** seeded backtests; every fill written to a **fill-log** (event id, order type, price, qty, ts, slippage, commission) for reconciliation (§8).

---

## 6. Data & ingestion

> **Storage split (state it up front — a coding agent must not get this wrong):** **Postgres (Appendix A) is the control-plane + money-truth only** — strategies, runs, executions, audit, costs. **Market-data bars + history live in the Nautilus `ParquetDataCatalog`** (columnar on disk/object-store), computed/transformed with **Polars**. **Never store OHLC/tick history as row-per-bar in Postgres.** The **feature store** is a columnar **as-of store** keyed by `(instrument, feature_name, knowledge_time)`, not a Postgres table.

- **Venue market data (`data/venues/`):** Binance + ccxt (crypto), IBKR + Norgate/Databento (equities), Polymarket CLOB (prediction). **Point-in-time, survivorship-free** (incl. delisted), corp-actions-adjusted. **Store unadjusted bars + adjustment factors** (adjust at read time) so corp-action adjustment never injects look-ahead. Nautilus `ParquetDataCatalog`; live-shadow stream for paper. **Known V1 scope:** equity survivorship via Norgate (incl. delisted); **crypto universe scoped to liquid pairs with available history — delisted-alt survivorship is a documented V1 bias** (ccxt lists only live pairs), revisited if a hypothesis needs the long tail.
- **Tiered feature sources (`data/features/`)** — each a module with a **prior hypothesis** + must survive OOS (more data = more overfitting surface):
  - **Tier 0 (free, build first):** crypto funding/OI/liquidations/basis/flows; CFTC COT, put/call, VIX term; SEC EDGAR (8-K/10-Q/Form 4/13F), earnings & short-interest; FRED macro; calendars (earnings/dividends/token-unlocks/halvings/FOMC); prediction-market odds; news + social.
  - **Equity fundamentals (BUY — point-in-time, ~$30–50/mo):** **Sharadar Core US Fundamentals** (via Nasdaq Data Link) or **SimFin** — pre-parsed, survivorship-free, **as-of by filing/availability time**. Bought instead of building an EDGAR→fundamentals ETL; gives real revenue/margin/valuation features so "quantamental" is honest, not just events+technicals. (`knowledge_time` = availability time — §6 as-of join.)
  - **Tier 1 (premium, ROI-gated):** on-chain (Glassnode/Nansen/Dune), options flow/IV/GEX, estimate revisions.

**Source reality check (access · cost · cadence/lag · known limit — every source module declares its key + rate-limit + as-of cadence in config):**

| Source group | Access | Cost | Cadence / lag | Known limit & how we handle it |
|---|---|---|---|---|
| Crypto bars/funding/OI/basis | ccxt + exchange REST/WS | free | continuous | OI/funding **history depth is shallow** via ccxt (recent only) → backfill from exchange endpoints; accept short history else |
| **Crypto liquidations** | exchange WS snapshot | free **(degraded)** / Coinglass paid | continuous | **Binance restricted the full public feed (2021)** — WS is a throttled snapshot, *not* the full tape → **best-effort feature, flagged low-confidence**; promote to **Coinglass (Tier-1)** only if it earns OOS |
| Equity bars | Norgate + Databento | paid | EOD / intraday | fine (survivorship-free, corp-action factors) |
| Equity fundamentals **+ earnings dates** | Sharadar / SimFin | paid (~$30–50/mo) | per-filing, point-in-time | earnings calendar is **sourced here**, not a free feed |
| SEC EDGAR (8-K/Form4/13F) | EDGAR API | free | event; **13F +45d, Form4 +2d** | lagged by design → **stamp publication time** (as-of); UA header + ≤10 req/s |
| CFTC COT | Socrata/CFTC | free | weekly, **+3d** | low-freq/lagged — fine at swing horizon |
| FRED macro | FRED API (key) | free | daily/monthly | none material |
| CBOE put/call · VIX term | CBOE / FRED | free (some delayed) | daily | delayed snapshots OK at swing horizon |
| **Token unlocks** | **DefiLlama emissions API** | free-ish | event | no single clean feed → DefiLlama, **best-effort** |
| Calendars (FOMC/halving/dividend) | static/derived | free | event | fine |
| Prediction-market odds | Polymarket CLOB | free | continuous | fine |
| News | Exa / Tavily | paid | continuous | confirm/veto only (never originates a liquid-market trade) |
| Social | LunarCrush | paid tier | daily | confirm/veto only |

**Rule for lagged/low-frequency sources:** the `knowledge_time` stamped into the feature store is the **publication/availability time**, never the period the datum describes — the as-of join then makes the lag *safe* instead of look-ahead. Best-effort sources (liquidations, token-unlocks) ship as **low-confidence features that must earn their place through the same OOS gate**; nothing degraded is trusted by default.
- **Feature store** (`ml/feature_store`): columnar, keyed by `(instrument, feature_name, knowledge_time)`. Reads are **as-of joins** — a feature value is visible to a bar only if its `knowledge_time ≤ bar_time` (backward-only join), which is what mechanically prevents look-ahead. Validated by **Pandera** on write (dtype, null, monotonic ts, no future timestamps). The equity/fundamental case (where `knowledge_time` = filing/availability time, not the period it describes) is exactly why we store knowledge-time, not just event-time.
- **Qual ingestion (`ingest/`):** chat ideas, PineScript, YouTube transcripts, OSINT, news, social, **images/screenshots** → `sources` rows + embeddings → RAG. Mined for *testable* rules. Qual **confirms/vetoes** in liquid markets; **originates only in prediction markets**.
- **Vision + veracity pipeline (`ingest/vision.py`):** Console image upload → store in Supabase Storage → **multimodal model (OpenRouter)** + `instructor` extracts a typed `ImageExtract` (kind ∈ tweet/post/trades/chart/other; `claims[]` with entity/metric/value/timestamp; apparent strategy structure if any). Then a **veracity gate** (`ingest/veracity.py`, deterministic-assisted) loops each claim: route to the matching data tool (price/OHLC at `ts`, news/EDGAR/FRED for events), and label `verified` / `contradicted` / `unverifiable`. **Rules:** numeric P&L from a third-party screenshot is always `unverifiable` → discard the number, keep only the *setup structure* as a hypothesis; a `contradicted` claim is logged and vetoes (never trades); a `verified` claim behaves as a normal qual signal (confirm/veto in liquid markets, may originate only in prediction markets). The graded result is written as a `source` with a `veracity` field + `claims` jsonb. **Screenshots get the strictest gate because they're the lowest-trust input** — never evidence on trust, only (at most) a gated hypothesis or a monitor.
- **RAG + INDEX (`knowledge/`):** pgvector retrieval; `INDEX.md` + `catalog` table. Mine `TradingAgents-main`, **Qlib/RD-Agent**, **QuantaAlpha**, Freqtrade, pine as *patterns* into RAG.

**DoD:** ≥15 Tier-0 features served point-in-time across crypto/equities/prediction odds; RAG returns relevant prior art for a sample hypothesis.

---

## 7. Strategy spec & compiler (the differentiator)

- **`strategy/spec.py` — typed `StrategySpec` (Pydantic):** `universe` (venue/asset/liquidity selectors), `horizon` (1h/4h/1d bars, hold days–weeks), `catalyst` (event/news/regime trigger, optional), `entry`/`exit` **structure referencing named features** (SL/TP **required**), `risk`, `rationale` (LLM's economic *why*), `param_space` (what the optimizer fits).
- **Hard rule:** the **LLM may not hardcode thresholds / magic numbers.** It authors structure + names features + declares `param_space`. **Numbers are fit from data.**
- **`strategy/compiler.py`:** `StrategySpec → runnable Nautilus Strategy` (deterministic, no LLM at runtime).
- **`strategy/optimizer.py`:** fits `param_space` on **in-sample folds only**; **every trial counted** for the multiple-testing correction (feeds deflated Sharpe in §8).
- **`strategy/static_check.py`:** AST allowlist on any agent-authored code — no network/filesystem/secrets, imports from a safelist only. Runs before execution. (Trusted-code path.)

**DoD:** a hand-written sample spec compiles, optimizes on IS, runs OOS; an LLM-authored spec passes `instructor` with **zero hardcoded numbers** and compiles.

---

## 8. Evolution loop & scorer

**Loop (`evolution/`), 24/7:**
`seed/mutate → compile → static-check → **fast vectorized screen (vectorbt)** → IS optimize → **walk-forward OOS validation (Nautilus BacktestNode)** → score → gate → untouched-holdout (once) → allocate paper sleeve → keep / kill / mutate`.

- **Two lanes (explore/exploit, config split ~70/30):** an **exploit lane** mutates/recombines survivors (incremental, attribution-clean); an **explore/wildcard lane** authors novel, high-variance, low-prior specs reaching outside the population (exotic feature combos, cross-market transfer, bold multi-variable leaps) so the machine can get *lucky* and escape local optima. Same scorer for both; **neither is judged at birth.** The explore budget is **guaranteed** — the survival model prioritizes compute but never vetoes an idea, so its own blind spots surface. **Diversity pressure** keeps decorrelated/unusual strategies alive even at slightly lower rank (option value across regimes).
- **Two-tier backtest (throughput):** vectorbt screens thousands cheaply, kills obvious losers; only survivors pay for full event-driven Nautilus validation with realistic fills. The **survival model (§12)** ranks which survivors to validate first. *(Cheap screening exists precisely so exploration can be wide.)*
- **Fill-log reconciliation (flaw-fix):** compare the vectorbt screen's assumed fills to Nautilus's fill-log; if they diverge beyond a tolerance, **trust Nautilus** and flag the screen (prevents the cheap stage silently lying).
- **Walk-forward:** thin orchestration over `BacktestNode`/`BacktestRunConfig` (params via config, no code changes) + our fold splitter (rolling IS/OOS) + a final **untouched holdout** seen once.
- **Scorer (`master/scorer.py` — DETERMINISTIC, OUT OF AGENT REACH):** single ranking scalar = **deflated OOS Sharpe** via **pypbo** (Bailey/López de Prado), corrected for **trial count**; gates: min-trades, max-drawdown, multi-regime, holdout; also computes **Probability of Backtest Overfitting**.
- **Graveyard:** killed versions recorded *with reasons* — learn from deaths, never survivor-bias our own population.
- **Capital handoff:** gate-passers get a standardized **$100k sleeve** (eval layer); proven survivors get **pooled-wallet** allocation (§10).

**DoD:** the loop autonomously seeds→screens→validates→scores→kills→keeps with no human input; deflated Sharpe + PBO per `strategy_version`; graveyard populated; reconciliation catches an injected screen/engine mismatch.

---

## 9. Lab agent & model router

**Agent loop (`lab/agent.py`) — our own thin orchestration, not a framework:**
```
draft  = cheap_tier.propose(spec | mutation)        # breadth
spec   = instructor.validate(draft, StrategySpec)   # structured; NO magic numbers
code   = strategy.compiler.compile(spec)            # trusted path
static_check(code)
result = evolution.screen_then_validate(code)       # vectorbt → Nautilus, OUR infra
score  = master.scorer(result)                      # deterministic; agent can't alter
store(spec, code, result, score)                    # structured + audited
if passes_gate: holdout(); allocator.seed_sleeve()
if success:     curator.distill_skill(spec, result) # Hermes skill pattern
```
- **Trusted vs untrusted code (critical):** compiled `StrategySpec`s run on **our infra** (fast, cheap, allowlisted). The agent's *free-form* ML/feature code runs **only in E2B/Modal** (no secrets, no venue network); only artifacts (features, model files, predictions) return. **E2B is not in the per-backtest hot path** → cost + security stay sane.
- **Model router (`lab/router.py`):** single gateway = **OpenRouter**; model IDs in config; tiers — *frontier* (Opus 4.8 / GPT-5.5 / Grok) judges depth · *mid* (Sonnet / GPT-5-mini / DeepSeek-V3) routine · *cheap* (DeepSeek / Qwen / Hermes-4) drafts breadth. Deterministic policy: task declares difficulty+budget → cheapest tier clearing a quality bar, escalate on low confidence, **respect the daily spend cap**.
- **Sandbox:** **E2B** for code, **Modal** for ML/GPU bursts. Hard **sandbox-time cap** (per-second billing runaway guard).
- **Self-improvement (Hermes skill pattern):** success → distilled **skill** (parameterized recipe, embedded); periodic **Curator** grades skills by downstream OOS success and prunes.

**DoD:** the agent autonomously authors a valid spec, runs free-form feature code in E2B, gets a score it can't influence, and distills one Curator-graded skill.

---

## 10. Deterministic master (the safety partition)

Single control plane (`master/`). Small, strongly-typed, fully audited. Owns everything irreversible.

| Component | Responsibility |
|-----------|----------------|
| `scheduler.py` + `queue.py` | one loop; atomic job claim (`SELECT … FOR UPDATE SKIP LOCKED`); no missed/double runs; every tick audited |
| `scorer.py` | the fitness authority (§8) — **agent cannot touch** |
| `allocator.py` | pooled wallet: capped-Kelly, **correlation-aware**, compounding into survivors, defunding losers |
| `risk.py` | the validator gauntlet (§13) on **every** order |
| `live_gate.py` | global toggle (**off by default**); on flip, gate-passers auto-promote under per-strategy + global caps; auto-defund on live<paper divergence |
| `venue_router.py` | routes the same strategy entity to sandbox(paper) or a live venue adapter — **all venues identical, incl. Polymarket** |
| `policy.py` | parses chat/voice → **validated** config deltas (risk/allocation/universe), applied atomically + audited |
| `audit.py` | append-only `events` ledger — the money-truth |

**The partition that makes autonomy safe:** the scorer and the money live here, deterministic, out of the agent's reach.

**DoD:** scheduler runs unattended; a chat command becomes a validated policy delta; flipping the (test) toggle promotes a paper survivor through the gauntlet in simulation.

---

## 11. Venues

| Venue | Adapter | V1 status | Notes |
|-------|---------|-----------|-------|
| **Binance spot** (crypto) | Nautilus native | paper now, live under toggle | cleanest V1 execution venue |
| **ccxt** (crypto breadth) | Nautilus/ccxt | paper | more crypto venues |
| **IBKR** (equities) | Nautilus native | paper now, live under toggle | exec needs gateway; data via Norgate/Databento |
| **Polymarket** (prediction) | **Nautilus native** (`py-clob-client-v2`) | paper now, **live under the same global toggle as every venue** | live-only adapter → paper = sandbox sim-fill on live CLOB book; needs Polygon wallet + pUSD/USDC to go live; **operator owns legality** (France geoblock) — no system special-casing |
| Kalshi (prediction) | pykalshi / PMXT | optional | US-only; add if jurisdiction allows |

Arbitrage is just a strategy template over simultaneous multi-venue pricing (fee/latency-aware).

**DoD:** the same `StrategySpec` runs in paper across Binance, an equity, and a Polymarket market with correct per-venue fees/fills; Polymarket adapter authenticates and reads the live CLOB book in sandbox mode.

---

## 12. ML

- **Agent-written ML (`ml/` via Modal, untrusted):** the agent writes/runs its own feature-eng/model/training/eval in the sandbox; keeps whatever beats the deterministic OOS scorer (which it can't alter). **Closure rule:** an agent-engineered feature only becomes usable by a strategy by **entering the named feature registry through the same gate as any feature** — declared prior hypothesis, **point-in-time/no-look-ahead enforced (Pandera)**, then it must earn its place via the OOS scorer. Nothing the agent fabricates in the sandbox bypasses data-quality checks or the deterministic scorer — the partition (§13) holds for ML too.
- **Tabular survival model (XGBoost/LightGBM):** predicts whether a `strategy_version` holds edge OOS → **prioritizes compute** (which screen survivors to validate first) + **flags overfit**. Itself OOS-validated. **Cold-start:** at boot there's no labeled death history, so prioritization falls back to **random/cheap-heuristic** ordering until ≥ N labeled outcomes exist (config); the model only takes over once trained and OOS-validated. It **never vetoes** an idea (§8) — only orders the queue — so a useless early model can't strangle discovery.
- **Regime classifier:** labels market regime (vol/trend/breadth); the master uses it to gate **which strategies may go live**. **Bootstrap:** the multi-regime *gate* (Appendix C) and live-eligibility need labels **before** this ML classifier lands (track G, checkpoint 4) — so start with **deterministic vol/trend buckets** (e.g. realized-vol tercile × trend sign) computed from price; the classifier refines/replaces those labels later without changing the gate's interface.
- **Feature store** (shared with §6): point-in-time, named features.

**DoD:** survival model produces a calibrated edge-persistence score used to order the validation queue; regime classifier gates a sample strategy's live-eligibility.

---

## 13. Risk & security model (deterministic, non-negotiable)

**Validator gauntlet** (port + harden v1 `validator.ts`/`guardian.ts`) on **every** order, paper or live:
- venue/pair authorization, min-notional/lot/tradability, budget + safety buffer, min cash reserve;
- **SL/TP required** on entries; max orders/run; market/limit policy; **book-depth/ADV size caps** (capacity);
- **data-freshness guard:** every feature an order depends on must be **as-of within a per-feature staleness tolerance** of now (and the venue feed must be live); stale/missing/gapped data → **veto the order** (skip, don't guess). Paper→live parity is a silent killer — never trade on data we can't currently trust;
- **memoryless sizing:** size = f(equity, vol, conviction), **never** f(past losses); martingale/averaging-down/"win it back" **banned**;
- portfolio **drawdown kill-switch**; per-strategy + global exposure caps; **daily LLM/API + sandbox spend cap**;
- **live OFF by default**; on promotion, per-strategy + global live caps.

**Security model:**
- Secrets (venue keys, model/API keys) **server-side env only** — never in prompts, sandbox, DB, or frontend.
- **Sandbox isolation:** E2B/Modal have **no secrets** and **no execution-venue network path**; only data-in / artifacts-out.
- **Trusted/untrusted split** (§9): untrusted code never runs with credentials or order access.
- Venue keys created **trade-only, withdrawals disabled** where the venue supports it (Binance/IBKR). For **self-custodied wallets where you can't disable withdrawal** (Polymarket = a Polygon wallet signing CLOB orders), enforce it operationally: a **dedicated low-balance hot wallet** funded only with the strategy's live allocation, topped up from a separate cold wallet — never the main treasury behind a hot key.
- **API auth (single-owner):** every **mutating** route — above all `POST /toggle/live`, `POST /console/command`, policy/allocation/cap changes — sits behind auth (Supabase Auth session or a server-side token); read routes may be looser. Uploaded images are validated (type/size) and stored private (signed URLs), never executed. The live toggle additionally requires an explicit `confirm` flag (§14).

**DoD:** every order path hits the gauntlet; a banned martingale spec is rejected; the kill-switch trips a simulated drawdown; a secret never appears in any sandbox or prompt (asserted by a test).

---

## 14. API surface (FastAPI → OpenAPI → TS)

Thin, typed routers (the web's only contract):
- `GET /portfolio` (pooled wallet, equity curve, allocation, costs) · `GET /leaderboard` (sleeves, deflated Sharpe, net %, PBO, status) · `GET /strategies/{id}` (spec, code, trades, OOS/holdout, notes) · `GET /costs` (attribution) ·
- `POST /console/command` (chat → validated policy delta) · `POST /console/voice` (STT in/TTS out) · `POST /console/upload` (image → vision-extract + veracity gate → typed `source` + reply/recommendation) · `GET /recommendations` + `POST /recommendations/{id}/approve` ·
- `POST /toggle/live` (the global toggle; off by default; gated) · `GET /events` (audit stream).

All response models are Pydantic → OpenAPI → `packages/contracts-ts`. **DoD:** OpenAPI emits; the TS client compiles; every surface in §15 reads only generated types.

---

## 15. Frontend (4 surfaces, beautiful, lean)

Next.js + **shadcn/ui** + **Tremor** + **TanStack Table**, dark/modern, desktop-first/mobile-friendly, **generated TS client** only.
1. **Dashboard** — pooled wallet equity (paper+live), P&L net of all costs, allocation treemap, **Costs card** (infra/hosting/data/LLM-sandbox, drill-down per-category & per-strategy), opex-vs-profit gauge, **global live toggle (off)**.
2. **Leaderboard** — every strategy-version on its $100k sleeve, ranked by deflated OOS Sharpe, **net % displayed prominently**, lineage, status, PBO.
3. **Strategy detail** — backtest+paper equity, trade blotter, the spec + compiled code, agent notes/post-mortem, fee/slippage breakdown, OOS-vs-holdout.
4. **Console** — **chat + voice** (STT in / TTS out) control + recommendation/approval inbox + the live toggle.

**DoD:** all four render live engine data via the generated client; Console sends a validated command and shows a proactive recommendation; voice round-trips.

---

## 16. Observability & evals

- **`obs/`:** OpenTelemetry spans across master + agent + tools → **Langfuse** (free tier/self-host). The `events` ledger stays money-truth.
- **3-layer evals (`evals/`):** unit evals on agent steps · LLM-as-judge regression suites · production-trace sampling. **Failed online scores become eval cases.**
- **CI eval gate:** `pytest -m evals` blocks merges that drop quality.

**DoD:** a trace for one agent task appears in Langfuse; a failing judge eval blocks a CI run.

---

## 17. Costs & ROI accounting

- **`costs` + `llm_calls` tables:** every LLM call (tier/tokens/cost), sandbox-second, data query, infra slice → attributed **per-strategy** where possible.
- **Net edge = alpha − attributed opex**, surfaced on Dashboard + Strategy detail.
- **Auto-throttle:** research/LLM/sandbox spend capped as a **% of trailing realized edge**; not earning → drop to cheap tier; earning → spend more.

**DoD:** Dashboard shows real opex vs paper alpha; a strategy's net nets its opex share; throttle trips past the trailing-edge cap.

---

## 18. Deployment topology

| Piece | Runs on | Notes |
|-------|---------|-------|
| Research worker (loop, scheduler, agent) | **Render** worker (CPU) | continuous; vertical-scale first, worker pool later |
| API (FastAPI) | **Render** service | emits OpenAPI |
| Web | **Vercel** | generated TS client |
| DB + RAG | **Supabase** (Postgres + pgvector) | migrations on boot |
| Untrusted code / ML bursts | **E2B** (code) / **Modal** (GPU) | usage-priced, capped |
| Traces | **Langfuse** (free tier/self-host) | OTel exporter |

Migrations run on boot (port the v1 migrate-on-start pattern to Alembic). Secrets in Render/Vercel/Supabase env.

---

## 19. Sequencing & milestones

- **Phase 0 — Spine (hour-zero, blocking):** §4. Everything waits on it.
- **Phase 1 — eight parallel tracks** (open once spine is green):
  A. Data & ingestion (§6) · B. Strategy spec & compiler (§7) · C. Evolution loop & scorer (§8) · D. Lab agent & router (§9) · E. Master (§10) · F. Venues & paper fills (§11) · G. ML (§12) + Risk/security (§13) · H. API (§14) + Frontend (§15) + Obs/evals (§16) + Costs (§17).
- **Integration checkpoints:**
  1. B+F → one spec runs in paper on one venue (correct fees/fills, fill-log written).
  2. +C+E → the loop autonomously seeds/screens/validates/scores/kills.
  3. +D → the agent authors specs into the loop; skills distilled.
  4. +A+G → real Tier-0 features + ML prioritization + regime gating.
  5. +H → you watch and steer it (Dashboard/Leaderboard/Detail/Console), costs visible.
- **V1 done = the whole machine runs autonomously in paper across crypto + equities + prediction markets, live-off, one toggle from real money, with costs < trailing paper edge.**
- **V2 = flip live on live-proven survivors; more venues, FX/options, deeper arbitrage/ingestion/ML; optional Numerai Signals side-revenue.**

---

## 20. Risk register (technical) + mitigations

| Risk | Mitigation |
|------|-----------|
| Backtest throughput bottleneck | two-tier (vectorbt screen → Nautilus validate) + ML-prioritized validation queue |
| Screen vs engine disagreement | fill-log reconciliation; trust Nautilus, flag the screen |
| Overfitting / data dredging | deflated Sharpe + trial-count correction + PBO + holdout + graveyard |
| Reward-hacking | scorer + money in the master, out of agent reach; untrusted code sandboxed |
| Untrusted agent code | E2B/Modal, no secrets/network; AST allowlist on trusted path; artifacts-only return |
| Cost runaway (sandbox per-second) | hard sandbox-time cap + daily spend cap + cheap-tier-default routing + ROI throttle |
| Paper ≠ live | native Nautilus sandbox on live-shadow data; realistic fee/slippage/funding/borrow/halts; auto-defund on divergence |
| Schema drift Python↔TS | Pydantic→OpenAPI→generated TS, never hand-typed |
| Loop reliability | one scheduler, atomic claim, every tick audited |
| Data quality | point-in-time, survivorship-free (Norgate), corp-actions-adjusted, seeded |
| Secret leak | server-side env only; trade-only keys; sandbox has none; asserted by test |
| Prediction-market resolution/legal | adapter models resolution; operator owns jurisdiction (no system branch) |
| Complexity creep | 4 surfaces; everything a plug-in; intent-specs; profit-only filter on features |

---

## 21. "It wins" — acceptance criteria + the flywheel

V1 **works** when, with **zero human authoring**, the machine:
1. autonomously seeds, screens, validates, scores, and **kills 95%+** on deflated OOS Sharpe + holdout, recording every death;
2. surfaces a **decorrelated handful** that clear the gates **and survive 4–6 weeks of realistic paper** with positive net-of-cost edge **at fillable size**;
3. proves them across **crypto + equities + prediction-market** paper with correct fees/fills;
4. keeps **opex < trailing paper edge** (throttling when not earning);
5. would, on flipping the toggle, **auto-promote** exactly those survivors under caps — and **auto-defund** any whose live edge decays.

**The flywheel (better/faster/stronger):** more runs → more labeled outcomes → sharper survival model → smarter compute allocation (screen many, full-validate the right few) → faster discovery; success → skills (Curator-pruned) that raise authoring quality; the graveyard stops re-walking dead ends; more data → better features → better strategies → more data. It compounds *research efficiency*, not just capital.

**The honest bar:** winning ≠ guaranteed profit. Winning = a **disciplined research machine that finds and sizes small, real, decaying edges and refuses to fool itself.** The edge most likely to pay at this size: **neglected markets (small-caps, long-tail alts, prediction markets) + slow alt-data + risk-management-as-alpha + a decorrelated ensemble.** Flat paper months are the gates working, not failure.

---

## 22. Hour-zero task list (first commits)

1. Scaffold `apps/engine` (uv, ruff, pytest, Pydantic, SQLAlchemy/Alembic, FastAPI). Intent-spec headers in every package.
2. `spine/`: Nautilus node facade (backtest/sandbox/live) + `VenueCatalog` + seeded backtest path + fill-log.
3. `knowledge/`: Alembic migrations for the full VISION §10 schema from zero; pgvector on; `events` ledger.
4. `lab/tools/`: tool-bus registry + first read-only tools (market-data, backtest, RAG-read).
5. `config/`: settings, model-IDs, spend caps, venue catalog, feature registry; env-only secret loading.
6. FastAPI stub + OpenAPI emit + `packages/contracts-ts` generator.
7. **Green spine check:** seeded Binance backtest writes `backtests`/`executions`/`events`; TS client compiles. → open the eight tracks.

---

## Appendix A — Data model (DDL-level spec)

> Postgres on Supabase, pgvector on. **Alembic generates the real DDL; this is the target shape.** Conventions: `id` = `uuid` PK (except `events.id` = `bigserial`); `*_at` = `timestamptz`; money = `numeric(20,8)`; flexible payloads = `jsonb`. **Two invariants the code must enforce:** `events` and `executions` are **append-only/immutable** (no UPDATE/DELETE — enforce via DB role grants + a guard trigger); the `events` ledger is the **money-truth** (every irreversible act writes a row here in the same transaction).

**Reference / catalog**
- `venues`(id, name, kind `enum[crypto|equity|prediction]`, adapter, fee_schedule `jsonb`, constraints `jsonb`, enabled `bool`)
- `instruments`(id, venue_id→venues, symbol, asset_class, tick_size `numeric`, lot_size `numeric`, min_notional `numeric`, listed_at, **delisted_at** `nullable` ← survivorship lives here, active `bool`) · idx(venue_id, symbol)
- `catalog`(id, ref_type, ref_id, title, summary, section, updated_at) — the INDEX over everything

**Strategy population**
- `strategies`(id, name, thesis, origin `enum[agent|chat|pine|mined]`, created_at)
- `strategy_versions`(id, strategy_id→strategies, **parent_id**→self `nullable`, spec `jsonb` (App. B), generated_code `text`, code_hash, params `jsonb`, mutation_operator, mutation_rationale, origin `enum`, status `enum[draft|screening|validating|paper|live|killed]`, created_at, killed_at, kill_reason) · idx(status), idx(parent_id)
- `backtests`(id, strategy_version_id→…, kind `enum[screen|wfo|holdout]`, is_start, is_end, oos_start, oos_end, oos_return `numeric`, sharpe, sortino, **deflated_sharpe**, max_dd, win_rate, num_trades `int`, **pbo** `numeric`, **trials_counted** `int`, regime_label, folds_positive `int`, passed_gates `bool`, holdout_passed `bool`, created_at) · idx(strategy_version_id, kind)
- `graveyard` view = `strategy_versions WHERE status='killed'` (kill_reason required)

**Execution & money (immutable)**
- `runs`(id, strategy_version_id, mode `enum[backtest|sandbox|live]`, venue_id, seed `bigint`, started_at, ended_at, status)
- `executions`(id, run_id→runs, strategy_version_id, instrument_id, venue_id, side `enum[buy|sell]`, qty, price, fee, slippage, order_type, is_paper `bool`, ts, **fill_log** `jsonb`) — *immutable* · idx(run_id), idx(ts)
- `positions`(id, scope `enum[sleeve|pool]`, ref_id, instrument_id, qty, avg_price, unrealized_pnl, opened_at)
- `portfolio_snapshots`(id, scope `enum[sleeve|pool]`, ref_id, ts, equity, cash, positions_value, pnl, drawdown) · idx(scope, ref_id, ts)

**Capital layers**
- `sleeves`(id, strategy_version_id→… **unique**, starting_capital default 100000, equity, return_pct, updated_at) — eval layer
- `allocations`(id, strategy_version_id, weight, capital, kelly_fraction, correlation_group, cycle_ts) — pooled-wallet layer · idx(cycle_ts)
- `live_toggle`(id **singleton**, enabled `bool` default false, enabled_at, enabled_by)
- `live_caps`(id, scope `enum[global|venue|strategy]`, ref_id `nullable`, max_notional, max_daily_loss)

**Knowledge, agent, control**
- `skills`(id, name, recipe `jsonb`, grade `numeric`, lineage `jsonb`, success_count `int`, embedding `vector`, created_at, pruned_at)
- `sources`(id, kind `enum[chat|pine|youtube|news|osint|social|image]`, uri (Supabase Storage for images), raw `text`, extracted `jsonb`, **claims** `jsonb` (per-claim verdict+evidence), **veracity** `enum[verified|contradicted|unverifiable|mixed|na]` default `na`, embedding `vector`, ingested_at)
- `research_notes`(id, strategy_version_id `nullable`, kind, body_md, structured `jsonb`, embedding `vector`, created_at)
- `recommendations`(id, ts, kind, body, state `enum[open|approved|dismissed]`, payload `jsonb`)
- `policies`(id, ts, source `enum[chat|voice]`, raw_text, parsed `jsonb`, scope, applied `bool`, applied_at)

**Costs & audit**
- `costs`(id, ts, vendor, category `enum[infra|hosting|data|llm|sandbox|voice|research]`, amount, currency, strategy_version_id `nullable`, meta `jsonb`) · idx(ts), idx(strategy_version_id)
- `llm_calls`(id, ts, tier `enum[frontier|mid|cheap]`, model_id, task, tokens_in, tokens_out, cost, latency_ms, confidence `nullable`, strategy_version_id `nullable`, trace_id) · idx(ts)
- `events`(id `bigserial`, ts, actor `enum[master|agent|human|system]`, kind, ref_type, ref_id, payload `jsonb`) — **append-only money-truth** · idx(ts), idx(ref_type, ref_id)

**Vectors:** `vector` columns on `skills/sources/research_notes`; ivfflat (or hnsw) indexes; embedding dim from config. **FKs** indexed throughout.

**Growth (24/7 forever):** the append-only/high-churn tables — `events`, `executions`, `portfolio_snapshots`, `llm_calls`, `costs` — are **time-partitioned (monthly, by `ts`)** with a retention/rollup policy in config (snapshots can downsample beyond a horizon; `events` never deletes — archive cold partitions). Bar/feature history is **not** here (it's the Parquet catalog, §6), so Postgres stays the small, fast control-plane.

---

## Appendix B — StrategySpec & compiler contract

> The differentiator's data structure. The LLM authors a **typed spec**; a deterministic compiler turns it into a runnable Nautilus strategy. Illustrative Pydantic (real types live in `strategy/spec.py`):

```python
class ParamSpace(BaseModel):                 # what the OPTIMIZER fits — never the LLM
    kind: Literal["int","float","choice"]
    lo: float | None = None; hi: float | None = None; step: float | None = None
    choices: list[float] | None = None

class ParamRef(BaseModel):                   # a threshold is a NAMED param, not a literal
    param: str                               # must be a key in StrategySpec.param_space

class FeatureRef(BaseModel):
    name: str                                # MUST resolve in the feature registry (App. D)
    lookback: ParamRef | int | None = None   # bars; optimizer may fit if a ParamRef

class Condition(BaseModel):
    feature: FeatureRef
    op: Literal["gt","gte","lt","lte","cross_up","cross_down","between"]
    threshold: ParamRef                      # <-- ParamRef ONLY. literal numbers REJECTED.

class ExitRules(BaseModel):
    stop_loss: ParamRef                      # REQUIRED
    take_profit: ParamRef                    # REQUIRED
    signal_exits: list[Condition] = []
    time_stop_days: ParamRef | None = None

class StrategySpec(BaseModel):
    name: str
    rationale: str                           # the economic WHY (the LLM's contribution)
    universe: UniverseSelector               # venue + asset_class + liquidity/ADV filters
    horizon: Horizon                         # bar size (1h/4h/1d) + hold window (days–weeks)
    catalyst: Catalyst | None = None         # event/news/regime trigger (optional)
    entry: list[Condition]                   # references named features
    exit: ExitRules                          # SL + TP REQUIRED
    risk: RiskRules                          # conviction + risk *constraints* (max position cap, max concurrent,
                                             #   conviction score) — NOT absolute dollar sizing. The deterministic
                                             #   allocator/risk layer (§10/§13) owns final size = f(equity, vol,
                                             #   conviction); a spec can never set its own notional or martingale.
    param_space: dict[str, ParamSpace]       # the ONLY place numbers come from
```

**Validation rules (`static_check.py`, enforced before anything runs):**
1. **No magic numbers.** Every `threshold`/`stop_loss`/`take_profit`/`time_stop` is a `ParamRef` resolving into `param_space`. A literal number anywhere in entry/exit ⇒ **reject**.
2. Every `FeatureRef.name` resolves in the **feature registry** (App. D). Unknown feature ⇒ reject.
3. `exit.stop_loss` and `exit.take_profit` are present. Missing ⇒ reject.
4. `universe` resolves to **≥ N instruments** (config, default 5) at author time.
5. Any agent-authored Python touches an **AST allowlist** only (no `import os/sys/socket`, no filesystem, no network, no `eval/exec`).

**Compiler contract (`compiler.py`):** `compile(spec, params) -> nautilus Strategy subclass`. **Pure & deterministic** — no LLM, no network, no clock at runtime; same `(spec, params)` ⇒ same `code_hash`. The optimizer fits `param_space` on **in-sample folds only**; **every trial is counted** and written to `backtests.trials_counted` (feeds the deflated-Sharpe correction, App. C).

---

## Appendix C — Scorer, gates & walk-forward (concrete defaults)

> The fitness authority lives in `master/scorer.py`, **deterministic, out of the agent's reach.** All thresholds are **config** (App. G) — tunable by master/human, never by the agent. Defaults below.

**Walk-forward (rolling, anchored=false):**
| Asset class | IS window | OOS window | Step | Min folds |
|-------------|-----------|------------|------|-----------|
| Equities | 18 mo | 3 mo | 3 mo | 5 |
| Crypto | 9 mo | 3 mo | 1 mo | 6 |
| Prediction markets | by event cohort (resolved events) | next cohort | cohort | 4 |

**Untouched holdout:** the most-recent **3 months** (event-cohort for PM) — **never touched during search**, evaluated **once** at promotion. Touch it twice and it's burned.

**Gates (must clear ALL even to be *ranked*):**
- `num_trades ≥ 30` over concatenated OOS · `max_dd ≤ 25%` (per-asset config) · OOS return positive in `≥ 60%` of folds · multi-regime: positive in `≥ 2 of 3` labeled regimes (labels = deterministic vol/trend buckets at first, ML-refined later — §12) · `pbo ≤ 0.5` · holdout `deflated_sharpe > 0`.

**Ranking scalar (single):** **deflated OOS Sharpe** (Bailey/López de Prado, via `pypbo`) on concatenated OOS, corrected for `trials_counted` (param trials + sibling variants in that search). **Tie-break:** lower PBO → then higher net %. Leaderboard *sorts* by deflated Sharpe, *displays* net % prominently.

**Promotion ladder:**
1. **→ paper sleeve:** clears all gates.
2. **→ live** (only when toggle ON): gates **+** survived **≥ 4 weeks** realistic paper with net-positive edge **+** regime classifier says *current* regime ∈ the strategy's proven regimes **+** live caps available.

**Kill / defund:** fail any gate ⇒ kill (write `kill_reason`). Live edge < paper edge by `> tolerance` (config) ⇒ **auto-defund**. Trailing paper edge turns negative beyond tolerance ⇒ kill. Every death recorded in the graveyard *with reason* — never survivor-bias our own population.

---

## Appendix D — Feature registry v0 (named features)

> The LLM's **vocabulary** and the feature store's **build list**. Every feature: `name` · source · as-of semantics (point-in-time, no look-ahead) · a one-line **prior hypothesis** (why it could carry edge at swing horizon). Start Tier-0; each must survive the same OOS gate or it's dropped. *This list is the v0 seed — the registry is a plug-in table, features are added by config + a small source module.*

**Crypto microstructure (ccxt + exchange APIs, free):** `funding_rate` (carry/positioning), `open_interest`, `oi_change` (leverage build-up), `liquidations_long`/`liquidations_short` (forced flow → reversals — **best-effort/low-confidence: full public feed restricted, see §6 reality check; Coinglass Tier-1 upgrade if it earns**), `perp_spot_basis` (risk appetite), `exchange_netflow` (accumulation/distribution), `taker_buy_sell_ratio` (aggressor imbalance).

**Cross-asset / macro (FRED, CFTC, CBOE, free):** `vix_term_slope` (risk regime), `putcall_ratio` (sentiment extreme), `cftc_net_positioning` (crowding), `dxy` (risk-on/off), `yield_curve_2s10s`, `credit_spread` (financial conditions).

**Equity events (SEC EDGAR free; `days_to_earnings` calendar from the fundamentals vendor):** `days_to_earnings`, `post_earnings_drift`, `insider_buy_ratio` (Form 4), `short_interest_ratio` (squeeze fuel), `inst_ownership_change` (13F).

**Equity fundamentals (Sharadar/SimFin, bought, point-in-time):** `revenue_growth_yoy`, `gross_margin_trend`, `fcf_yield`, `earnings_surprise`, `valuation_z` (sector-relative P/E or EV/EBITDA) — each as-of by filing/availability time (no restatement look-ahead).

**Calendars (free):** `days_to_token_unlock` (crypto supply shock — **DefiLlama emissions, best-effort**), `days_to_halving`, `days_to_fomc`, `days_to_dividend` (dividend/earnings dates from the fundamentals vendor).

**Price / technical (pandas-ta on point-in-time bars):** `ret_Nd`, `atr`, `rsi`, `adx`, `bb_z`, `vol_realized`, `volume_zscore`, `breadth_adv_dec`.

**Prediction markets (Polymarket CLOB, free):** `pm_implied_prob`, `pm_prob_velocity` (re-pricing speed), `pm_book_depth` (capacity), `pm_days_to_resolution`.

**Sentiment (LunarCrush/news — confirm/veto only, never originates a liquid-market trade):** `lunarcrush_galaxy_score`, `social_volume_z`, `news_sentiment`.

---

## Appendix E — API contracts

> Pydantic response models → OpenAPI → `packages/contracts-ts`. Shapes (illustrative; the web consumes only generated types):

| Method/route | Request | Response (shape) |
|--------------|---------|------------------|
| `GET /portfolio` | — | `{ equity_curve: Point[], pnl_net: number, allocation: {strategy_id,weight,capital}[], costs: {category,amount}[], live_enabled: bool }` |
| `GET /leaderboard` | `?status&limit` | `{ rows: {version_id, name, sleeve_return_pct, deflated_sharpe, net_pct, pbo, status, lineage}[] }` |
| `GET /strategies/{id}` | — | `{ spec, generated_code, params, trades: Execution[], backtests: Backtest[], notes_md, holdout: {...} }` |
| `GET /costs` | `?from&to` | `{ by_category: {...}[], by_strategy: {...}[], opex_vs_alpha: number }` |
| `POST /console/command` | `{ text }` | `{ parsed_policy, applied: bool, reply_md }` |
| `POST /console/voice` | `audio (multipart)` | `{ transcript, reply_md, tts_audio_url }` |
| `POST /console/upload` | `image (multipart) + note?` | `{ source_id, kind, claims: {text,verdict,evidence}[], veracity, reply_md, recommendation? }` |
| `GET /recommendations` | `?state` | `{ items: Recommendation[] }` |
| `POST /recommendations/{id}/approve` | — | `{ ok: bool, effect }` |
| `POST /toggle/live` | `{ enabled, confirm }` | `{ enabled, promoted: version_id[], caps }` — **gated; off by default** |
| `GET /events` | `?ref_type&ref_id&limit` | `{ events: Event[] }` (audit stream) |

**Rule:** every response is a Pydantic model; no route returns free-form JSON the web has to re-type.

---

## Appendix F — Evolution operators (mutation catalog)

> `evolution/seeder.py` + `evolution/mutator.py`. Each child records its **operator + parent_id** (`strategy_versions.mutation_operator/parent_id`) so the survival model (§12) can learn which operators pay and the graveyard explains deaths. Runs in **two lanes** (config split, default 70% exploit / 30% explore). **Exploit-lane default = single-operator children** (clean causal attribution); the **explore lane is deliberately unrestricted** — multi-operator leaps, crossover, and fresh from-scratch authoring are encouraged there. Single-operator is a *default for attribution, not a law*; the explore budget is guaranteed and never vetoed by the survival model.

**Seed sources:** indicator templates · plain-chat ideas · imported PineScript · mined OSS patterns (RAG) · LLM-authored fresh specs.

**Mutation operators (single-variable unless noted):**
- `add_condition` / `remove_condition` (entry or exit)
- `swap_feature` (replace one `FeatureRef` with a registry sibling)
- `widen_param` / `narrow_param` (adjust a `ParamSpace` range — re-fit, not hardcode)
- `change_horizon` (bar size / hold window)
- `add_catalyst` / `drop_catalyst`
- `change_universe` (tighten/loosen liquidity/ADV or asset set)
- `tighten_risk` / `loosen_risk` (SL/TP/sizing structure)
- `crossover(parent_a, parent_b)` (two-parent; recombine entry/exit blocks — flagged multi-variable)

**Wildcard generators (explore lane):** `random_feature_combo` (sample novel feature sets within the registry), `cross_market_transfer` (port a signal from one asset class to another), `novel_hypothesis` (frontier-model authors a fresh from-scratch spec on a low-prior thesis), `bold_recombination` (multi-block crossover). These intentionally produce high-variance candidates; the cheap screen + scorer sort them out.

**Loop budget:** within each lane the survival model orders which children get the expensive Nautilus validation first; obvious losers die at the vectorbt screen; trial counts accrue for the deflated-Sharpe correction. **The explore lane's budget is reserved up front** so exploitation can't starve discovery.

---

## Appendix G — Config schema & spend governor

> `config/` via **pydantic-settings**. Secrets from **env only** (never in DB/prompts/sandbox). Everything below is config — including **gate thresholds** (so they're tunable by master/human, *never* by the agent).

```
models:        { frontier:[…ids], mid:[…ids], cheap:[…ids], judge:id }
spend:         { daily_cap_usd, alpha_share, floor_usd, per_task_budget:{author,ml,research} }
gates:         { min_trades, max_dd, min_folds_positive_pct, min_regimes,
                 max_pbo, holdout_min_dsharpe }       # App. C — capital valve, not idea choke
evolution:     { explore_fraction:0.30,               # guaranteed wildcard budget
                 exploit_single_operator:true,        # default for attribution (explore lane exempt)
                 diversity_pressure:true,             # keep decorrelated/unusual strategies alive
                 survival_model_vetoes:false }        # model prioritizes compute, never forbids an idea
walk_forward:  { equities:{is_mo,oos_mo,step_mo,min_folds}, crypto:{…}, pm:{…} }
venues:        [ {name, kind, adapter, fee_schedule, constraints, enabled} ]
features:      [ {name, source_module, tier, enabled} ]   # the registry (App. D)
risk:          { global_max_notional, per_strategy_cap, drawdown_killswitch_pct,
                 min_cash_reserve, sandbox_seconds_cap }
live:          { enabled:false, per_strategy_live_cap, global_live_cap, daily_loss_cap }
sandbox:       { provider:e2b|modal, time_cap_s, no_network:true, no_secrets:true }
```

**Spend governor (deterministic, `master`):**
```
trailing_edge = realized_net_edge(last_30d)
research_budget_today = clamp(alpha_share * trailing_edge, floor_usd, daily_cap_usd)
if trailing_edge <= 0:  force cheap tier only, budget = floor_usd
route(task): pick cheapest tier whose quality bar ≥ task difficulty;
             escalate one tier iff model confidence < threshold;
             refuse if budget exhausted (queue to next window)
```
ROI rule made literal: **spend scales with what we earn; throttle to cheap when flat; escalate only on low confidence; never exceed the daily cap.**

---

## Appendix H — Acceptance matrix (proof each track is done)

| Track | Done when… (automated check) |
|-------|------------------------------|
| Spine | seeded Binance backtest writes `backtests`/`executions`/`events`; TS client compiles (`§4` DoD) |
| Data (A) | ≥15 Tier-0 features served **point-in-time** across crypto/equity/PM; a look-ahead probe test fails if any feature peeks |
| Spec/compiler (B) | LLM spec passes `instructor` with **zero literals**, compiles, optimizes IS, runs OOS; a magic-number spec is **rejected** by `static_check` (test) |
| Evolution/scorer (C) | loop autonomously seeds→screens→validates→scores→kills with no human; deflated Sharpe + PBO per version; injected screen↔engine mismatch is caught by reconciliation |
| Lab agent (D) | agent authors a valid spec, runs free-form feature code **in E2B** (no secrets/network — asserted), gets a score it can't alter, distills one Curator-graded skill |
| Master (E) | scheduler runs unattended; a chat command becomes a validated policy delta; test-toggle promotes a paper survivor through the gauntlet |
| Venues (F) | one `StrategySpec` runs in paper on Binance, an equity, **and** a Polymarket market with correct per-venue fees/fills; PM adapter reads live CLOB book in sandbox |
| ML/Risk (G) | survival model orders the validation queue (calibrated); regime classifier gates live-eligibility; a martingale spec is rejected; kill-switch trips a simulated drawdown; a secret never appears in any sandbox/prompt (test) |
| API/UI/Obs/Costs (H) | 4 surfaces render live engine data via generated client; Console sends a validated command + shows a recommendation; voice round-trips; a Langfuse trace appears; a failing judge eval blocks CI; Dashboard shows real opex vs paper alpha |
| Vision/veracity (A+H) | a dropped tweet screenshot is extracted + each claim labeled against real data; a doctored "+400%" trades screenshot is marked **unverifiable**, its number discarded, its setup kept only as a gated hypothesis; a `contradicted` claim vetoes and never trades (tests) |

**V1 ships when every row is green and the whole machine runs autonomously in paper across crypto + equities + prediction markets, live-off, one toggle from real money, with opex < trailing paper edge.**

---

*This plan serves the contract in `docs/VISION.md`. Buy commodities, build the differentiator, and ship only what moves net profit.*
