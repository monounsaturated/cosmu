> Historical/aspirational. Operational truth = AGENTS.md + docs/IMPLEMENTATION.md (Built sections). Hosting/runtime details here may be stale.

# Cosmu v2 — Master Plan

> Status: **planning, pre-build.** Owner: read the box below. A fresh agent: read this whole file.
> Last revised 2026-06-01 — gate-first, lean, product-first pass.

---

## For you (the owner) — what to actually do

You don't write code. Your job is 3 steps:

1. **Buy nothing yet.** The first real gate runs on **free data ($0) across three asset classes** — crypto (funding/OI, Fear & Greed), equities (free daily bars + macro), and prediction-market odds — plus free news headlines. A **LunarCrush key** (~$24–40/mo) is *optional*, only to add social data **after** the free gate shows the cross-asset thesis has legs. Real money and paid data vendors come later, gated on a proven survivor.
2. **The harness is built** (Phase 0 → 1.6 + the functional Overview-led app — see `docs/IMPLEMENTATION.md`). To *extend* it, hand a coding agent (Claude Code / Cursor) a typed spec for the one feature you want and review the plan + tests before merging. You don't write code.
3. **Run it on real data** — these are bounded, cron-able commands (no 24/7 process):
   ```
   python3 -m cosmu.ingest.run          # one free-data pass into the point-in-time store ($0, no keys)
   python3 -m cosmu.research.loop --ingest   # ingest → run the four-arm cross-asset gate → record the verdict
   python3 -m cosmu.research.gate       # just print the four-arm verdict (PASS / STOP-narrow)
   ```
   - **PASS** → cross-asset + aggregated data beats single-asset *and* buy-and-hold on real data → plan the next build.
   - **STOP-narrow** → it doesn't hold up → days not months spent, and the per-source + per-asset-class report tells you which data/classes (if any) to keep. Still a win.

**Cost to run:** ~$60–130/month, hard-capped. **Live trading stays OFF** until you flip it.
**One optional choice** (default is fine): trade **spot only** (default), or add **futures** later (lets you short; bigger idea space).

Everything below is reference — the strategy, the math, the safety rules. You don't need it to start.

---

## 0. Vision: an autonomous trading *firm* where the LLM is the data brain

The LLM is **not** primarily a "strategy writer." Its job, in order:

1. **Standardize messy social/alt data → quantifiable, ML-ready features** (the universal adapter).
2. **Detect patterns** across those features + the graveyard memory.
3. **Launch strategies** into backtest → paper → (gated) live.

LLMs are excellent at #1 and #2 (structure from messy text, hypothesis generation) and *dangerous* at math, scoring, and moving money. So the LLM lives **at the edges** and the **deterministic core is immovable**. That mapping *is* the firm:

| Firm role | Who does it | Boundary |
|---|---|---|
| **Data engineer** | LLM standardizes LunarCrush/on-chain/news into canonical features | proposes transforms; code executes them |
| **Quant researcher** | LLM detects patterns, writes typed `StrategySpec`s | proposes; never scores |
| **Risk & validation (the wall)** | **Deterministic scorer/gates** | LLM *cannot* touch this |
| **Execution trader** | NautilusTrader, gated | LLM *cannot* fire a live order |
| **Portfolio manager** | `skfolio` capped-Kelly allocator | deterministic |
| **CIO** | **You** — chat + the live toggle | the only human in the money loop |

## 1. Core principle

> **The LLM works at design-time and ingest-time. Deterministic code works in the hot path.**

- The LLM **defines a transform once** (e.g., "galaxy_score → winsorize, z-score over 30d, resample to bar cadence"). That mapping is **frozen, versioned, executed by plain code forever after.** No LLM call per bar, per backtest, or per decision.
- For genuinely unstructured text (news, posts), the LLM runs **at ingest, batched, cheap-tier, cached** — emitting a validated numeric row. Never in the trading or scoring path.

