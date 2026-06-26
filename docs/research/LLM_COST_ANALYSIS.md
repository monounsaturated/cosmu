# COSMU LLM Cost Analysis
> Generated 2026-06-19 | Covers narrative pipeline, strategy authoring, scaling, and self-hosted compute

---

## 1. COSMU Token Profile Per Cycle

Derived from codebase analysis of three LLM call sites.

### Sources and token estimates (1 bot, 10 symbols)

| Call site | File | Tokens in | Tokens out | Notes |
|-----------|------|----------|-----------|-------|
| Narrative scoring | `research/llm_narrative_pipeline.py` | ~9,000 | ~3,500 | 10 symbols × (300 sys prompt + 40 headlines × 15 tok) |
| Strategy authoring | `lab/llm.py` | ~7,500 | ~2,400 | 3 candidates × (2,500 in + 800 out) |
| LLM formatter | `ingest/llm_formatter.py` | ~1,500 | ~600 | 3 alt-data format calls |
| **Full cycle (uncached)** | | **~18,000** | **~6,500** | **≈ 24,500 total** |

### Cache impact on narrative scoring

`llm_narrative_pipeline.py` caches results by content hash of the headline batch. GDELT updates every 15 min; narrative articles stale at different rates depending on run frequency.

| Frequency | Cache hit rate | Effective narrative in | Effective narrative out |
|-----------|---------------|----------------------|------------------------|
| 15 min | ~82% | 1,620 | 630 |
| 30 min | ~68% | 2,880 | 1,120 |
| 1 hour | ~50% | 4,500 | 1,750 |
| 4 hours | ~18% | 7,380 | 2,870 |
| Daily | ~5% | 8,550 | 3,325 |

Strategy authoring and formatter calls are **fresh every run** — no caching applies.

### Effective tokens per run by frequency

| Frequency | Input tokens | Output tokens | Total |
|-----------|-------------|---------------|-------|
| 15 min | 10,620 | 3,630 | 14,250 |
| 30 min | 11,880 | 4,120 | 16,000 |
| 1 hour | 13,500 | 4,750 | 18,250 |
| 4 hours | 16,380 | 5,870 | 22,250 |
| Daily | 17,550 | 6,325 | 23,875 |

---

## 2. Monthly Token Volume (1 bot)

| Frequency | Runs/day | Runs/month | Input (M tok) | Output (M tok) |
|-----------|----------|-----------|--------------|---------------|
| 15 min | 96 | 2,880 | 30.6 | 10.5 |
| 30 min | 48 | 1,440 | 17.1 | 5.9 |
| 1 hour | 24 | 720 | 9.7 | 3.4 |
| 4 hours | 6 | 180 | 2.95 | 1.06 |
| Daily | 1 | 30 | 0.527 | 0.190 |

---

## 3. API Cost Tables by Model and Frequency

### Monthly cost: 1 bot

| Model | 15 min | 30 min | 1 hour | 4 hours | Daily |
|-------|--------|--------|--------|---------|-------|
| GLM-4-Flash (Zhipu) | $0.84 | $0.47 | $0.27 | $0.082 | $0.015 |
| DeepSeek V3 | $7.22 | $4.04 | $2.31 | $0.71 | $0.13 |
| Llama 3.1 8B (Together) | $4.21 | $2.36 | $1.31 | $0.40 | $0.072 |
| GLM-4 std (Zhipu) | $4.21 | $2.36 | $1.31 | $0.40 | $0.072 |
| DeepSeek R1 | $17.6 | $9.84 | $5.59 | $1.85 | $0.34 |
| **Claude Haiku 4.5** | **$83** | **$47** | **$27** | **$8.25** | **$1.48** |
| Llama 3.1 70B (Together) | $27.4 | $15.3 | $8.73 | $2.65 | $0.48 |
| Qwen 2.5 72B (Together) | $29.3 | $16.4 | $9.35 | $2.84 | $0.51 |
| **GLM 5.2 (Zhipu est.)** | **$145** | **$81** | **$47** | **$14** | **$2.57** |
| **Claude Sonnet 4.6** | **$249** | **$140** | **$80** | **$25** | **$4.43** |
| **Claude Opus 4.8** | **$416** | **$233** | **$134** | **$41** | **$7.39** |
| GPT-5 class / o3 proxy | $726 | $407 | $233 | $72 | $12.87 |
| Claude Fable 5 | $834 | $467 | $268 | $82 | $14.8 |

