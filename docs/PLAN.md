# Cosmu v2 — Master Plan

> Status: **planning, pre-build.** Owner: read the box below. A fresh agent: read this whole file.
> Last revised 2026-06-01 — gate-first, lean, product-first pass.

---

## For you (the owner) — what to actually do

You don't write code. Your job is 3 steps:

1. **Buy one thing:** a **LunarCrush API key** (lunarcrush.com, cheapest paid tier ~$24–40/mo). That's the only purchase needed to start.
2. **Hand the build to an agent** — paste this one line into a fresh coding agent:
   > *Build everything in `docs/BUILD_BRIEF.md`. Show me a plan first, then run the tests before saying it's done.*
3. **Run one command** when it's finished — it tells you if there's a real edge:
   ```
   python3 -m cosmu.research.gate
   ```
   - **PASS** → there's a signal worth chasing → tell me to plan the next build.
   - **STOP** → the idea doesn't hold up → you spent days, not months. That's still a win.

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

**Does an exploitable edge actually exist on Binance spot, after fees, point-in-time-correct?**

Most published crypto social/alt-data edges are decayed or were lookahead artifacts. The entire firm is scaffolding around a premise that may be zero. So we **prove the premise before building the factory** (Phase 0.5 below). Phases 2–4 are *conditional* on Phase 0.5 producing at least one honest survivor.

### Venue constraint (resolve before ingestion)

Cosmu trades **Binance spot, long-only**. Many funding/OI/mean-reversion hypotheses ("negative funding → 3-day reversion on alts") require shorting or futures and can only be expressed as the long leg here. Either (a) accept a narrower long-only hypothesis space, or (b) widen the venue to futures. **Decide this before building funding/OI ingestion you can't fully trade on.** Until decided, treat funding/OI as *filters on long entries*, not standalone signals.

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

### Phase 2 — Earn the stack *(only if Phase 1 passed)*
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
Railway $10–25 · Vercel $0–20 · Supabase $0–25 · Modal $0–20 · ccxt/funding/OI **$0** · LunarCrush $24–40 · on-chain $0–40 · OpenRouter $20–60 (cap ~$60) · Langfuse/Sentry free · all quant/ML libs **$0 (OSS)**. The run cost is a rounding error against any real edge. The real cost is builder time — which is why Phase 0.5 exists to fail fast.

## 6. Risks & mitigations
| Risk | Mitigation |
|---|---|
| **No edge actually exists** | Phase 0.5 gate: prove one honest survivor before building the factory |
| **Lookahead bias** in alt-data | Point-in-time availability stamps (enforced, not optional) |
| **Scorer lies optimistically** | Pin against known reference values; the wall is judged before it judges anything |
| **Frozen transform silently poisons features** | Stage A validator: leakage/variance/NaN tests; transforms versioned *and* tested |
| **LLM-driven overfitting** | CPCV + PBO + untouched holdout; LLM never scores |
| **Multiple-testing / family-wise error** | Global trial accounting — deflate against *cumulative* hypotheses, not per-spec params |
| **LLM cost runaway** | `LiteLLM` hard cap, cheap-tier default, batch+cache; transforms run code, not LLM |
| **Long-only/venue mismatch** | Resolve spot-vs-futures before funding/OI ingestion; treat funding as long filter until then |
| **Data vendor ToS / rate limits** | Cache aggressively; respect terms; batched ingest |
| **Edge decay** | Defined decay detector + auto-defund; graveyard memory stops re-proposing dead ideas |

## 7. Proprietary vs bought
- **You build (small):** spec schema, gates, tool bus, orchestration glue, UI, the ~100–200-LOC exact scorer math.
- **You buy/operate (everything else):** data APIs, vectorbt/Optuna/LightGBM/Nautilus, Supabase, Modal, OpenRouter, Prefect, Langfuse. Maintenance and bug risk live mostly in someone else's repo.

## 8. Open items before code
1. **Phase 1 edge gate** — the whole roadmap past Phase 2 is conditional on it. Build the Phase 0 wall, then run the gate; don't build further until it passes.
2. **Spot vs futures venue decision** (§2) — gates funding/OI signal design; needed for Phase 1 hand-signals.
3. **LunarCrush API key + tier choice** — needed for Phase 1 data pull.
4. **`class_gates` schema add** (Phase 4.1 polish) — ask-first DB change, not on the critical path.
