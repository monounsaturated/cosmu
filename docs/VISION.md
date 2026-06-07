> Historical/aspirational. Operational truth = AGENTS.md + docs/IMPLEMENTATION.md (Built sections). Hosting/runtime details here may be stale.

# Cosmu v2 — Product Memo & Build Plan

> **One line:** an autonomous, multi-venue quant **money machine**. A *deterministic master* runs a *population of self-improving, LLM-authored swing strategies*, backtested walk-forward with real per-venue fees, **forward-testing each survivor on its own standalone SIM track 24/7 with live trading OFF by default** — flip one toggle and a qualifying strategy is launched LIVE manually with dedicated capital. It competes on **returns, not speed**, and is steered by **plain chat (text or voice)**.

> **The one metric:** realized risk-adjusted profit, net of every cost (fees, slippage, funding, LLM/API spend, hosting). Everything here is justified only if it moves that number.

**How to read this (humans and agents):** sections are self-contained. Agents read `§0` + the `INDEX` table, then jump to the one section they need. Don't read the whole file to answer one question.

| # | Section | Read it when… |
|---|---------|---------------|
| 0 | North star & principles | you need the non-negotiables |
| 1 | What the user experiences | designing/critiquing UX or the chat/voice control surface |
| 2 | Economics & ROI model | making any spend/scale/business decision |
| 3 | System architecture (the spine) | touching control flow, money, or modules |
| 4 | The autonomous lab agent + model router | authoring, ML, self-improvement, model calls |
| 5 | The evolution loop & live toggle | how strategies are born/scored/killed/promoted |
| 6 | Knowledge, memory, ingestion & RAG | reading/writing notes, indexes, audit, inputs |
| 7 | Venues, fees, realistic forward-test, arbitrage | anything market-facing |
| 8 | ML | the agent-written + tabular models |
| 9 | Risk & safety | anything that can lose money |
| 10 | Data model | schema/queries |
| 11 | UX/UI | building pages |
| 12 | Infra, vendors & cost accounting | deploy/hosting/buy decisions |
| 13 | Codebase conventions | writing code |
| 14 | Milestones | sequencing work |
| 15 | Human checklist | what the user must do |
| 16 | Honest risks | sanity-checking ambition |
| 17 | Weak links we're closing | de-risking; why v1 was slop |

---

## 0. North star & principles

- **Earn, don't pinch.** ROI mindset: optimize for *net profit and compounding*, not for minimizing spend. Spend aggressively on what raises expected return; cut anything that doesn't. Every cost is an investment measured against yield.
- **Profit is the only score.** Everything secondary must defend itself by moving net profit.
- **LLM proposes, deterministic disposes.** LLMs author/mutate/analyze/do-ML. A deterministic master owns money, scheduling, allocation, caps, and the live gate. No LLM ever fires a live order directly.
- **Two things the AI never touches: the scorer and the money.** The fitness metric (walk-forward OOS + untouched holdout) and capital are deterministic and out of the agent's reach. Take those away and the agent can be *as autonomous and creative as it wants* — including writing and running its own ML — because it can't grade its own homework or lose real capital on a hallucination. This single rule is what makes "fully autonomous" safe.
- **Explore wide, gate hard.** The rigor (deflated Sharpe, holdout, multiple-testing correction, "kill 95%+") is a **valve on *capital*, not a choke on *ideas*.** Generation is deliberately cheap, wild, and creative — exotic hypotheses, weird feature combos, cross-market long-shots — and a **fixed exploration budget** is spent on high-variance, low-prior "wildcards," not just mutations of current winners. **Luck is allowed to run:** a lucky-looking strategy isn't pre-judged or forbidden — it's funded on its own *SIM track* and then separated from real edge over time by the holdout + weeks of forward-test. The gates decide what gets *money*, never what gets *tried*. The constraints (no hardcoded numbers, single-variable-by-default) are **enablers**: they let the data find numbers humans wouldn't guess, and keep attribution clean — they are not a creativity tax. Guard against **monoculture**: diversity/decorrelation has option value, so keep weird, slightly-lower-ranked bets alive.
- **Live OFF by default.** The machine forward-tests strategies in realistic SIM 24/7, tracked *as if live*. Flipping the global toggle launches a qualifying strategy LIVE manually with dedicated capital, under hard caps. SIM (forward-test) and LIVE are the same code path, the same entities — never a separate system.
- **Buy commodities, build the differentiator.** Buy/borrow managed services for undifferentiated plumbing (model routing, sandboxes, voice, search). Keep tight, hand-written control of the core loop and its deterministic gates — that loop *is* our edge, and it's the thing that keeps us out of "slop." When unsure a buy is worth it, flag the stakes (§12).
- **Agentic-first, token-frugal.** Structured data is the source of truth; markdown + an INDEX are the cheap human/LLM-readable views; RAG retrieves only what's relevant.
- **Audit everything.** Every decision, fill, model call, and dollar is a structured, queryable record.

---

## 1. What the user experiences (the product)

A small, beautiful app with **a few surfaces** (lean — collapse toward ~4–6, never 10; if a page doesn't help you *decide* or *earn*, it isn't a page). You mostly watch and occasionally chat; the machine runs strategies and proactively pings you. **Complex, rare, or heavy operations are NOT new app pages** — they live in Claude Code + `docs/` (author/migrate/research via a coding agent). The app stays a clean *monitoring + steering* surface; customization is config, not clutter.

1. **Dashboard** — the aggregate read-out (Σ of all standalone tracks, *not* a pooled wallet you trade from): net equity curve (SIM + live), **P&L net of all costs**, per-track funding across strategies/venues, a compact **Costs card** (infra · hosting · data/APIs · LLM/sandbox, drill-down per-category & per-strategy), opex-vs-profit gauge, and the **global live toggle (off by default)**.
2. **Leaderboard** — every strategy-version on its **own standalone track** (default **$1,000**, `sim_track_capital`), ranked by **risk-adjusted %** (out-of-sample), with lineage, status (alive / forward-test / live / killed), and why.
3. **Strategy detail** — backtest & SIM (forward-test) equity, trade list, the LLM-authored code, the agent's notes/post-mortem, fee/slippage breakdown, OOS vs holdout.
4. **Console (chat + voice + vision + recommendations)** — the control surface. Type, **speak** (STT in, TTS out), or **drop an image** — a screenshot of trades, a tweet/post, a chart. A vision model extracts it, a **veracity gate** verifies the claims against real data (§6), and the result feeds research / monitoring / hypotheses (never a blind trade). The master parses everything to *validated config changes* and **posts recommendations + approval asks on its own**.