> **Pricing sources:** Anthropic official (2026-06-04); Zhipu AI platform; Together AI published rates. GLM 5.2 is estimated at GPT-4o parity ($2/$8 per MTok) — Zhipu has not publicly listed a "GLM 5.2" SKU as of this writing. "GPT-5 class" uses o3-tier rates ($10/$40 per MTok) as a proxy for frontier OpenAI; adjust if GPT-5 launches at different rates. DeepSeek R1 uses $0.55/$2.19 per MTok.

### Current OpenRouter monthly cap: **$30.00** (`BUDGET__OPENROUTER__MONTHLY_CAP`)

At $30/month, here's what each model can sustain:

| Model | Max affordable frequency (1 bot) |
|-------|----------------------------------|
| GLM-4-Flash | Every 15 min — budget barely touched |
| DeepSeek V3 | Every 15 min — 4× headroom |
| Claude Haiku 4.5 | Every 30 min — tight ($47 over) → hourly comfortable ($27) |
| GLM 5.2 | Every 4 hours ($14) |
| Claude Sonnet 4.6 | Daily only ($4.43) |
| Claude Opus 4.8 | Daily only ($7.39) |
| GPT-5 / Fable 5 | Daily only (still under $15, leaves room for extras) |

---

## 4. Signal Quality vs. Run Frequency — "Smartland" Commentary

This is the key question: does running every 15 minutes buy you better trading signals?
For **LLM-driven narrative signals specifically**, the answer is almost always no.

### Timeframe verdict

**15 minutes — noise-land**
GDELT ingests every 15 minutes, but a meaningful narrative shift (sustained bullish/bearish pressure from news) takes hours to establish. Between two consecutive 15-minute runs, headline batches differ by maybe 2-5 new articles out of 40 — the LLM will score them almost identically. The cache hit rate is ~82%, meaning 82% of LLM calls return instantly with no API spend, and the 18% that run return nearly the same scores as the prior cycle. The only genuine signal from 15-minute LLM runs is **breaking news events** — an earnings miss, a merger, a geopolitical shock — where a single article changes the entire narrative. For this purpose, you're better off with a dedicated breaking-news detector (keyword trigger → single LLM call) rather than burning 96 full-cycle runs per day.
**Verdict: never useful for narrative LLM. Use price-based indicators only at this frequency.**

**30 minutes — still mostly noise**
Slightly more headline turnover (~32% new content), but narrative LLM is still overkill. The authoring cost dominates because strategy candidates are regenerated fresh regardless of cache. Cache buys almost nothing on the authoring side. No signal quality improvement vs hourly.
**Verdict: skip. Step up to hourly or use only for breaking-news triggers.**

**1 hour — sweet spot for news-driven signals**
At one hour, GDELT has enough new material to meaningfully update sentiment scores for most symbols. This is the natural cadence of breaking news digestion — a story that breaks at 09:00 will have been reported, syndicated, and counter-narrated by 10:00. The 50% cache hit rate is a good balance: you're paying for new signal, not re-scoring stale content. Strategy authoring at hourly is genuinely useful for intraday regimes.
**Verdict: recommended for active news-driven strategies. Manageable cost at Haiku ($27/mo).**

**4 hours — macro-narrative cadence**
Aligns with major session transitions: Asia close, EU open, US open, US PM session. LLM scores reflect an entire session's worth of narrative accumulation. Signal is more stable, less prone to whipsawing from single articles. At 18% cache hit rate, you're almost always scoring fresh content. Good for strategies that react to session-level regime changes.
**Verdict: excellent for multi-session macro strategies. Cost-efficient across all model tiers.**

**Daily — optimal for GDELT narrative baseline**
The natural cadence of the existing `llm-narrative-pressure-long.json` strategy (`news_event_score` feature). One clean consolidated signal per day, reflecting the full day's news. At 5% cache miss on intraday rechecks, almost all content is new. This is the timeframe where LLM narrative adds the most value per dollar.
**Verdict: primary recommendation for the COSMU LLM narrative pipeline. Lowest cost, highest signal quality per run.**

### Clutter summary

| Frequency | Signal quality (narrative LLM) | Clutter risk | Recommended for |
|-----------|-------------------------------|-------------|-----------------|
| 15 min | Very low | Extreme | Price signals only |
| 30 min | Low | High | Breaking-news triggers only |
| 1 hour | Good | Moderate | Active intraday strategies |
| 4 hours | Very good | Low | Session-regime strategies |
| Daily | Best | Very low | Primary narrative signal |

---

## 5. Model Comparison: Quality, Cost, and Fit