This is what buys an "AI trading firm" for ~$60/mo instead of $6,000: you pay the LLM to *write the adapter and the hypothesis*, not to think on every tick. It keeps the scorer/money partition mathematically clean and every backtest reproducible.

### Lean & product-first

- **The gate before the factory.** Build the thinnest thing that proves an edge; defer all infrastructure until an edge earns it. Most of the managed stack (Prefect, Modal, pgvector, Langfuse) is **deferred, not provisioned** — adopt each only when a concrete pain demands it.
- **Every phase ships a usable slice.** No infra for its own sake. The "product" is the working money loop plus the minimal surface you steer it from — not a polished SaaS.
- **One ruler, reused.** The Phase 0 wall is the same scorer used by the spike, the loop, and live eligibility. Build it once, trust it everywhere.

### Keep the codebase lean (decluttering)

- **Delete what you replace.** Every swap (real scorer, `pandas-ta`, `vectorbt`) removes the hand-rolled code it supersedes — no surrogate left sitting beside the real thing.
- **One-time hygiene pass (cheap — do alongside Phase 0):**
  - Stop tracking build artifacts: add `__pycache__/` + `*.pyc` to `.gitignore` and `git rm --cached` the tracked ones.
  - `TradingAgents-main/` (~5 MB) is prior-art reference, not product code — untrack it; ingest into RAG in Phase 3, or move under the gitignored `.external/`.
  - Prune stale docs/prose (e.g. the AGENTS.md "Legacy v1 / `apps/api`" section — `apps/` now holds only `engine` + `web`).
- **No speculative modules.** Files/dirs appear when a phase needs them, not before.

### Two non-negotiable correctness rules, from day one

1. **Point-in-time integrity.** Every alt-data row is stamped with its **availability time**, not its event time. Backtests read "as you'd have known it then." This is the #1 way alt-data backtests lie.
2. **Transform versioning.** A spec pins the feature-transform versions it used, so a survivor is re-runnable byte-for-byte. **A frozen transform is a code dependency: versioned *and* tested, not just versioned** — the Stage A validator must reject transforms that leak future info, explode variance, or NaN at boundaries.

## 2. The strategic question that gates everything

**Does an exploitable edge exist *across asset classes* — crypto + equities + prediction markets — after fees, point-in-time-correct? And does *combining* them beat any single one?**

Most published *single-market* alt-data edges are decayed or were lookahead artifacts. But the edge most likely to survive at small size is **decorrelation + cross-market signal transfer** (§6, VISION §21) — and that edge *only exists multi-asset*. So we do **not** narrow to one market to feel safe. We go multi-asset on **inputs** from day one and make "multi-asset beats single-asset" a **falsifiable hypothesis the gate tests** (Phase 1.6). The firm is still scaffolding around a premise that may be zero — so we prove it before building the factory (Phases 1 → 1.6). Phases 2–4 are *conditional* on the gate producing an honest **cross-asset** survivor that beats the single-asset, price-only baseline.

### The two-plane split (how multi-asset stays cheap *and* disciplined)

The objection to "multi-asset first" is cost and sprawl — paid vendors and an execution adapter per venue. We dissolve it by splitting the system into two planes that scale independently:

- **Data & signal plane — multi-asset from day one, ~$0.** Every asset class's *features* are ingested point-in-time from **free** sources: crypto (ccxt funding/OI/flows, Fear&Greed), equities (free daily bars + FRED/EDGAR/COT macro), **prediction-market odds** (Polymarket public API). Cross-asset signal transfer is first-class. The **same wall scores every class on the same ruler** — and the foundation already supports this: the scorer has per-class walk-forward windows, and the schema already ships `venues.kind ∈ crypto|equity|prediction` + an `asset_class_gates` table. **No execution venue is needed to prove edge.**
- **Execution plane — one venue now, more gated to live.** Paper/backtest fills are **simulated for every class** by the engine we already have. *Real* execution adapters (IBKR, Polymarket live wallet) and *paid* survivorship-free vendors (Norgate, Sharadar) are built **only when you flip live on a proven cross-asset survivor** — the expensive, irreversible spend is deferred until an edge pays for it.

