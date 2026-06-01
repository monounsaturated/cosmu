# Cosmu v2 — Master Plan

> Status: **planning, pre-build.** Owner: read the box below. A fresh agent: read this whole file.
> Last revised 2026-06-01 — gate-first, lean, product-first pass.

---

## For you (the owner) — what to actually do

You don't write code. Your job is 3 steps:

1. **Buy nothing yet.** The first real gate runs on **free data ($0) across three asset classes** — crypto (funding/OI, Fear & Greed), equities (free daily bars + macro), and prediction-market odds — plus free news headlines. A **LunarCrush key** (~$24–40/mo) is *optional*, only to add social data **after** the free gate shows the cross-asset thesis has legs. Real money and paid data vendors come later, gated on a proven survivor.
2. **Hand the build to an agent** — paste this one line into a fresh coding agent:
   > *Build everything in `docs/BUILD_BRIEF.md`. Show me a plan first, then run the tests before saying it's done.*
3. **Run one command** when it's finished — it tells you if aggregating data actually adds edge:
   ```
   python3 -m cosmu.research.gate
   ```
   - **PASS** → the aggregated/standardized data beats price-only *and* buy-and-hold → tell me to plan the next build.
   - **STOP** → it doesn't hold up → you spent days, not months, and the per-source report tells you which data (if any) to keep. That's still a win.

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

Most published *single-market* alt-data edges are decayed or were lookahead artifacts. But the edge most likely to survive at small size is **decorrelation + cross-market signal transfer** (§6, VISION §21) — and that edge *only exists multi-asset*. So we do **not** narrow to one market to feel safe. We go multi-asset on **inputs** from day one and make "multi-asset beats single-asset" a **falsifiable hypothesis the gate tests.** The firm is still scaffolding around a premise that may be zero — so we prove it before building the factory (Phases 1 + 1.5). Phases 2–4 are *conditional* on the gate producing an honest **cross-asset** survivor that beats the single-asset, price-only baseline.

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

### Phase 1.5 — Prove the *cross-asset* aggregation edge *(THE DIFFERENTIATOR GATE — multi-asset, FREE data)*
Phase 1 proves *a* signal exists. Phase 1.5 proves the **two** things the product is actually *for*: that **aggregating complex point-in-time data adds edge over price alone**, *and* that **combining asset classes beats any single one** — the decorrelation/cross-market edge most likely to pay at small size. All on **free data, $0**, with **execution still deferred** (two-plane split, §2). *More data is not automatically good (it is overfitting surface — §6); this phase is where every source and every asset class has to earn its place or get cut.*
- **1.5.1 Free multi-asset sources** behind the existing `AltDataProvider`/market seams, point-in-time, append-only, offline-fixture-backed: crypto **funding + OI + Fear&Greed** (ccxt / alternative.me, funding as a **long filter** — §2); equity **free daily bars + FRED macro**; **prediction-market odds** (Polymarket public API); one **unstructured** source (crypto news headlines, free) for the LLM adapter. *(Free equity data is survivorship-biased — a documented PoC limitation, replaced by Norgate at the execution/live phase; here we test signal **presence**, not deployable capacity.)*
- **1.5.2 The LLM universal adapter, done right:** the unstructured source is standardized to a validated numeric row **once** — frozen, **versioned**, content-hash-**cached**, cheap-tier, hard daily cap — then deterministic code runs forever (§1). Numeric sources **skip the LLM**. The whole gate runs **fully offline via fixtures** (CI has no keys).
- **1.5.3 Cross-asset features**, each with a stated prior: e.g. **prediction-market odds → crypto/equity risk-on/off**, **crypto funding → cross-asset risk appetite**, news-sentiment z-score. Cross-asset signal transfer is the whole point — one market's price as another market's feature.
- **1.5.4 The multi-arm ablation gate** (extend `apps/engine/cosmu/research/gate.py`): four arms on the **same** wall / costs / windows — (1) **single-asset price-only** (baseline), (2) **single-asset + alt-data**, (3) **cross-asset + alt-data** (the multi-asset thesis), (4) **buy-and-hold** — plus **drop-one** per-source *and* per-asset-class contribution. Pre-registered bar (logged before looking): arm (3) must beat (1), (2), **and** (4) net of costs, clear the existing PSR/overfit/min-trades/≥2-regime/drawdown gates, with **attempt budget ≤ 12, every attempt counted in the global trial counter** (the gate itself must not be p-hacked).
- **DoD / decision gate:** cross-asset+alt beats single-asset **and** buy-and-hold → the multi-asset thesis is **proven** (not assumed) → proceed to Phase 2. Only single-asset+alt clears → narrow to that. Neither → **STOP.** The per-axis report tells you exactly **which asset classes and which sources** paid — ambition validated by evidence, for $0.

### Phase 2 — Earn the stack *(only if the Phase 1 / 1.5 gate passed)*
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

## 8. Open items before code
1. **Phase 1 / 1.5 edge gate** — the whole roadmap past Phase 2 is conditional on it. The Phase 0 wall + Phase 1 single-signal gate are **built** (see `IMPLEMENTATION.md`); the active unit is the **Phase 1.5 cross-asset ablation gate** (`docs/BUILD_BRIEF.md`). Run it on free multi-asset data; don't build further until cross-asset+alt beats the single-asset price-only baseline.
2. **Spot vs futures** (§2) — now an *optimization, not a blocker*: multi-asset gives directional/decorrelated expression without it. Decide only if the gate shows crypto specifically needs the short leg.
3. **LunarCrush API key + tier choice** — *optional*, only to add social data after the free gate passes.
4. **`class_gates` schema add** (Phase 4.1 polish) — ask-first DB change, not on the critical path. (Note: an `asset_class_gates` table already exists in the schema.)