### API-hosted models

| Model | Provider | Quality tier | Reasoning | JSON reliability | $/daily (1 bot) | Best fit |
|-------|----------|-------------|-----------|-----------------|-----------------|----------|
| GLM-4-Flash | Zhipu AI | Budget | Weak | Acceptable | $0.015 | Ultra-cheap volume scoring |
| DeepSeek V3 | DeepSeek | Strong | Good | Good | $0.13 | High-quality at fraction of Opus price |
| Llama 3.1 8B | Together | Budget-mid | Weak | Marginal | $0.072 | Non-critical formatting only |
| GLM-4 std | Zhipu AI | Mid | Moderate | Good | $0.072 | Narrative scoring, not strategy |
| DeepSeek R1 | DeepSeek | Strong+ (reasoning) | Excellent | Very good | $0.34 | Strategy authoring where reasoning matters |
| GLM 5.2 (est.) | Zhipu AI | Mid-high | Moderate | Good | $2.57 | GLM ecosystem completeness play |
| Claude Haiku 4.5 | Anthropic | Mid | Good | Excellent | $1.48 | Best price/reliability for COSMU |
| Llama 3.1 70B | Together | Strong | Good | Good | $0.48 | Open-source quality at low cost |
| Qwen 2.5 72B | Together | Strong | Good | Very good | $0.51 | Strong multilingual + structured output |
| Claude Sonnet 4.6 | Anthropic | High | Very good | Excellent | $4.43 | Strategy authoring quality tier |
| Claude Opus 4.8 | Anthropic | Highest | Best | Excellent | $7.39 | Top strategy authoring, max insight |
| GPT-5 / o3 proxy | OpenAI | Highest | Excellent | Excellent | $12.87 | Not worth 2× Opus cost for this task |
| Claude Fable 5 | Anthropic | Highest | Adaptive | Excellent | $14.8 | Research tasks, not routine pipeline |

### GLM 5.2 vs Opus 4.8 vs GPT-5 class — direct comparison

**GLM 5.2 (estimated, Zhipu API):**
- Estimated GPT-4o parity on benchmarks
- Chinese-market data and sentiment understanding may be stronger
- No public "GLM 5.2" SKU confirmed — based on trajectory from GLM-4 family
- Pricing estimated at $2/$8 per MTok (2-2.5× Haiku, ~0.4× Opus)
- JSON structured output reliability: good but not Anthropic-grade
- **For COSMU:** competitive for narrative scoring. Questionable for strategy authoring where strict Pydantic parsing in `lab/llm.py` needs consistent JSON.

**Claude Opus 4.8:**
- Highest-quality strategy proposals in the `LlmProposal` Pydantic schema
- Temperature=0, structured output: near-perfect JSON compliance
- Deep reasoning on market conditions, coherent multi-factor strategies
- $5/$25 per MTok — 2.5× Sonnet, 5× Haiku
- **For COSMU:** overkill for headline scoring, justified for strategy authoring

**GPT-5 / o3 class (proxy):**
- Comparable to Opus in reasoning; o3 specifically excels at math/logic
- At $10/$40 per MTok — 2× Opus, 10× Sonnet — no meaningful quality gain for this use case
- OpenRouter already supports GPT-4o, GPT-4o-mini; "GPT-5.5" not yet a listed SKU
- **For COSMU:** not recommended. Anthropic Haiku→Sonnet→Opus gradient is a better ladder.

**Recommendation:** Run narrative scoring on **DeepSeek V3** (best quality/price ratio), strategy authoring on **Claude Haiku 4.5** (reliable JSON, proven in tests), escalate to **Claude Sonnet 4.6** for strategy authoring if proposal quality needs improvement. Reserve **Opus 4.8** for high-conviction, low-frequency strategy generation cycles only.

---

## 6. Open Source Models — Self-Hosted Compute Analysis

### Model options and quality

| Model | Size | Quality | Notes |
|-------|------|---------|-------|
| GLM-4-9B (open source) | 9B | Mid | Chinese-language strength; fits RTX 4090 |
| Llama 3.1 8B | 8B | Budget-mid | Meta; good baseline; single GPU |
| Mistral 7B-Instruct | 7B | Budget-mid | Fast, low VRAM |
| Llama 3.1 70B | 70B | Strong | Needs 2-4× GPU; best open 70B |
| Qwen 2.5 72B | 72B | Strong | Strong multilingual, JSON |
| DeepSeek V3 (open weights) | 671B MoE | Highest open | 8× H100 to run; API easier |
| Mixtral 8×7B | 46B active | Strong | MoE, efficient; 2× GPU |