**The reconciliation:** be ambitious on *inputs and evaluation* (multi-asset, free, now); stay lean on *money and irreversible spend* (one execution venue, paid vendors deferred). Ambition where it's cheap; discipline where it's expensive.

### Directional expression (multi-asset also relaxes the long-only problem)

Going multi-asset partly *solves* the crypto long-only-spot handicap: **prediction markets express "down" by buying the opposite side**, equities carry a natural long drift, and cross-asset positions hedge each other. So you get directional and decorrelated expression **without needing crypto futures.** Crypto stays **spot long-only** for now (funding/OI as long-entry filters); the spot-vs-futures choice becomes an *optimization*, not a *blocker*.

## 3. Architecture (target state)

```
        YOUR CODE (small, agentic — the moat)
   spec schema · gate config · tool bus · orchestration · UI
                          │
 ┌──── LLM at the edges ──┴───────────── deterministic core (the wall) ───┐
 │  ingest: text→features │  scorer (exact deflated Sharpe/PBO/CPCV)       │
 │  design: transforms +  │  gates · risk gauntlet · allocator (skfolio)   │
 │  hypotheses (instructor)│  execution (Nautilus, gated)                  │
 └────────────────────────┴───────────────────────────────────────────────┘
   DATA APIs                 OSS ENGINES              MANAGED CLOUD
   ccxt · LunarCrush ·       vectorbt · Optuna ·      Supabase(PG+pgvector)
   Glassnode/CryptoQuant ·   LightGBM · pandas-ta ·   Modal · OpenRouter ·
   funding/OI (free)         Nautilus                 Railway/Vercel · Prefect
                                                      Langfuse · Sentry
```
*Target state. Most cloud/OSS services are **deferred until a phase earns them** (see §4) — provision nothing speculatively.*

## 4. Phased roadmap *(gate-first: build the ruler, prove an edge, then earn the rest)*

### Phase 0 — The minimal honest wall *(do first, days not weeks, ~$0, no LLM)*
The ruler everything is measured by. Build **only** enough to trust a yes/no — nothing more.
- **0.1** Replace the invented penalty with **exact deflated Sharpe + PBO + purged/embargoed walk-forward** (López de Prado formulas, ~100–200 LOC — *not* commercial `mlfinlab`).
- **0.2 Global trial accounting.** Deflate against the **cumulative hypotheses ever tested**, not the per-spec `param_space` size used today. With an LLM generating unlimited ideas, family-wise error is *the* overfit risk.
- **0.3** Honest fees + slippage on the **existing** Python backtest. **No vectorbt, Polars/Parquet, Optuna, or full CPCV yet** — those are speed/scale, not correctness, and are premature before an edge exists.
- **DoD:** scorer pinned against **known reference values** (worked examples or a hand-computable synthetic), *not just* "PBO rises with trials."

### Phase 1 — Prove an edge exists *(THE GATE — stop-or-go)*
Cheapest path to truth. **No LLM, no registry, no pipeline, no UI.** Manual data pull, hand-built signals.
- **1.1** Hand-pull ~1–2 yrs LunarCrush + Binance bars (manual, cached), stamped **point-in-time**.
- **1.2** Hand-build 1–2 signals (galaxy_score z-score; funding extreme as a *long filter* — see §2 venue constraint) on a few liquid pairs.
- **1.3** Run through the **Phase 0 wall** vs BTC/ETH buy-and-hold, after realistic costs.
- **DoD / decision gate:** ≥1 signal clears with an honest deflated Sharpe + survivable PBO. **Nothing clears → stop. That's a real, valuable result.** Clears → proceed.
- *Product slice:* a one-screen result view (signal vs buy-and-hold) is the thinnest useful surface — optional, but it's the first thing you'd actually look at.