**Steer in natural language** (all deterministically validated before applying):
- "Be more aggressive on breakout strategies, cut anything with >15% drawdown." → risk/allocation policy.
- "Here's an idea: fade overnight gaps on Nasdaq large-caps." → becomes a real, backtested strategy.
- "Learn from this YouTube video / this PineScript." → ingested, mined for testable rules.
- *(image)* "This tweet says BTC ETF inflows hit a record — true? worth a trade?" → vision-extracts the claim, **verifies it against real data**, and either seeds a hypothesis/monitor or vetoes it.
- *(image)* "Here's a screenshot of someone's trades — replicate the setup." → extracts the apparent strategy; flags the P&L as **unverifiable** (we can't see their broker); turns the *structure* into a real, gated backtest, not a belief.
- "Why did strat #142 die?" → reads its audit trail + notes, answers in plain language (or voice).

**Proactive recommendations** (Console inbox):
- "3 strategies cleared OOS + holdout and survived 6 weeks of forward-test (SIM). If you flip live on, each launches at $X dedicated cap — want me to?"
- "Crypto regime shifted to high-vol; I de-risked momentum books and flagged it."
- "LLM/API spend is 40% of trailing strategy yield — I throttled to the cheap tier."

You are needed only to **move real money** (flip live, raise caps). Everything else runs unattended.

---

## 2. Economics & ROI model (business POV)

Treat it as a tiny fund. Two ledgers: **opex** (cost to run) and **alpha** (what it earns). Job: alpha ≫ opex, then **compound**.

**Monthly opex (forward-test / R&D phase, tunable):**

| Item | Est. / mo | Notes |
|------|-----------|-------|
| Compute (Railway worker) | ~$25 + usage | continuous research loop |
| DB (Supabase Pro, pgvector) | ~$25 | structured store + RAG |
| Frontend (Vercel) | $0–20 | |
| LLM router (OpenRouter) | $50–400 | **hard daily cap**; mostly cheap tier |
| Agent sandbox / ML (E2B or Modal) | $10–150 | usage-priced; scales with agent effort |
| Voice (Deepgram/ElevenLabs) | $5–30 | STT/TTS |
| Research APIs (Exa/Tavily, news, YouTube) | $20–100 | per-query; cap-able |
| ML burst (RunPod/Modal, optional) | $0–50 | periodic tabular training |
| **Total** | **~$135–800** | dial up when alpha justifies it |

**ROI rules:**
- **Research/LLM/sandbox spend is R&D, capped as a % of trailing realized edge.** Not earning → throttle to cheap tier automatically. Earning → spend more to find more.
- **Standalone funding.** Each survivor runs on its own standalone SIM track (default **$1,000**, `sim_track_capital`); winners are launched LIVE with dedicated capital, losers defunded. No pooled wallet, no cross-strategy allocation.
- **Calculated aggression.** Bigger dedicated capital on higher-conviction, multi-regime, OOS-proven survivors when they go live. Aggression is *earned* by evidence.
- **Scale gate.** Live capital grows only on strategies that keep their edge *live*. A SIM-track edge that dies live → defunded immediately.
- **Break-even framing.** Opex is small and fixed-ish; the real risk is **capital** (§9). On a SIM track, P&L is pure signal about which strategies deserve real money.
- **Cost attribution.** Every cost (LLM, sandbox, data, infra) is attributed per-strategy where possible and surfaced on the Dashboard; a strategy's *net* edge nets its share of opex.

---

## 3. System architecture (the spine)

Two planes: a **deterministic control plane** (the master) and an **autonomous lab agent** (the brain). Between them: the **engine** (NautilusTrader), a **modular tool bus**, and the **knowledge layer** (structured store + RAG). Everything is modular — for the *coding agent* (clean packages with intent-specs) and for the *runtime agent* (tools it calls to query/trade/research/learn). **It's a platform, not a script: every venue, data feature, strategy template, tool, and model is a plug-in** — adding one is config + a small module, never a rewrite.

```
            ┌────────────────────────── DETERMINISTIC MASTER ──────────────────────────┐
            │  scheduler · capital allocator · risk/guardrails · spend caps · LIVE GATE  │
            │  venue router · audit ledger · policy engine (chat/voice commands land here)│
            │  >> owns the SCORER (walk-forward OOS + holdout) and the MONEY — AI can't touch <<
            └───────────────▲───────────────────────────────────────────▲───────────────┘
                            │ validated proposals                        │ tools
   ┌────────────────────────┴───────────┐                 ┌──────────────┴───────────────────────────┐
   │     AUTONOMOUS LAB AGENT (brain)   │  RAG / query    │            MODULAR TOOL BUS               │
   │ our thin orchestration loop:       │◄───────────────►│ market-data · backtest · fills            │
   │ author · mutate · WRITE+RUN ML ·   │   (other        │ web-search(Exa/Tavily) · news · YouTube   │
   │ analyze · self-improving SKILLS    │    models)      │ OSINT · LunarCrush · pine-import          │
   │ (OpenRouter fleet, structured out, │                 │ STT/TTS · notes/RAG read-write            │
   │  runs in E2B/Modal SANDBOX)        │                 │ (read/research/propose only — NO execution)│
   └────────────────────────┬──────────┘                 └──────────────┬────────────────────────────┘
                            ▼                                            ▼
   ┌──────────────────────────────────────── ENGINE: NautilusTrader ──────────────────────────────┐
   │  multi-venue · per-venue fee+slippage · backtest = SIM = live parity · Binance/IBKR/ccxt      │
   └──────────────────────────────────────────────────────────────────────────────────────────────┘
                            ▼
   ┌──────────────────── KNOWLEDGE LAYER (Supabase Postgres + pgvector) ───────────────────────────┐
   │  structured records (truth) · event/audit ledger · skills · RAG vectors · markdown views/INDEX │
   └──────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Master = deterministic** (Python). Owns money, scheduling, allocation, caps, venue routing, the live gate, the **scorer**, and the **policy engine** that turns chat/voice into validated config. Small, strongly typed (Pydantic), fully audited.

**Lab agent = our own thin orchestration loop**, not a framework. Pattern: *call model → validate output (`instructor`/Pydantic) → run in sandbox → score → store → improve*. It can **query multiple models** (cheap drafts breadth, frontier judges depth) and **write + run its own ML/code in a managed sandbox**. We adopt the **Hermes self-improving *skill* pattern** (after a successful task, write a reusable skill; a Curator grades/prunes them) — implemented in our own DB + RAG, no framework lock-in. *We buy commodities (OpenRouter, E2B/Modal) and keep the loop hand-written, because the loop is the differentiator.*

**Tool bus = modular**, each capability an independent module with a tiny NL intent-spec, exposed to the agent (MCP where it helps). **Tools are read/research/propose only — execution is deterministic.**

---

## 4. The autonomous lab agent & model router

The brain is genuinely autonomous *inside the lab*: it designs experiments, writes feature engineering, picks/trains models, authors/mutates strategy code, reads results, and iterates — like a human quant researcher — all in a **managed E2B/Modal sandbox** with no secrets and no path to execution venues. Its only hard limits: it **cannot define its own success metric** (the scorer is the master's) and **cannot touch money**.

**Self-improvement (Hermes pattern, our implementation):** successful task → distilled into a reusable **skill** (a parameterized authoring/ML recipe) stored structured + embedded; a periodic **Curator** pass grades skills by downstream OOS success and prunes the rest. The population gets smarter over time, auditable the whole way.

**Model router — buy, not self-host.** Single gateway via **OpenRouter** (one key, many providers; ~5.5% markup accepted for zero routing ops — venue keys never appear in prompts). Structured outputs via **`instructor`**. **Model IDs in config**, newest slot in free.

| Tier | Used for | Example models (configurable) |
|------|----------|-------------------------------|
| **Coding-agent (subscription)** | heavy, occasional, NON-realtime work: batch strategy authoring, deep research, the data-factory passes, migrations, refactors | **Claude Code / Cursor** (flat sub — not per-token) |
| **Frontier / reasoning (API)** | hard novel judgment INSIDE the 24/7 loop where a human can't be triggered | Claude **Opus**, GPT, **Grok** latest — used sparingly |
| **Workhorse / mid (API)** | routine authoring, summarization, regime notes | Sonnet, GPT-mini, Grok-mini, **DeepSeek-V3** |
| **Cheap / open / free (API, DEFAULT)** | the 24/7 autonomous loop: mass mutation drafting, labeling, bulk reads, ingestion | **DeepSeek, Qwen, Hermes** — cheap/free first |

**One gateway = OpenRouter** (one key, every model — Qwen/DeepSeek/Grok/Claude/GPT — swap by config, not code). **Default to the cheapest/free tier**; escalate to a smart model only when confidence is low, under the **daily cap**.

**Cost rule (the lever):** **24/7 + cheap + deterministic → cheap/free API tier; heavy + occasional + judgment → Claude Code on the flat subscription** (the sub beats per-token for big batch/research work). The system is therefore **steerable by any coding agent**: it exposes typed seams — `StrategySpec`, `strategies/inbox/`, **skills in `.claude/skills/`**, the engine API + CLIs — so Claude Code/Cursor *drives* the heavy LLM work directly instead of the app paying API tokens for it. `docs/` names which tasks are coding-agent-driven vs automatic.

---

## 5. The evolution loop & live toggle

**One self-improving population machine.** A continuously-evolving population of strategy-versions; survivors get capital and become parents.

**Two clocks:**
- **Research clock (fast, continuous "farming"):** `seed/mutate (from templates, chat ideas, pine, mined research) → fast vectorized screen (vectorbt) → walk-forward OOS backtest in Nautilus (real fees) → score → untouched-holdout check → fund a standalone SIM track → keep / kill / mutate`. **Two-tier backtest** is the throughput trick: cheap vectorized screening (thousands of candidates in minutes) kills the obvious losers first; only survivors pay for full event-driven Nautilus validation with realistic fills. Runs as fast as compute allows, 24/7.
- **Trade clock (slow):** survivors act on 1h/4h/daily bars, hold **days–weeks** (swing).

**Strategy representation — natural-language hypothesis, data-fit numbers (quantamental).** Strategies are neither hand-coded templates we tune nor free-text vibes. The LLM authors a **typed hypothesis spec** — universe, horizon, catalyst, entry/exit *structure* referencing **named data features**, risk rules — in natural language; a deterministic compiler turns it into a runnable Nautilus strategy. **The LLM may not hardcode thresholds or magic numbers** — the *numbers are fit from data* by the optimizer/agent and must be robust across folds. The LLM brings the economic *why*; the data brings the *how much*. (This is also an overfitting control: parameter search is scored with multiple-testing-corrected, deflated Sharpe, so "discovering" a lucky parameterization doesn't count.)

**Fitness = walk-forward OOS**, hardened with deflated Sharpe, min-trades gate, multi-regime checks, and a **final untouched holdout** seen once before promotion. **The single ranking scalar = deflated out-of-sample Sharpe**; a strategy must clear the gates (min-trades, max-drawdown, holdout) even to be ranked — one number to sort by, so the agent can't cherry-pick a flattering metric. The leaderboard still **displays net %** prominently (it's what you care about); we *rank* robustly and *show* the %. **Expect to kill 95%+** — that's the system working.

**Explore/exploit — keep luck alive.** The loop runs two lanes on a configurable split (default ~70/30): an **exploit lane** that mutates and recombines current survivors (incremental, single-variable-by-default, clean attribution), and an **explore/wildcard lane** that authors high-variance, low-prior, *novel* hypotheses — exotic feature combinations, cross-market transfers, bold multi-variable leaps and crossover — deliberately reaching outside the current population so the machine can get *lucky* and escape local optima. Both lanes face the same deterministic scorer; neither is judged at birth. **Diversity pressure** keeps the population from collapsing into one style: decorrelated and unusual strategies are kept alive even at a slightly lower rank, because variety has option value when regimes shift. The screening is cheap on purpose precisely so exploration can be wide.

**The flywheel (better / faster / stronger).** The machine compounds its own *research efficiency*, not just capital: every run adds labeled outcomes → the survival model (§8) gets sharper → compute is steered to the candidates worth validating (screen many, full-test the right few) → discovery speeds up. Successful tasks distill into **skills** (Curator-pruned) that raise authoring quality; the **graveyard** stops it re-walking dead ends. More data → better features → better strategies → more data. *(The survival model prioritizes compute; it never vetoes an idea — the explore lane always gets its budget so the model's own blind spots can be discovered.)*

**Live toggle (off by default).** Everything runs in realistic SIM, **tracked as if live** (same code path — backtest = SIM = live). Flip the **global toggle ON** and a strategy that has passed the gates is **launched LIVE manually with dedicated capital under hard caps** — same entity, just routed to a live venue. No separate SIM-bots vs live-bots. (It still *announces* promotions in the Console and respects per-venue/global caps; if a strategy's live edge underperforms its SIM track, it's defunded automatically.)

**Capital model — standalone tracks (no pooled wallet):**
- **Each survivor proves itself on its OWN standalone track.** Every strategy-version that clears the gate gets its *own* SIM forward-test (a **Track**, default **$1,000** — `sim_track_capital`), held and marked-to-market across real bars, judged purely on **risk-adjusted % return**. It always has full capital to express its signal — there is **no pooled wallet**, no cross-strategy allocation, and no capped-Kelly pool sizing, so a good strategy is never mis-scored because some shared book drew down or another strategy hogged capital. This is the leaderboard signal.
- **Going live is manual and per-strategy.** A track that proves itself is **launched LIVE manually with dedicated capital** under hard caps — same entity, just routed to a live venue. No automatic pooled bankroll; each live strategy gets its own dedicated allocation.
- The UI shows **both**: per-strategy track % (Leaderboard) and the **aggregate read-out** — the Σ of all standalone tracks (Dashboard) — which is a read-out, not an account you trade from. A manual top-up/reset (reset = back to starting capital, not zero) stays available for clean experiments.

---

## 6. Knowledge, memory, ingestion & RAG (read a lot, cheaply)

Structured data is the source of truth; markdown + an INDEX are the cheap views; RAG retrieves only what's relevant.

- **Structured first (standardized).** Strategies, backtests, trades, notes, skills, model calls, decisions, ingested sources → typed Postgres rows + an append-only **event/audit ledger**. Queryable, comparable, chartable. Not free-form markdown.
- **Markdown views, generated.** Strategy "cards", weekly digests, post-mortems — rendered from structured data, editable in chat.
- **INDEX over everything** (`INDEX.md` + a `catalog` table): agents find the right record/section and read *only that*.
- **RAG (pgvector in Supabase).** Strategies, notes, skills, and mined external knowledge embedded so the agent retrieves prior art before authoring. Embeddings via API (buy).
- **Ingestion (all V1):** **plain-chat strategy ideas**, **PineScripts**, **YouTube transcripts**, **OSINT**, **news**, **LunarCrush/social**, and **images/screenshots (vision)** — pulled via managed APIs into the RAG store and mined for *testable* rules. Qualitative signals **confirm or veto** a numbers-based setup in liquid markets — they never *originate* a liquid-market trade. **Exception:** in prediction markets the event itself is the tradeable, so news/forecasting can originate there (§7).
- **Vision ingestion + veracity gate (the screenshot path).** The Console accepts images — a tweet/post, a trades screenshot, a chart. A **multimodal model** (via OpenRouter; no new vendor) extracts typed content (kind, claims, entities: tickers/prices/dates/handles) with `instructor`. Then a **deterministic-assisted veracity gate** classifies every claim and **cross-checks it against data we already hold** — price/OHLC at the claimed time, the event vs news/EDGAR/FRED, etc. — labeling each `verified` / `contradicted` / `unverifiable`. Examples: *"BTC broke $100k yesterday"* → checked against the tape; *"I made +400% on this trade"* → **unverifiable** (we can't see a stranger's broker), so the *number* is discarded and only the *setup structure* is kept as a hypothesis. **Screenshots are the lowest-trust input that exists, so they get the strictest gate** — a doctored image can never become evidence, only (at most) an unverified hypothesis or a watch. Verified claims behave like any qual signal (confirm/veto in liquid markets; may originate only in prediction markets). The image is stored (Supabase Storage), graded, and written as a typed `source` with a `veracity` field. **This is anti-slop, not a backdoor:** the screenshot feeds research / monitoring / a gated backtest — it never fires a trade on trust.
- **External repos / prior art to mine (RAG):** the staged `TradingAgents-main`, plus **Microsoft Qlib + RD-Agent** (automated quant R&D + ML factor patterns), **QuantaAlpha** (LLM + evolutionary factor mining), **AgentQuant / Alpha-Agent / Auto-Quant** (LLM strategy-research loops), **FINSABER** (LLM-strategy benchmark with explicit bias mitigation), **Freqtrade** + pine libs — copied as *patterns*, never coupled to live trading. **Benchmark reality:** none of these is a money-machine — they're research toys, single-asset, or let the LLM define/tune its own metric (the reward-hacking trap we engineer out). We mine them; we don't adopt them as the brain.

---

## 7. Venues, fees, realistic forward-test (SIM) & arbitrage

**Venues, pairs, and fees are first-class.** The agent sees a catalog: "instrument @ venue @ fee schedule @ constraints." Adding a venue is config + an adapter.

- **V1 covers crypto *and* stocks** (Binance spot + IBKR equities) on one abstraction, plus **ccxt** breadth for more crypto venues. FX/options/futures via the same interface later.
- **Realistic forward-test / SIM (as close to live as possible):** per-venue maker/taker fees, **slippage vs. order size/liquidity/ADV**, partial fills, latency, **funding rates** (perps), **borrow costs** (shorts/margin), spread, **market hours & halts** (equities), min-notional & lot sizes — via Nautilus fill models on real historical + live-shadow data. "It worked in SIM" must mean something, because the SIM track *is* the promotion track record.
- **Data is first-class (the quant weak link most people get wrong):** **point-in-time, survivorship-free** history (incl. delisted names), corporate-actions-adjusted for equities, and **seeded/reproducible** backtests. Crypto via exchange/**ccxt** (free, solid); equities via dedicated **bars + fundamentals** vendors (§15). Forward-test (SIM) runs on **live-shadow** market data so fills reflect *current* liquidity, not just clean history. Garbage-in is the silent killer of SIM→live parity. **Storage split:** bars/feature **history live in the Nautilus Parquet catalog** (columnar, Polars); **Postgres is the control-plane + money-truth only** — never row-per-bar OHLC. Features are read by **as-of join** on knowledge-time (the mechanism that makes lagged sources like 13F/COT safe, not look-ahead). Some free sources are **best-effort/degraded** (crypto liquidations, token-unlocks) and ship as low-confidence features that must still earn their place through the OOS gate (`docs/archive/BUILD_PLAN.md §6`, historical).
- **Quant feature sources, tiered (signal-first, cost-aware).** *More data = more overfitting surface*, so each source needs a **prior hypothesis** for why it carries edge at swing horizon and must survive the same OOS gate. No data for its own sake.
  - *Tier 0 — free/cheap, high-signal, start here:* crypto funding rates / open interest / liquidations / perp-spot basis / exchange flows (ccxt + exchange APIs); **CFTC COT** (positioning), put/call ratio, VIX term structure; **SEC EDGAR** (8-K, 10-Q, Form 4 insider, 13F), earnings & short-interest; **FRED** macro (rates, yields, DXY, credit spreads); economic / earnings / dividend / token-unlock / halving **calendars**; **prediction-market odds**; news + social (LunarCrush, Reddit/X, Google Trends).
  - *Tier 1 — premium, buy only when an edge justifies it (ROI rule §2):* on-chain (Glassnode / Nansen / Dune), options flow / IV surface / gamma exposure, estimate revisions and other alt-data.
- **Prediction markets are a first-class V1 asset class — Polymarket (+ Kalshi optional).** Edge = better/faster **probability estimation** on slower-resolving events: exactly the "compete on returns, not speed" game where small size is an *advantage* and big funds can't be bothered. **No custom build:** NautilusTrader ships a **native Polymarket adapter** (data + execution via the CLOB, `py-clob-client-v2`, Polygon wallet + **pUSD/USDC** collateral; ~1s order-signing is irrelevant at swing horizon). The adapter is **live-only**, so *SIM* Polymarket runs our generic **simulated-fill engine on live CLOB order-book data** (live-shadow) — identical to every other venue. We model **resolution/settlement** and **thin long-tail liquidity** (cap size vs book depth) as first-class risks. **Polymarket trades live under the same global toggle as every other venue — no special-casing.** When live is on, qualifying prediction-market strategies promote to real pUSD/USDC exactly like a crypto or equity strategy. **Legality/eligibility is the operator's responsibility** (e.g. Polymarket's ANJ geoblock in France, Kalshi US-only), the same as holding any venue key — the system treats it as one more venue, not a separate gate. Odds-as-features are usable everywhere immediately.
- **Event/news-driven is a strategy class — done right.** We do **not** race headlines in liquid markets (we can't win latency, and "the LLM read the news and bought" *was* v1 slop). News/catalysts are *features* the quant layer must confirm. The place news genuinely *originates* a trade is **prediction markets**, on a slow horizon where forecasting skill — not speed — pays.
- **Cross-market signal transfer** (cheap, underused edge): Polymarket/Kalshi odds → macro/equity positioning; crypto funding/OI → risk-on/off; options skew → equity hedging. One market's price is another market's feature.
- **Arbitrage is a strategy type**, not special infra: simultaneous multi-venue pricing makes cross-venue/cross-instrument (fee- and latency-aware) arbitrage just another evolvable template.

---

## 8. ML

Two layers, both cheap and CPU-first:
- **Agent-written ML (autonomous):** the lab agent writes and runs its own feature engineering, model selection, training, and evaluation in the sandbox — not limited to a fixed pipeline. It keeps whatever beats the **deterministic OOS scorer** (which it cannot alter).
- **Baseline tabular models (XGBoost/LightGBM):** a standing survival/edge model predicts whether a strategy-version will hold its edge OOS, to **prioritize compute** and **flag overfit**. Shared **feature store** (volatility regime, trend, breadth, liquidity, strategy stats). Periodic CPU training (RunPod/Modal burst only if needed). Improves as labeled history grows.

---

## 9. Risk & safety (deterministic, non-negotiable)

The validator gauntlet (now in the engine — `apps/engine/cosmu/`; ported + hardened from the retired v1 Node validator) runs on **every** order, SIM or live:
- venue/pair authorization, min-notional/lot/tradability, budget with safety buffer, min cash reserve;
- **stop-loss/take-profit required** on entries; max orders per run; market/limit policy;
- **memoryless sizing — no revenge trading:** position size = f(current equity, volatility, conviction), **never** f(past losses); martingale / averaging-down-to-recover / "win it back" are banned outright;
- portfolio **drawdown kill-switch** (from `guardian.ts`); per-strategy and global exposure caps;
- **daily LLM/API spend cap**; **live OFF by default**; on promotion, **per-strategy + global live caps**.
- **The scorer and the money are out of the AI's reach** — the agent can write any code and run any ML, but cannot define success or move capital. Sandbox (E2B/Modal) has no secrets and no execution-venue network path.

**Evaluation biases we engineer out:** *starvation* (standalone per-strategy tracks, §5) · *capacity/market-impact* (slippage modeled vs order size & liquidity/ADV, so % is honest at deployable size) · *survivorship/lookahead* (point-in-time data incl. delisted instruments, no future info) · *timing/recovery* (memoryless sizing + normalized %).

Everything is logged to the audit ledger; blocks are recorded and surfaced in chat.

---

## 10. Data model (fresh DB, standardized)

Old DB killed; fresh schema on Supabase Postgres + pgvector. Core tables below; **the DDL-level shape (columns, types, FKs, indexes, the append-only invariants) is `docs/archive/BUILD_PLAN.md` Appendix A** (historical reference; the live shape is `apps/engine/cosmu/knowledge/schema_postgres.sql`).

`venues` · `instruments` · `strategies` · `strategy_versions` (parent_id, generated_code, code_hash, params, mutation_rationale, origin[template|chat|pine|mined]) · `backtests` (is/oos windows, oos_return, deflated_sharpe, max_dd, win_rate, num_trades, holdout_passed) · `runs` · `executions` (+venue, +is_sim, +fees, +slippage) · `portfolio_snapshots` · `tracks` (per-strategy standalone SIM book, default **$1,000** — `sim_track_capital`; no pooled wallet, no cross-strategy allocation) · `positions` · `live_toggle` + `live_caps` · `costs` (vendor, category, amount, strategy_attribution) · `policies` (chat/voice-driven config) · `skills` (recipe, grade, lineage, embedding) · `sources` (ingested youtube/news/osint/pine/**image**, **claims+veracity**, embedding) · `recommendations` (proactive, approval state) · `events` (append-only audit) · `llm_calls` (tier, tokens, cost) · `research_notes` (structured + rendered markdown) · `catalog` (the INDEX). **Embeddings live as `vector` columns on their owning rows** (`skills`, `sources`, `research_notes`, `strategy_versions`) — no separate `embeddings` table (see Appendix A).

---

## 11. UX/UI (beautiful, modern, finance-grade)

- **Stack:** Next.js + **shadcn/ui** + **Tremor** (finance charts) + **TanStack Table** (dense data). Dark, modern, clean. Desktop-first, mobile-friendly.
- **Finance-data-first:** equity curves, drawdown bands, allocation treemaps, trade blotters, OOS-vs-holdout views — legible at a glance, drill-down on demand.
- **Two views, one truth:** per-strategy **track %** (Leaderboard) for unbiased judgment, and the **aggregate read-out (Σ of all standalone tracks) + Costs card** (Dashboard) for the real money picture — a read-out, not a pooled wallet you trade from.
- **Four surfaces only** (§1). The **Console** is the star: **chat + voice** control + a recommendation/approval inbox + the global live toggle.
- **No clutter.** If a page doesn't help you decide or earn, it doesn't ship.

---

## 12. Infra, vendors & cost accounting

**Principle: buy commodities, build the differentiator.** Managed where sane; flag stakes where a buy's cost is uncertain.

| Need | Choice | Build/Buy | Stake / note |
|------|--------|-----------|--------------|
| Model access | **OpenRouter** | buy | drop self-hosted router; ~5.5% markup, fine |
| Agent sandbox + ML compute | **E2B or Modal** | buy | secure isolation is hard; **usage-priced — cost scales with agent effort** (tied to ROI rule + spend cap) |
| Voice | **Deepgram / ElevenLabs / OpenAI** | buy | cheap STT/TTS |
| Web/research | **Exa or Tavily**, a news API, YouTube-transcript API, LunarCrush | buy | per-query; cap-able |
| Embeddings | OpenAI/Voyage API | buy | cheap |
| Compute (loop+API) | **Railway** worker | buy/managed | continuous CPU; predictable beats metered |
| DB + RAG | **Supabase + pgvector** | managed | a switch, not a build — keep |
| Market data (bars) | **Norgate** (survivorship-free *daily* US/AU/CA, cheap) + **Databento** (intraday/breadth) for equities · **ccxt** (crypto, free) | buy | **survivorship-free, point-in-time, corp-actions-adjusted**; ~$30–100/mo. Data quality = SIM→live parity |
| Equity fundamentals | **Sharadar** (Nasdaq Data Link) or **SimFin** | buy | point-in-time, pre-parsed (~$30–50/mo) — keeps "quantamental" honest vs building an EDGAR ETL; also supplies earnings dates |
| Prediction markets | **Polymarket** (native Nautilus adapter) · Kalshi optional | buy/lib | data+exec via CLOB; **forward-test (SIM) now, real money gated on jurisdiction** (France geoblock) |
| Engine | **NautilusTrader** | core lib | no managed equivalent — keep |
| Frontend host | **Vercel** | managed | keep |
| Observability + evals | **OpenTelemetry + Langfuse** | buy / OSS | vendor-neutral traces; free tier / self-host; **audit ledger stays money-truth** |
| Durable workflow engine | *skip for now* | — | in-process scheduler suffices at V1; revisit if we need bulletproof retries |

Secrets (server-side only, never in prompts): venue keys (Binance, later IBKR), model/API keys. **Scaling path:** vertical first (bigger box / more parallel backtests), then a worker pool when alpha justifies it.

---

## 13. Codebase conventions (modular, agent-first)

- **New home:** `apps/engine/` (Python) + `apps/web/` (Next.js) — those are the only `apps/` now. The old v1 Node API is **gone** (engine parity landed; `apps/web` was rebuilt on the typed contracts). Stack: **Railway** (engine) · **Vercel** (web) · **Supabase** (Postgres) · **Modal** (heavy compute).
- **Two kinds of modularity:** (a) *code* modules for the coding agent — small packages, each with a short NL **intent-spec header** (purpose / inputs / outputs / invariants); (b) *runtime* tool modules for the agent to query/trade/research/learn, each independently callable.
- **Token-frugal docs (SOTA):** keep `AGENTS.md` *short*; **decision tables** for 2–3 valid approaches; **always / ask-first / never** boundaries; **pair every "don't" with a "do instead."** **Don't auto-generate docs** and **don't restate what a linter/type-checker/CI already enforces** — *the tool is the constraint* (bloated/auto-gen context files measurably lower agent success and raise cost). Intent-specs stay tiny (why + invariants). The big `VISION.md` is the human memo; the per-session agent file is lean. Read the INDEX, then one record/section.
- **Strong typing & validation:** Pydantic everywhere; LLM outputs always pass `instructor` + the validator before they count.
- **Eval-driven (SOTA):** three layers — unit evals on agent steps · LLM-as-judge regression suites · production trace sampling. **Failed online scores become eval cases**; **CI eval gates block merges** that drop quality. Instrument with **OpenTelemetry** (portable across Langfuse/Braintrust/self-host).
- **OSS/vendors we stand on:** NautilusTrader (engine, full event-driven validation + Polymarket adapter), **vectorbt** (fast vectorized screening tier), ccxt (venue breadth), pandas-ta/ta-lib (indicators), **Optuna** (param-space optimizer — Bayesian/TPE + pruning, multi-objective), XGBoost/LightGBM (ML), **pypbo** (deflated Sharpe + probability-of-backtest-overfitting), **Polars** (fast columnar feature pipeline) + **Pandera** (dataframe/data-quality validation — guards point-in-time/no-look-ahead), **exchange_calendars** (equity hours/halts), **QuantStats** (strategy tearsheets for the detail page), **OpenRouter** + **instructor** (models, incl. **vision/multimodal** for the screenshot path) + **Supabase Storage** (uploaded images), **E2B/Modal** (sandbox/ML), pgvector (RAG), **Deepgram/ElevenLabs** (voice), **Exa/Tavily** (research), APScheduler (scheduling), **OpenTelemetry + Langfuse** (LLM/agent traces) + **Sentry** (app errors/alerting for 24/7 reliability), **Hypothesis** (property-based tests for the compiler/validator), FastAPI/Pydantic, shadcn/Tremor/TanStack (UI), plus mined patterns from `TradingAgents-main`, **Qlib/RD-Agent**, **QuantaAlpha**, Freqtrade, and pine libraries.
- **Deliberately declined (anti-bloat):** `tsfresh`/`featuretools` mass auto-feature-generation (conflicts with "every feature needs a prior hypothesis" — explodes the overfitting surface); **DSPy** (framework-y; our skill/Curator loop already self-improves prompts without lock-in); **MLflow/W&B** (our typed `backtests`/`runs` tables *are* the experiment tracker); **Prefect/Temporal** (in-process scheduler suffices at V1); **LiteLLM** (OpenRouter chosen). **Scale-path, not V1:** **Ray** (distributed backtests when throughput-bound), **DuckDB** (analytical queries over the parquet cache), **River** (online/incremental survival-model updates), **ccxt Pro** (websocket live-shadow streams).

---

## 14. Milestones (few, huge — V1 built in parallel)

**V1 — the autonomous, self-improving forward-test (SIM) money-machine (everything, in parallel).**
A thin spine is laid hour-zero (engine + fresh schema + tool bus), then these workstreams are built **concurrently**:
- multi-venue engine, **crypto + stocks**, realistic fees/slippage/funding/halts;
- deterministic master (scheduler, allocator, risk, scorer, live gate **off by default**, policy/chat+voice, audit ledger);
- the **autonomous lab agent** (own loop, OpenRouter fleet, E2B/Modal sandbox, writes+runs ML, self-improving skills);
- the **evolving population loop** (seed→walk-forward→score→holdout→fund a standalone SIM track→keep/kill/mutate) with **auto-promote-on-toggle** wired;
- **ingestion (all of it):** chat ideas, PineScript, YouTube, OSINT, news, social, **images/screenshots (vision + veracity gate)** → RAG;
- **ML** (agent-written + tabular baseline);
- **RAG + INDEX + structured store**;
- the **4-surface UI** with the **chat + voice Console**, recommendation inbox, and the global live toggle.
Result: fully autonomous, fully SIM (forward-test), realistic — flip a switch away from live.

**V2 — live & scale.** Turn the toggle on with real capital + scaling on live-proven survivors; more venues, FX/options, deeper arbitrage, heavier ingestion/ML. *Earning mode: double down on what works live.* *(Optional extra leverage: submit our best signals to **Numerai Signals** for NMR — a side revenue stream on the same research.)*

---

## 15. Human checklist (what you do)

1. **OpenRouter** account + key (covers Opus 4.8 / GPT-5.5 / Grok / DeepSeek / Hermes-4 in one). Tell me any models to force-include.
2. **E2B or Modal** account (agent sandbox + ML) — pick one or let me default to E2B for sandbox, Modal for ML bursts.
3. **Railway** account + connect repo (I configure the worker).
4. **Supabase** — confirm I create a fresh project/schema with pgvector.
5. **Voice + research API keys:** Deepgram/ElevenLabs (voice), Exa or Tavily (web), a news API, YouTube-transcript API, LunarCrush. Tell me which to enable from day one. **Tier-0 quant data is free** (ccxt, SEC EDGAR, FRED, CFTC, prediction-market public APIs) — no keys; premium alt-data (on-chain/options flow) is opt-in later.
6. **Prediction markets (Polymarket via Nautilus's native adapter; Kalshi optional):** odds feed in as features now; forward-test (SIM) ships V1; **live trades under the same global toggle as every venue.** To go live you provide a **Polygon wallet + pUSD/USDC** (like a Binance key). **Legality/eligibility is your call** — Polymarket is geo-blocked in France (ANJ), Kalshi is US-only; the system doesn't special-case it.
7. **Binance API key** (spot, read+trade) — *not needed for V1 forward-test (SIM)*; needed when you flip live.
8. **Equities bars vendor** (Polygon / Databento / Norgate) — **survivorship-free, point-in-time, corp-actions-adjusted**; pick one or let me default. (Crypto data is free via ccxt.) **IBKR** account + gateway is for equity *execution*, needed only when you flip live.
9. **Equity fundamentals vendor** (**Sharadar** via Nasdaq Data Link, or **SimFin**) — point-in-time, ~$30–50/mo; you approved buying. Account/API key needed when track A builds equity fundamentals features (not an hour-zero blocker).
9. **SIM bankroll + base currency** — default **$1,000 USD-equiv per standalone track** (`sim_track_capital`, adjustable) unless you say otherwise.
10. **Spend caps** — set the daily LLM/API cap now; live daily-loss cap before flipping live.

---

## 16. Honest risks & how we defend

- **Overfitting / reward-hacking (the big one):** the agent could "prove" itself rich by gaming a metric — so the **scorer (walk-forward OOS + untouched holdout) is the master's, not the agent's**, plus deflated Sharpe, min-trades, multi-regime, and ML overfit-flagging. We expect to kill the vast majority of ideas.
- **Evaluation biases:** *starvation* killed by standalone per-strategy tracks; *capacity* by market-impact/slippage modeling so % is honest at deployable size; *survivorship/lookahead* by point-in-time data; *revenge/recovery* by memoryless sizing. (Details §5/§9.)
- **SIM≠live divergence:** realistic forward-test / SIM (fees, slippage, funding, borrow, latency, halts) + auto-defunding any strategy whose live edge underperforms its SIM track.
- **Cost runaway (heavier now — sandbox + APIs are usage-priced):** daily caps, cheap-tier-by-default routing, and research spend tied to trailing realized edge. The agent throttles itself when it's not earning.
- **Sandbox security:** managed (E2B/Modal), no secrets, no execution-venue network path.
- **Garbage qualitative/OSINT data:** news/social can only **confirm or veto** a numbers-based setup — never originate a trade.
- **Complexity creep:** four-surface UI + chat/voice control keep it simple to drive; modularity + intent-specs keep it simple to evolve.

---

## 17. Weak links we're closing (incl. why v1 was "slop")

The point of v2 is to fix the specific failure modes that made v1 unreliable and that sink most amateur quant systems. Each row is a known weak link → the deterministic defense.

| Weak link | Why it bites | Our fix |
|-----------|--------------|---------|
| **LLM makes the trade call** (v1's core slop) | non-deterministic, hallucinated orders, no reproducibility | **deterministic master decides**; LLM only proposes code/analysis (§0, §3) |
| **Loop didn't reliably run** (v1) | missed cycles, double-runs, silent stalls | **one scheduler**, atomic claim (`FOR UPDATE SKIP LOCKED`), every tick audited (§3, §9) |
| **Data quality** | survivorship/lookahead → fake edge that dies live | **point-in-time, survivorship-free, seeded** data; corp-actions-adjusted (§7) |
| **SIM ≠ live** | clean backtests, ugly live fills | realistic fills (fees/slippage/funding/borrow/halts) + **live-shadow data** + **auto-defund** on live underperformance (§7, §5) |
| **Fuzzy fitness** | many metrics → cherry-picking, overfit | **one scalar: deflated OOS Sharpe, gated**; holdout seen once (§5) |
| **Reward-hacking / overfit** | agent "proves" itself rich by gaming the metric | **scorer + money out of the agent's reach**; deflated Sharpe, min-trades, multi-regime, ML overfit-flag (§0, §9, §16) |
| **Cold start** | nothing to trade on day one | **seed from OSS patterns** (TradingAgents/Freqtrade/pine) + indicator templates, then mutate (§6) |
| **Agent-authored code reaching live** | unsafe/buggy generated code on real money | must **survive sandbox → OOS → holdout → forward-test (SIM)**, pass static checks + the validator before any capital (§4, §9) |
| **Compute throughput** | farming is backtest-bound | vectorized + **parallel backtests**, ML prioritizes which candidates to spend compute on; scale on edge (§8, §12) |
| **Token burn** (v1) | naive prompting got expensive fast | **structured store + INDEX + RAG**, cheap-tier-by-default routing, daily spend cap (§4, §6) |
| **Schema drift Python↔TS** | hand-maintained types diverge, frontend breaks | **Pydantic → OpenAPI → generated TS client**, never typed twice (§13) |
| **Secrets / live keys** | leak or misuse = real loss | **server-side only, never in prompts/sandbox**; withdrawals disabled on venue keys (§9, §12) |
| **Too many pages** (v1 sprawl) | UI rot, nothing helps you decide | **four surfaces only**; if a page doesn't help you decide or earn, it doesn't ship (§1, §11) |
| **Data dredging / multiple testing** | farm thousands of specs/params → the best is *lucky*, not real | deflated Sharpe corrected for **trial count**; holdout; cap discoveries per unit of search; keep the **graveyard** of deaths so we don't survivor-bias our own population (§5) |
| **Hardcoded magic numbers** | LLM guesses thresholds → our bias + overfit | LLM authors hypothesis *structure* only; **numbers fit from data**, multiple-testing-corrected (§5) |
| **Thin-market liquidity / capacity** | small-caps & prediction markets fill poorly; backtest size ≠ tradeable size | model market impact vs ADV/open interest; cap size to a fraction of liquidity; an unfillable edge is worthless (§7, §9) |
| **Prediction-market resolution & legal** | settlement-timing/resolution risk; France geoblock (ANJ); Kalshi US-only | **native Nautilus adapter** + our resolution model; **trades live under the global toggle like any venue**; legality/eligibility is the **operator's responsibility**, not a system branch; odds usable as features immediately (§7, §15) |
| **Regime fragility** | a strategy that only worked in one regime | multi-regime gate + a regime classifier decides which strategies may go live (§5, §8) |
| **Naive news-trading** | latency race vs HFT you can't win | news = confirm/veto feature in liquid markets; only *originates* trades in prediction markets, slow horizon (§7) |
| **Trusting screenshots / fake social proof** | doctored tweets & faked P&L screenshots → acting on lies | **veracity gate** cross-checks every claim against real data; third-party P&L is always `unverifiable` (number discarded, structure kept as a gated hypothesis); `contradicted` vetoes; screenshots never become evidence on trust (§6) |

---

*This memo is the contract. If code and memo disagree, fix one of them on purpose.*