### Hardware cost scenarios

#### Scenario A: Serverless GPU (RunPod / Modal / Replicate — pay per second)

Most cost-effective for COSMU's bursty usage pattern (trading cycles are short, compute is idle between runs).

| Model | GPU needed | Cost/hr | Time/cycle | Cost/cycle |
|-------|-----------|---------|-----------|-----------|
| 7B class (GLM-4-9B, Llama 8B) | RTX 4090 (24GB) | $0.70 | 4.5s | $0.00088 |
| 70B class (Llama 70B, Qwen 72B) | 2× A100 80GB | $4.50 | 12.6s | $0.0158 |
| DeepSeek V3 full | 8× H100 | $32.00 | 35s | $0.311 |

Cycle time estimate: input throughput ~5,000 tok/s, output throughput ~1,500 tok/s for 7B; lower for larger models.

| Model | Frequency | Monthly (serverless) |
|-------|-----------|---------------------|
| GLM-4-9B / Llama 8B | Every 15 min | $2.53/mo |
| GLM-4-9B / Llama 8B | Hourly | $0.63/mo |
| GLM-4-9B / Llama 8B | Daily | $0.026/mo |
| Llama 3.1 70B | Every 15 min | $45.6/mo |
| Llama 3.1 70B | Hourly | $11.4/mo |
| Llama 3.1 70B | Daily | $0.47/mo |

#### Scenario B: Dedicated GPU box (always-on cloud instance)

Only cost-efficient if utilization > 30%. COSMU trading cycles use GPU for maybe 1-5% of the day.

| Hardware | Cost/mo | Break-even utilization vs serverless |
|----------|---------|--------------------------------------|
| RTX 4090 (cloud, 24GB) | ~$460/mo | >56% utilization vs serverless 7B |
| A100 40GB (cloud) | ~$900/mo | Not competitive for burst workloads |
| H100 80GB (cloud) | ~$1,800/mo | Only viable for continuous training |

**Verdict:** Dedicated GPU makes no sense for COSMU's trading cadence. Serverless GPU (Modal preferred — already in the COSMU compute stack) is the right call.

#### Scenario C: Local consumer GPU (RTX 4090, owned hardware)

Electricity cost only. At €0.20/kWh (France), RTX 4090 draws ~350W:
- Cost/hour of compute: ~€0.07
- Monthly (always on): ~€50
- Monthly (1% utilization / trading calls only): ~€0.50

**If you already own the hardware:** open-source 7B is essentially free to run for trading workloads.

### Open source vs API: quality gap

| Task | 7B open source | 70B open source | DeepSeek V3 API | Claude Haiku 4.5 |
|------|---------------|----------------|----------------|-----------------|
| Headline sentiment scoring | Acceptable | Good | Very good | Good |
| Strategy JSON authoring | Marginal — parsing failures | Acceptable | Good | Excellent |
| Multi-factor narrative | Weak | Good | Very good | Good |
| Pydantic schema adherence | ~70-80% | ~85-90% | ~95% | ~99% |

The `lab/llm.py` retry logic (max 2 retries on invalid JSON) means ~5% failure rate on 7B models = ~10% of authoring runs degrade or fail. For narrative scoring in `llm_narrative_pipeline.py`, this is acceptable — a failed call returns None and the signal gracefully degrades.

**Practical open source recommendation:** Use GLM-4-9B or Llama 3.1 8B (via Modal serverless) for headline scoring only. Keep Claude Haiku 4.5 via OpenRouter for strategy authoring. Hybrid architecture → lowest possible cost with maintained authoring quality.

---

## 7. Scaling: 1 Bot → 10 Bots → 1,000 Bots

### Architectural insight: what scales with what

In COSMU's architecture:
- **Narrative scoring** scales with **unique symbols tracked** (cached at symbol level, shared across bots)
- **Strategy authoring** scales with **number of bots** (each bot evolves independently)
- **Formatting** scales with **data sources** (fixed overhead)

This means at large bot counts, authoring dominates cost entirely.

### Monthly cost at daily frequency

| Tier | Bots | Unique symbols | Input (M tok) | Output (M tok) | Haiku 4.5 | DeepSeek V3 | Opus 4.8 |
|------|------|----------------|--------------|----------------|----------|------------|---------|
| Single | 1 | 10 | 0.75 | 0.26 | $1.83 | $0.18 | $7.39 |
| Small | 10 | 15 | 2.97 | 0.98 | $7.82 | $0.69 | $30.9 |
| Scale | 1,000 | 50 | 226 | 72.3 | $587 | $51.9 | $2,937 |