### Phase 1.5 — Prove the *aggregation* edge, single-asset *(THE DIFFERENTIATOR GATE — BUILT ✓)*
**Done and green on the fixture** (see `IMPLEMENTATION.md`): three free crypto sources (funding as a long filter, Fear&Greed, free news) behind the alt-data seam; the LLM universal adapter (`ingest/standardize.py`, frozen/versioned/cached, never in any backtest/scoring path); and a **three-arm ablation** (`research/gate.py` `evaluate_ablation`) — **price-only vs + alt-data vs buy-and-hold** — with a drop-one per-source report, CSCV/PBO, the pre-registered bar, and every arm counted in the global trial ledger. On the seeded fixture: **PASS, alt > price-only > buy-and-hold, news is the paying source.** *(The real-data run still needs the live free pulls wired — but the harness and the verdict logic are proven.)*

### Phase 1.6 — The cross-asset extension *(ACTIVE — multi-asset, still FREE data)*
Phase 1.5 proved *aggregating data beats price* on one asset class. Phase 1.6 proves the **second, bigger** half of the thesis: that **combining asset classes beats any single one** — the decorrelation/cross-market edge most likely to pay at small size (§6, VISION §21). Built on the proven 1.5 harness, on **free data, $0**, with **execution still deferred** (two-plane split, §2). *More data/assets is not automatically good (it is overfitting surface — §6); this is where each asset class earns its place or gets cut.*
- **1.6.1 Add two free asset classes** to the existing seams, point-in-time, append-only, fixture-backed: equity **free daily bars + FRED macro**, and **prediction-market odds** (Polymarket public API). *(Free equity data is survivorship-biased — a documented PoC limitation, replaced by Norgate at the execution/live phase; here we test signal **presence**, not deployable capacity.)*
- **1.6.2 Cross-asset features**, each with a stated prior: e.g. **prediction-market odds → crypto/equity risk-on/off**, **crypto funding → cross-asset risk appetite**. Cross-asset signal transfer is the whole point — one market's price as another market's feature.
- **1.6.3 Add a fourth arm to the ablation** (extend `evaluate_ablation`): (1) single-asset price-only · (2) single-asset + alt-data *(both already built)* · **(3) cross-asset + alt-data (the new thesis)** · (4) buy-and-hold. Add **per-asset-class** drop-one alongside the existing per-source one. Same pre-registered bar, same global trial counter, **attempt budget ≤ 12**.
- **DoD / decision gate:** cross-asset+alt beats single-asset **and** buy-and-hold → the multi-asset thesis is **proven, not assumed** → proceed to Phase 2 with all three classes. Only single-asset+alt clears → keep it single-asset for now. Neither → **STOP.** The per-axis report tells you exactly **which asset classes and which sources** paid — ambition validated by evidence, for $0.

### Phase 2 — Earn the stack *(only if the Phase 1 → 1.6 gate passed)*
Infrastructure is now justified by a real edge. Add each piece **only as volume/pain demands it.**
- **2.1** Automate ingestion with a **scheduled job** (adopt Prefect only when DAG complexity is real) → **Supabase Postgres**, point-in-time.
- **2.2** **vectorbt** (throughput), **Optuna** (param fitting, kills the midpoint stand-in), **CPCV** (upgrade the wall now that there are many strategies to validate), Polars/Parquet.
- **DoD:** thousands of candidates/run, reproducible, on real point-in-time data.

### Phase 3 — LLM data factory + autonomous loop *(conditional)*
- **3.1** Stage A (schema standardization) + Stage B (text→numeric, **pre-filtered before spending tokens**) → versioned, *tested* features (leakage/variance/NaN). Wire **OpenRouter + `instructor` + `LiteLLM`**, hard cost cap (`daily_cap_usd` ~$2–3, cheap-tier default).
- **3.2** Stage C (pattern detection → typed spec) + Stage D (`backtest_request` → scorer → paper). Tool bus **read/propose-only**.
- **3.3** **LightGBM** survival model + regime classifier as *tools* (scorer still judges); **pgvector graveyard RAG**; **Langfuse** tracing + CI eval gates. Failed live scores → new eval cases.
- **DoD:** end-to-end cohort with zero human authoring, honest survivors, agents cannot escalate to money.

### Phase 4 — Operator product + small-real live *(the stated goal)*
Product-first but **lean** — the surface you actually use, nothing gold-plated.
- **4.1** Minimal operator UI: real equity chart + the **2-click live arm modal** on top of the existing settings/gate. Full **`sidebar-07`** (collapsible icon rail), **tri-state toggles** (parent "—", children keep their tick when parent off — needs a small **`class_gates` schema add → ask-first**), ⌘K palette, per-sleeve charts are **polish — ship after live works.**
- **4.2** **NautilusTrader** paper→live parity, **Binance spot only**, OFF by default. Arm modal shows a literal "what will trade" table; per-strategy + global + daily-loss caps; **auto-defund** on rolling deflated-Sharpe drop *or* live-vs-paper divergence. Eligibility = **4+ weeks positive paper net edge**.
- **DoD:** $1k–$10k live on top survivors, audited, auto-disarming — the proof.

## 5. Budget (Tier 1 "prove it": ~$60–130/mo, hard-capped)
Railway $10–25 · Vercel $0–20 · Supabase $0–25 · Modal $0–20 · ccxt/funding/OI **$0** · LunarCrush $24–40 · on-chain $0–40 · OpenRouter $20–60 (cap ~$60) · Langfuse/Sentry free · all quant/ML libs **$0 (OSS)**. The run cost is a rounding error against any real edge. The real cost is builder time — which is why the Phase 1 / 1.5 gate exists to fail fast.