At 1,000 bots, authoring tokens (225M in / 72M out) utterly dominate — narrative is noise in the budget.

### Monthly cost at hourly frequency (narrative hourly, authoring daily)

| Tier | Bots | Unique symbols | Input (M tok) | Output (M tok) | Haiku 4.5 | DeepSeek V3 | Opus 4.8 |
|------|------|----------------|--------------|----------------|----------|------------|---------|
| Single | 1 | 10 | 9.7 + 0.225 = 9.93 | 3.4 + 0.072 = 3.47 | $27.3 | $2.36 | $134 |
| Small | 10 | 15 | 9.9 + 2.25 = 12.2 | 3.4 + 0.72 = 4.12 | $32.8 | $2.86 | $161 |
| Scale | 1,000 | 50 | 16.2 + 225 = 241 | 6.3 + 72 = 78.3 | $633 | $56.0 | $3,162 |

### Daily token spend (per bot tier)

| Tier | Haiku 4.5 | DeepSeek V3 | Opus 4.8 | GLM-4-Flash |
|------|----------|------------|---------|------------|
| 1 bot / daily | **$0.049** | **$0.006** | **$0.247** | **$0.0005** |
| 10 bots / daily | **$0.26** | **$0.023** | **$1.03** | **$0.002** |
| 1,000 bots / daily | **$19.6** | **$1.73** | **$97.9** | **$0.20** |
| 1 bot / hourly | **$0.91** | **$0.079** | **$4.47** | **$0.009** |
| 10 bots / hourly | **$1.09** | **$0.095** | **$5.37** | **$0.012** |
| 1,000 bots / hourly | **$21.1** | **$1.87** | **$105** | **$0.22** |

---

## 8. Full Autonomous COSMU Vision — Cost Forecast

The full vision (from `VISION.md`, `MASTER_PLAN.md`, scheduler architecture):

- Global symbol coverage: **500 assets** (equities, crypto, macro indices, FX pairs)
- Active strategies: **100 bots** concurrently running
- Cadence: hourly narrative, daily authoring/evolution
- Additional: research layer (strategy lab, backtesting commentary, market digest), alert pipeline

### Token budget at full vision scale

| Layer | Description | Monthly input (M tok) | Monthly output (M tok) |
|-------|-------------|----------------------|------------------------|
| Narrative scoring | 500 symbols × hourly × 50% fresh rate | 162 | 63 |
| Strategy authoring | 100 bots × daily evolution | 22.5 | 7.2 |
| Research/lab LLM | Strategy ideation, market analysis, report generation | ~50 | ~15 |
| Alert/formatter | Structured alt data conversion | ~8 | ~3 |
| **Total** | | **~242.5** | **~88.2** | 
| **Grand total** | | | **~331M tokens/month** |

### Cost at full vision by model strategy

| Strategy | Narrative model | Authoring model | Research model | Monthly LLM cost |
|----------|----------------|----------------|----------------|-----------------|
| Ultra-cheap | GLM-4-Flash | DeepSeek V3 | Haiku 4.5 | **~$35/mo** |
| Budget-smart | DeepSeek V3 | Haiku 4.5 | Sonnet 4.6 | **~$260/mo** |
| **Recommended** | **DeepSeek V3** | **Sonnet 4.6** | **Sonnet 4.6** | **~$590/mo** |
| High-quality | Haiku 4.5 | Sonnet 4.6 | Opus 4.8 | **~$1,350/mo** |
| Maximum | Haiku 4.5 | Opus 4.8 | Opus 4.8 | **~$3,400/mo** |

**Recommended configuration:** Route narrative headline scoring (high volume, forgiving task) to DeepSeek V3 via OpenRouter. Route strategy authoring and research to Sonnet 4.6. Reserve Opus 4.8 calls for high-stakes one-shot decisions (e.g., a major regime change signal, quarterly strategy overhaul). At this split, full autonomous COSMU costs ~$590/month in LLM alone.

### Full operating cost at COSMU full vision

Building on `operating_costs.py` steady-state baseline:

| Component | Current R&D | Full Vision |
|-----------|-------------|-------------|
| Claude Max (coding agent) | $200/mo | $200/mo |
| Cursor Pro | $20/mo | $20/mo |
| Railway (backend) | $7.50/mo | $20–40/mo (more CPU, higher throughput) |
| LLM inference (OpenRouter/API) | $0–5/mo (Haiku+cache) | $590/mo (recommended split) |
| Modal (bursty compute) | ~$0 (free tier) | ~$30–80/mo (backtests, lab) |
| Supabase (data) | Free tier | $25/mo (Pro, pgvector) |
| Data feeds (LunarCrush, etc.) | ~$13/mo one-shot | ~$50–100/mo (expanded coverage) |
| **Total** | **~$240/mo** | **~$935–1,055/mo** |

The jump is almost entirely LLM inference at scale. The infrastructure is already production-ready.

### Revenue required to justify full vision

At $1,000/month operating cost:
- Break-even: **$1,000/month P&L** from deployed strategies
- Target: 5–10× cost coverage = $5,000–10,000/month P&L to justify the compute
- At 100 active bots with $100 average monthly P&L each → $10,000/month → **viable**
- At 10 active bots with $1,000 average monthly P&L each → $10,000/month → **viable**

The economics improve dramatically if narrative scoring migrates to self-hosted open source (GLM-4-9B on Modal serverless GPU), cutting the 162M narrative tokens from ~$40/mo down to ~$3/mo in serverless compute.

---

## 9. Practical Recommendations

### Immediate (today, 1 bot)

1. **Keep daily cadence** for the `llm-narrative-pressure-long` strategy. Sub-daily runs add noise, not signal.
2. **Current config is correct**: `openai/gpt-4o-mini` via OpenRouter at $0.15/$0.60 per MTok. Budget of $30/month handles hourly runs comfortably.
3. **Best upgrade path if signal quality disappoints**: swap narrative scoring model to `deepseek/deepseek-chat` on OpenRouter. Same API shape, 4× cheaper than gpt-4o-mini, better reasoning.

### Near-term (10 bots, scaling)

4. **Tiered model routing**: cheap model for scoring, better model for authoring. Already possible via OpenRouter's `openai/gpt-4o-mini` (scoring) + `anthropic/claude-haiku-4-5` (authoring) with separate model_id configs.
5. **Raise the monthly cap** from $30 → $75 to support 4-hour cadence on 10 symbols with Haiku authoring.
6. **Add `deepseek/deepseek-r1`** as an alternative authoring model when market conditions are ambiguous and you want explicit reasoning traces in the strategy proposal.

### Full vision (100 bots+)