## 6. Risks & mitigations
| Risk | Mitigation |
|---|---|
| **No edge actually exists** | Phase 1 gate: prove one honest survivor before building the factory |
| **Aggregating data adds noise, not edge** (the product's core bet) | Phase 1.5 ablation: the alt-data arm must beat **price-only** on the same wall; drop-one marginal contribution keeps only sources that actually pay, cuts the rest |
| **Lookahead bias** in alt-data | Point-in-time availability stamps (enforced, not optional) |
| **Scorer lies optimistically** | Pin against known reference values; the wall is judged before it judges anything |
| **Frozen transform silently poisons features** | Stage A validator: leakage/variance/NaN tests; transforms versioned *and* tested |
| **LLM-driven overfitting** | CPCV + PBO + untouched holdout; LLM never scores |
| **Multiple-testing / family-wise error** | Global trial accounting — deflate against *cumulative* hypotheses, not per-spec params |
| **LLM cost runaway** | `LiteLLM` hard cap, cheap-tier default, batch+cache; transforms run code, not LLM |
| **Long-only/venue mismatch** | **Multi-asset relaxes it** (§2): prediction-market opposite-side + equity drift + cross-asset hedges give directional/decorrelated expression without crypto futures; crypto stays spot long-only as an *optimization*, not a blocker |
| **Multi-asset = cost & sprawl** | **Two-plane split** (§2): multi-asset *data/signals* are free and built now; multi-asset *execution* + paid vendors are deferred until a survivor earns them |
| **Data vendor ToS / rate limits** | Cache aggressively; respect terms; batched ingest |
| **Edge decay** | Defined decay detector + auto-defund; graveyard memory stops re-proposing dead ideas |

## 7. Proprietary vs bought
- **You build (small):** spec schema, gates, tool bus, orchestration glue, UI, the ~100–200-LOC exact scorer math.
- **You buy/operate (everything else):** data APIs, vectorbt/Optuna/LightGBM/Nautilus, Supabase, Modal, OpenRouter, Prefect, Langfuse. Maintenance and bug risk live mostly in someone else's repo.

### 7a. LLM, data & coding-agent policy (cost-smart, maintainable)
- **One LLM gateway = OpenRouter** (one key → every model: Qwen, DeepSeek, Hermes, Grok, Claude, GPT). Swap models by **config, not code**. **Default to the cheapest/free tier** (DeepSeek/Qwen/Hermes) for the 24/7 loop; escalate to a smart model only on low confidence, under the daily cap.
- **Claude Code / Cursor (flat subscription) is a first-class tier.** The rule: **24/7 + cheap + deterministic → cheap/free API; heavy + occasional + judgment → Claude Code on the sub** (batch authoring, deep research, the data-factory passes, migrations, refactors). Don't burn per-token API on big occasional jobs the subscription already covers.
- **The app is steerable by any coding agent.** It exposes typed seams — `StrategySpec`, `strategies/inbox/`, **skills in `.claude/skills/`**, the engine API + CLIs — so a coding agent *drives* the heavy LLM work directly. Keep a short **`docs/CODING_AGENT.md`** listing which tasks are coding-agent-driven vs automatic. New complex/rare capability → a **skill + doc**, not a new app page.
- **Data = standardized + pluggable + big-data/ML-ready.** All sources register through the one `DataSourceRegistry` (a new source = config + a small module, never a rewrite) and land in a **columnar, point-in-time feature store** (parquet/Polars off the control plane). **Buy great data when cheap, free otherwise.** Centralizing here is what keeps large data + ML maintainable.
- **Product simplicity:** few surfaces (~4–6), easy customization (config + tooltips), no section sprawl. The current build drifted to ~8 routes — collapse Costs into Paper/Overview, keep Steer as the one Console.

## 8. Open items before code
1. **Phase 1 → 1.6 edge gate** — the whole roadmap past Phase 2 is conditional on it. Phase 0 wall, Phase 1 single-signal gate, Phase 1.5 single-asset aggregation gate, and **Phase 1.6 the cross-asset extension are all built** (see `IMPLEMENTATION.md`), PASS on the fixture. The remaining step is **running the gate on real free multi-asset data** (`python3 -m cosmu.research.loop --ingest`); don't build the factory until cross-asset+alt beats the single-asset price-only baseline on real data.
2. **Spot vs futures** (§2) — now an *optimization, not a blocker*: multi-asset gives directional/decorrelated expression without it. Decide only if the gate shows crypto specifically needs the short leg.
3. **LunarCrush API key + tier choice** — *optional*, only to add social data after the free gate passes.
4. **`class_gates` schema add** (Phase 4.1 polish) — ask-first DB change, not on the critical path. (Note: an `asset_class_gates` table already exists in the schema.)

## 9. Data sources (impact-ranked) + stack & pricing tiers

> Principle (aligned with §1): **free data first, gate before factory.** Wire the cheap high-impact sources, run the *real* gate, and only build the big agentic/ML/indexing machine if real data beats price-only. Don't build the factory on a synthetic PASS.

### Data sources, ranked by impact-per-cost (crypto, free-first)
| # | Source | Cost | Edge prior | Status |
|---|--------|------|-----------|--------|
| 1 | **Price OHLCV** (Binance/ccxt) | free | baseline the rest must beat | wired |
| 2 | **Funding rate + Open Interest** (Binance fapi) | free | crowded-leverage / positioning — the classic crypto edge | provider wired |
| 3 | **Fear & Greed** (alternative.me) | free | crowd-sentiment regime, mean-reverts | wired |
| 4 | **Liquidations** (Coinglass free) | free | cascade/exhaustion timing | next |
| 5 | **News headlines** (CryptoPanic free / RSS / GDELT) | free | narrative shift precedes continuation; the LLM-as-adapter source | provider wired |
| 6 | **On-chain flows** (Glassnode/CryptoQuant free→paid, Dune free) | freemium | exchange in/outflows, whale moves | later |
| 7 | **Social** (LunarCrush) | ~$24–40/mo | social momentum; decays fast | optional, post-gate |
| 8 | **Macro** (FRED: DXY, 2s10s) | free | risk regime | later/equities |

**Acquisition = APIs + scheduled pulls, not scraping.** Where an API exists, use it (ToS-safe); scraping only via legal free feeds (RSS/GDELT). All pulls land **append-only, point-in-time** in the store. The **LLM runs only at ingest** to standardize unstructured text → numeric (content-hash cached, free/cheap model), never in the hot path.

### Agentic & retrieval (low-token, cheap)
- **MCP = the agent's *tool* interface** (web search, RAG read, backtest_request) — not the ingestion pipeline (plain code is cheaper for scheduled pulls).
- **Free models for ingest + breadth** (OpenRouter free Llama/Qwen/DeepSeek tiers), frontier only for novel hypotheses, all behind **LiteLLM with a hard cap**.
- **Low-token retrieval:** structured Postgres + a compact one-line **INDEX** + **pgvector** over graveyard/research notes. The LLM reads the INDEX then one record. **Recycle:** features computed once and reused across strategies; the **graveyard is long-term memory** so dead ideas aren't re-proposed.
- **Pine scripts / NL trading ideas** already enter via `translate_pine` + `lab/author` → the same typed-spec funnel; the LLM authors structure only, the wall judges.

### Stack & pricing — 3 tiers (smartest moves)
**Don't self-host LLMs or rent always-on GPU.** Always-on = cheap CPU; LLM = OpenRouter; GPU = pay-per-use bursts only.

| Tier | When | Always-on | DB | Compute burst | LLM | Paid data | ~ $/mo |
|------|------|-----------|----|--------------|----|-----------|--------|
| **1 — Prove it** | now (free gate) | Railway hobby **or** Hetzner CX22 / Scaleway; Vercel free | Supabase free (PG+pgvector) | none (CPU backtests) | OpenRouter **free** models, cap ~$10 | none | **$5–35** |
| **2 — Edge found** | after real gate PASS | Hetzner CX32 / Railway pro | Supabase Pro ($25) | Modal pay-per-use ($0–50) | cheap-tier + rare frontier, cap ~$30–80 | LunarCrush ($24–40) + on-chain basic (~$30) | **$60–150** |
| **3 — Compounding/live** | sustained paper edge | dedicated Hetzner AX (~$50) | Supabase Pro + add-ons | RunPod/Modal GPU bursts ($50–200) | frontier for novel, cap $100–250 | + Tardis/Databento/paid on-chain | **$250–600** |

**Recommended lean stack:** Railway (DX) or Hetzner (cost) always-on · Supabase (Postgres+pgvector) · Modal (bursts) · OpenRouter+LiteLLM (LLM) · Vercel (web). Render is fine but pricier than Hetzner for always-on; RunPod best for cheap GPU bursts.

### Next unit — real data + central DB (ask-first: infra/schema)
1. **Supabase Postgres + pgvector** replaces SQLite + JSONL caches → the central, indexed store the vision needs (feature store · append-only snapshots · graveyard RAG · INDEX).
2. **Scheduled free-data worker** pulls sources #1–5 live, point-in-time → run `evaluate_ablation` on **real** data → a true PASS/STOP.
3. Only on real PASS: build the holistic agentic/ML/indexing layer (Phase 2+).

## 10. Buy-vs-build, ML-via-LLM, and the agentic app (plan — 2026)

> Principle: **coordinate, don't build.** Proprietary code stays tiny (spec schema · the exact stats wall · glue · UI). Everything dangerous or heavy is a maintained dependency we *operate*. This keeps the app from breaking and us off maintenance.

### Dashboard decision
Do **not** `shadcn add dashboard-01` (clashes with our Tailwind v4 design + ships placeholder data). **Adopt its two best pieces into our themed dashboard:** Recharts interactive chart + TanStack DataTable, fed by real data. The real fix is replacing synthetic data, not the layout.

### "Use LLMs to do ML" — three meanings, all *buyable*
1. **LLM as feature engineer / data formatter** — built (`ingest/standardize.py`). The LLM turns messy text → numeric features at ingest, frozen+cached.
2. **Agent writes & runs ML code** — buy a **sandbox** (E2B or Modal), LLM via OpenRouter authors scikit/LightGBM code, it runs sandboxed, **the deterministic scorer judges**. Never build a sandbox.
3. **Pretrained models you *call*** — tabular **AutoML** (AutoGluon / LightGBM, free, CPU) for the survival model; **time-series foundation models** (Chronos / TimesFM open-weights, or **Nixtla TimeGPT** API) as a *feature/signal source* — call them, don't train. The scorer still owns success.

### Buy-vs-build matrix (every aspect)
| Capability | Buy / OSS | Cost | vs building | Pick |
|---|---|---|---|---|
| Fast backtest screen | **vectorbt** | free | weeks → hours | adopt (Phase 2) |
| Exec + paper/live parity | **NautilusTrader** | free | months saved | adopt (Phase 3) |
| Stats wall (DSR/PBO/CPCV) | papers, ~150 LOC | free | exact + tiny — the *one* justified build | **built ✓** |
| Param optimization | **Optuna** | free | adopt (Phase 2) |
| Tabular ML / survival model | **LightGBM / AutoGluon** | free (CPU) | don't hand-build models | adopt (Phase 3) as a tool |
| Managed AutoML (optional) | Vertex / SageMaker Autopilot | ~$ per train | skip unless needed |
| Time-series foundation model | **Chronos / TimesFM** (OSS) · TimeGPT (API) | free / API | call, don't train | adopt as feature (Phase 3) |
| Agent code sandbox | **E2B** or **Modal** | pay-per-use $0–50 | never build a sandbox | buy |
| LLM inference | **OpenRouter + LiteLLM** | free models → capped | buy ✓ |
| Agent orchestration | **Pydantic AI / LangGraph** | free | adopt (Phase 3) |
| Tools (web/news search) | **Exa / Tavily** (MCP) | free tiers | adopt |
| RAG / vector | **pgvector** (Supabase) | free → $25 | schema ready ✓ |
| Database | **Supabase** (PG+pgvector) | free → $25 | chosen ✓ |
| Data: price/funding/F&G/news | ccxt · REST · GDELT/RSS | **free** | wired ✓ |
| Data: social | LunarCrush | $24–40 | optional, post-gate |
| Data: on-chain | Glassnode/CryptoQuant | $0–100 | later |
| Charts / tables | **Recharts / Tremor · TanStack** | free | adopt (dashboard) |
| Tracing + evals | **Langfuse** | free tier | adopt (Phase 2/3) |
| Hosting + bursts | **Railway + Modal** | $5–50 | chosen ✓ |

### Agentic-first *app* (frontend + Claude Code, one tool layer)
- **One tool layer, two drivers.** The engine exposes typed read/research/**propose-only** tools (run gate, query population, draft strategy, propose venue). Wrap them as an **MCP server** so **Claude Code/Cursor drive the same app** for heavy/messy tasks — while the in-app agent uses the identical tools. **The deterministic wall + money are out of reach in every path.**
- **Frontend = routine ops:** monitor (real charts), toggles, run gate, browse strategies, 2-click live arm.
- **Claude Code = heavy/structural** (rare, messy): **add a venue** (skill scaffolds adapter + catalog entry + tests), **author a complex strategy** (skill: NL ↔ typed `StrategySpec` → farm), **deep-ML experiment** (agent writes code → sandbox → scorer judges). Don't build bespoke UI for rare heavy tasks.
- **NL-explained specs:** every strategy/feature carries a plain-language rationale + prior the LLM reads/writes; the wall judges regardless.

### Modular yet clean (no DB clutter)
- **Adapter pattern behind typed contracts** — swapping vectorbt↔Nautilus or LightGBM↔AutoGluon is one file. 
- **Truth = normalized Postgres rows + one event ledger**; markdown/INDEX are generated views; **pgvector** only for unstructured (graveyard/notes). No blob dumping; features computed once and reused (recycle).

### Sequencing (coherence — don't build the factory early)
**Real data + Supabase → real gate (PASS/STOP) → only on PASS: ML/FM tools + RAG + agentic loop + dashboard real-charts → live.** Lucrativeness is unproven until the real gate passes; these tools raise the odds of finding edge but the wall still decides. Stay disciplined.