7. **Migrate narrative scoring to Modal serverless GPU** (GLM-4-9B or Mistral 7B) — same quality for scoring, ~20× cheaper at volume.
8. **Keep authoring on Anthropic** (Haiku → Sonnet as quality bar rises). Pydantic reliability is worth the premium.
9. **Budget $590/month LLM** as the recommended operating target for full vision. This is the line item to optimize, not the infrastructure.
10. **Consider prompt caching** (Anthropic's cache-write tokens) for the long system prompts in `llm_narrative_pipeline.py` — the 300-token system prompt is reused every call, making it a natural cache candidate at 90% discount for cache reads.

---

## Appendix: Pricing Reference (2026-06-19)

| Model | Input $/1M tok | Output $/1M tok | Source |
|-------|---------------|----------------|--------|
| GLM-4-Flash | $0.01 | $0.05 | Zhipu AI platform |
| GLM-4-0520 std | $0.10 | $0.10 | Zhipu AI platform |
| GLM 5.2 (est.) | $2.00 | $8.00 | Estimated; not yet listed |
| Llama 3.1 8B | $0.10 | $0.10 | Together AI |
| Llama 3.1 70B | $0.65 | $0.65 | Together AI |
| Qwen 2.5 72B | $0.70 | $0.70 | Together AI |
| Mistral 7B | $0.20 | $0.20 | Together AI / Mistral |
| DeepSeek V3 | $0.14 | $0.28 | DeepSeek API |
| DeepSeek R1 | $0.55 | $2.19 | DeepSeek API |
| gpt-4o-mini | $0.15 | $0.60 | OpenAI / OpenRouter |
| gpt-4o | $2.50 | $10.00 | OpenAI / OpenRouter |
| o3 (GPT-5 proxy) | $10.00 | $40.00 | OpenAI |
| Claude Haiku 4.5 | $1.00 | $5.00 | Anthropic (2026-06-04) |
| Claude Sonnet 4.6 | $3.00 | $15.00 | Anthropic (2026-06-04) |
| Claude Opus 4.8 | $5.00 | $25.00 | Anthropic (2026-06-04) |
| Claude Fable 5 | $10.00 | $50.00 | Anthropic (2026-06-04) |
| Modal GPU (CPU) | $0.0000131/core/s | — | Modal (non-preemptible US/EU) |
| RunPod RTX 4090 | $0.34–0.69/hr | — | RunPod 2026 (Community/Secure) |
| RunPod A100 80GB | $1.49–1.99/hr | — | RunPod 2026 Secure Cloud |
| RunPod H100 PCIe | $2.89–3.29/hr | — | RunPod 2026 on-demand |

---

## 10. GLM-5.2 GGUF — Local Inference on RunPod

> Source: [unsloth/GLM-5.2-GGUF](https://huggingface.co/unsloth/GLM-5.2-GGUF) · [Unsloth docs](https://unsloth.ai/docs/models/glm-5.2)

### Reality check: GLM-5.2 is 744B parameters (MoE)

This is not a consumer model in any normal sense. GLM-5.2 is a Mixture-of-Experts architecture at 744B total parameters — in the same weight class as DeepSeek V3. Only a fraction of experts fire per token (~20-40B active params), but the full parameter set must be in VRAM (or CPU RAM with offloading) for inference.

### Quantization variants (unsloth dynamic GGUF)

| Quant | Disk size | Recommended VRAM / RAM | Quality retained | Throughput (est.) |
|-------|-----------|------------------------|-----------------|-------------------|
| UD-IQ1_S (1-bit dynamic) | ~217 GB | 223 GB RAM + 1× RTX 4090 (CPU offload) | ~76% | **2–3 tok/s** |
| UD-IQ2_M (2-bit dynamic) | ~239 GB | 256 GB RAM + 1× RTX 4090 (CPU offload) | ~82% | **2–5 tok/s** |
| UD-IQ2_M (full GPU) | ~239 GB | 3× A100 80GB (240 GB VRAM) | ~82% | **15–25 tok/s** |
| Q4_K_M (4-bit, lossless) | ~476 GB | 6× A100 80GB or 3× H100 80GB | ~99% | **25–50 tok/s** |
| FP16 (full precision) | ~1,510 GB | 20× A100 80GB | 100% | **cluster only** |

Unsloth's dynamic quantization ("UD") keeps attention and embedding layers at higher precision while compressing expert weights more aggressively — which is why quality retention is better than static quants at the same bit width.

### RunPod cost per setup

| Setup | GPUs | RunPod $/hr | Tok/s (est.) | Min viable for COSMU |
|-------|------|------------|-------------|----------------------|
| CPU offload (2-bit) | 1× RTX 4090 + 256GB RAM server | ~$2.50–4/hr | 2–5 | Too slow (hourly+ per cycle) |
| 3× A100 80GB (2-bit) | 3× A100 | ~$4.50–6/hr | 15–25 | Marginal (15–25 min/cycle) |
| 6× A100 80GB (Q4) | 6× A100 | ~$9–12/hr | 25–50 | OK (5–10 min/cycle) |
| 4× H100 80GB (Q4) | 4× H100 | ~$11.56/hr | 40–80 | Good (3–6 min/cycle) |
| 8× H100 80GB (Q4) | 8× H100 | ~$23.12/hr | 80–150 | Fast (1–3 min/cycle) |

> RunPod bills per second (no minimum). A100 Secure Cloud: ~$1.49–1.99/hr each. H100 PCIe: ~$2.89/hr each.

### Per-cycle compute cost (daily COSMU cycle, ~14,000 tokens)

Formula: `(model_load_time + generation_time) × RunPod_rate`

| Setup | Load time | Generation time | Total session | $/cycle | $/month (daily) |
|-------|-----------|----------------|--------------|---------|----------------|
| CPU offload 2-bit | n/a — model in RAM | ~2,800s (3,300 min!) | **not viable** | — | — |
| 3× A100 (2-bit) | ~120s | ~700s | ~820s | $1.03 | **$30.8/mo** |
| 6× A100 (Q4) | ~150s | ~350s | ~500s | $1.39 | **$41.7/mo** |
| 4× H100 (Q4) | ~130s | ~220s | ~350s | $1.12 | **$33.7/mo** |
| 8× H100 (Q4, fast) | ~120s | ~120s | ~240s | $1.54 | **$46.2/mo** |

> Load time assumes model on RunPod Network Volume (persistent NVMe), not re-downloaded each time. Cold download of 476GB would add 4–8 minutes and is not viable per-cycle.

### Monthly cost table: GLM-5.2 local (RunPod) vs API

This is the **same table** format as section 3, for GLM-5.2 specifically.

| Frequency | API (est. $2/$8 per MTok) | 3× A100 RunPod (2-bit) | 6× A100 RunPod (Q4) | 4× H100 RunPod (Q4) |
|-----------|--------------------------|----------------------|-------------------|-------------------|
| 15 min | $145/mo | ~$2,230/mo | ~$3,420/mo | ~$2,770/mo |
| 30 min | $81/mo | ~$1,480/mo | ~$2,270/mo | ~$1,840/mo |
| 1 hour | $47/mo | ~$748/mo | ~$1,148/mo | ~$930/mo |
| 4 hours | $14/mo | ~$185/mo | ~$284/mo | ~$230/mo |
| Daily | $2.57/mo | **$30.8/mo** | **$41.7/mo** | **$33.7/mo** |

> RunPod costs assume per-second billing with pod start/stop per cycle. At daily cadence, API is **12–16× cheaper** than RunPod self-hosted for GLM-5.2. At sub-daily frequencies the gap is extreme because each cycle's session overhead (load time) is repeated.

### The break-even scenario

Self-hosted GLM-5.2 only beats the API if:

1. **You already own the hardware** (GPU depreciation ≈ $0/hr). With owned 8× H100: power ~2.4kW at €0.20/kWh = €0.48/hr → ~$0.48/hr → $0.033/cycle → **$1.00/month at daily**. Cheaper than API. But 8× H100 costs ~$240,000 to buy.

2. **Shared infrastructure across 1,000+ bots**. At 1,000 bots running daily, the RunPod cluster is always busy and amortized:
   - 1,000 cycles/day × 500s/cycle = 138.9 GPU-hours/day on 6× A100
   - 138.9 / 24 = 5.8 dedicated 6×A100 pods ($9/hr × 24 = $216/day = $6,480/month)
   - vs GLM-5.2 API for 1,000 bots daily: ~$2,570/month
   - Still cheaper to use the API at 1,000 bots.

3. **Privacy requirement**: all LLM calls stay on your metal, no data leaves. This is the one legitimate reason to self-host at any scale.

### Practical verdict for COSMU

| Scenario | Recommendation |
|----------|---------------|
| 1 bot, any frequency | GLM-5.2 API ($2.57–$145/mo) — not RunPod |
| 10 bots, daily | GLM-5.2 API ($25.7/mo) vs 6× A100 ($41.7/mo) — API wins |
| 1,000 bots, daily | DeepSeek V3 API ($51.9/mo) — GLM-5.2 is overkill at this scale |
| Privacy-critical | Self-host, but use GLM-4-9B (single RTX 4090, $0.34/hr) not GLM-5.2 |
| Own hardware | Only worthwhile if 8× H100+ already deployed for other use |

**GLM-4-9B open source (9B params) is the practical GGUF story for COSMU** — not GLM-5.2. A 9B GGUF at Q4_K_M fits comfortably in a single RTX 4090 (24GB), runs at 80–150 tok/s, and costs $0.34–0.69/hr on RunPod. At daily frequency: 40 seconds per cycle → $0.004 per cycle → $0.12/month. That's better economics than the cheapest API tier.

| Model | GGUF size | GPU needed | RunPod $/hr | $/month (daily) | Quality |
|-------|-----------|-----------|------------|----------------|---------|
| GLM-4-9B (Q4_K_M) | ~5.4 GB | 1× RTX 4090 | $0.34–0.69 | **$0.12–0.23** | Good (narrative scoring) |
| Llama 3.1 8B (Q4_K_M) | ~4.7 GB | 1× RTX 4090 | $0.34–0.69 | **$0.12–0.23** | Good |
| Qwen 2.5 72B (Q4_K_M) | ~41 GB | 2× A100 40GB | $2.78–3.98 | **$0.95–1.35** | Very good |
| Llama 3.1 70B (Q4_K_M) | ~40 GB | 2× A100 40GB | $2.78–3.98 | **$0.95–1.35** | Strong |
| GLM-5.2 (UD-IQ2_M) | ~239 GB | 3× A100 80GB | $4.47–5.97 | **$30.8/mo** | Best open |
| GLM-5.2 (Q4_K_M) | ~476 GB | 6× A100 80GB | $8.94–11.94 | **$41.7/mo** | Best open, lossless |

For COSMU's narrative scoring task (forgiving, high volume): GLM-4-9B on a single RTX 4090 via Modal serverless is the optimal self-hosted path. GLM-5.2 is a legitimate choice only when you have a multi-GPU cluster already amortized across a larger workload.
