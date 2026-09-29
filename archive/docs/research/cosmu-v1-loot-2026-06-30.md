# COSMU v1 → v2 LLM-lane loot (2026-06-30)

**Task:** read the old COSMU **v1** app, extract what's worth looting for v2's **LLM strategy
lane** (`kind='llm'` AgentSpec), and map each idea to where it fits in v2. **Store + learn only —
no reimplementation, no risk to v2.** This is a research note; nothing here is wired.

**Verdict in one line:** v2's *contract and architecture are already better* (typed `AgentSpec`/`Decision`,
mandatory exit policy, risk-machine sizing, symbol×venue, multi-venue adapters, observe-only/human-armed).
The loot is **operational**, concentrated in five places v1 actually shipped and v2 has only *specced*:
(1) the xAI **live-browse research** path + its hard-won endpoint quirks, (2) the **anti-hallucination
grounding block**, (3) **heavy per-LLM-call observability**, (4) the **live execution safety belt**
(guardian + reconciliation + atomic run-claim + idempotency + peg guard), (5) **agentic tool-loop
robustness**. Everything else is LEAVE — v2 already does it cleaner.

---

## 0. Where v1 lives

- **Path:** `<repo> light/` — a *separate sibling folder* (not inside the v2 repo), its
  own git repo (`04c1835 edit kill switch`), authored **Apr 13 – May 5 2026**, predating v2's first
  commits (late May). The operator made a new folder for v2; v1 was left intact. Confirmed v1.
- **Stack:** TypeScript pnpm monorepo — `apps/api` (Node backend), `apps/web` (Next.js internal
  dashboard), `apps/mcp-server`, `packages/shared` (Zod contracts). Supabase Postgres, Railway
  (always-on + cron), Vercel (internal UI), Binance spot only, testnet+live (no paper).
- **Source-of-truth docs inside v1:** `SYSTEM.md` (36 KB product truth) and
  `ARCHITECTURE.md` ("non-obvious things the code relies on" — the single most useful file to read).

### What v1 actually was (the operator's memory, confirmed)

A lean, prompt-driven autonomous **spot trader**. One run = a **3-phase pipeline**, scheduled at a
chosen frequency:

```
scheduler tick / "Run Now"
  │  (global kill switch checked; atomic run-claim dedups double-fire)
  ▼
Phase 1  RESEARCH AGENT   — prompt #1, free-form text, xAI Responses API with web_search + x_search
  │      (live-browses X/web; candidate tickers regex-extracted from the prose)
  ▼
Phase 2  TRADER AGENT     — prompt #2, agentic tool-use loop (≤6 iters), returns strict JSON Decision
  │      (calls binance_symbol_lookup for canonical pair + live price to size SL/TP)
  ▼
Phase 3  VALIDATOR / EXECUTOR — DETERMINISTIC, no LLM: kill-switch, venue auth, tradability/lot/
         notional/balance; invalid ORDERS dropped, decision rejected only on kill/unknown-venue;
         Binance adapter places MARKET/LIMIT (+ OCO/safety-stop); full trace persisted
  ▼
Guardian loop (separate 10 s tick) — app-side SL/TP enforcement + boot-time safety-stop reconcile
Slack notifier (fire-and-forget) · heavy per-run + per-LLM-call observability UI
```

The "**two prompts**" the operator remembers = **Research** (prompt #1) + **Trader** (prompt #2).
The validator is deterministic, not a third prompt. There was also a **per-venue "formatter" prompt**
(`venue_prompt_versions`) used as the trader fallback.

v1 key files: `apps/api/src/services/{run-bot,pipeline,validator,guardian,kill-bot,prompt-context}.ts`,
`apps/api/src/providers/{xai,llm,tool-adapters}.ts`, `apps/api/src/mcp/`, `apps/api/src/adapters/binance.ts`,
`apps/api/src/lib/store/*`, `packages/shared/src/index.ts`, `apps/web/app/**`.

---

## 1. The loot table (ranked by value to v2)

| # | Loot | v1 source | v2 destination | Verdict |
|---|------|-----------|----------------|---------|
| **A** | **Live xAI browse + endpoint reality** (Responses-API `x_search`/`web_search`; `live_search`-on-Chat is **deprecated**; output/usage shapes) | `providers/xai.ts`, `ARCHITECTURE.md §"xAI provider quirks"` | [data/sources/xai_twitter.py](apps/engine/cosmu/data/sources/xai_twitter.py), [lab/llm.py](apps/engine/cosmu/lab/llm.py), [mind/news_intel.py](apps/engine/cosmu/mind/news_intel.py) | **LOOT (cross-check now)** |
| **B** | **Anti-hallucination grounding block** (inject today's date; forbid citing un-retrieved prices/tweets; demand timestamps; "honest short beats fabricated detailed") | `prompt-context.ts:RESEARCH_GROUNDING_BLOCK` | [mind/source_trust.py](apps/engine/cosmu/mind/source_trust.py), [mind/claims.py](apps/engine/cosmu/mind/claims.py), [data/sources/xai_twitter.py](apps/engine/cosmu/data/sources/xai_twitter.py) | **LOOT (drop-in)** |
| **C** | **Heavy per-LLM-call observability** (phase, provider/model, tokens, latency, attempt, strategy, **toolCalls input/output**, iterations) + the run-detail inspection UI (phase blocks, structured-vs-raw prompt, labeled injected-data, validation banner) | `lib/store/llm-calls.ts`, `apps/web/app/bots/[botId]/run-detail.tsx`, `run-detail-row.tsx` | agent-trace replay specced in [docs/epics/agentic-lane.md §9](docs/epics/agentic-lane.md); records via [strategy/agent_executor.py](apps/engine/cosmu/strategy/agent_executor.py) (`_record_decision`) | **LOOT (fills specced gap)** |
| **D** | **Live execution safety belt** — guardian loop (app-side SL/TP + boot reconcile), atomic run-claim, idempotent client-order-ids + "uncertain"/reconcile, USDC/USDT peg guard | `services/guardian.ts`, `lib/store/bots.ts:claimRun`, `adapters/binance.ts` | [adapters/exec/](apps/engine/cosmu/adapters/exec/) (binance/kraken), the live order path, the Modal cron fleet | **LOOT (for live-arm, step 6)** |
| **E** | **Agentic tool-loop robustness** — bounded iters (≤6), `tool_choice:auto`, JSON fallback chain (`json_object`→`no_format`), `extractJson` fence/brace strip, `DecisionParseError` keeps raw text; `binance_symbol_lookup` returns price+filters so the LLM sizes SL/TP on truth | `pipeline.ts:runTraderAgent`, `providers/xai.ts:runXaiAgentLoop`, `mcp/tools/binance-symbol-lookup.ts` | [lab/llm.py](apps/engine/cosmu/lab/llm.py) (already does structured+retry+offline), a future live tool-calling Mind seam | **LOOT (partial — graft the gaps)** |
| **F** | **MCP-shaped local tool registry + multi-provider tool adapters** (`ToolDefinition`, `agentFacing`, `callTool`; `toOpenAI/Anthropic/Gemini`) | `mcp/index.ts`, `mcp/types.ts`, `providers/tool-adapters.ts` | [adapters/exec/registry.py](apps/engine/cosmu/adapters/exec/registry.py); any tool-calling Mind | **ADAPT (pattern only)** |
| **G** | **Slack fire-and-forget notifier** + the event set (trade open/close, run failure, bot enable/disable, guardian give-up) | `services/notifier.ts` | [cosmu/notify/](apps/engine/cosmu/notify/) | **ADAPT (likely already have)** |

---

## 2. Loot detail (what / why / where)

### A — Live xAI browse + the endpoint reality  **[LOOT — cross-check now]**

**What v1 did.** Research and trader hit **different xAI endpoints on purpose**
(`ARCHITECTURE.md §"xAI provider quirks"`):

> Research calls `runXaiResearchWithBrowsing` against `/v1/responses` with `web_search` + `x_search`
> **server tools** so the model can actually browse. Trader uses `/v1/chat/completions` via
> `runXaiAgentLoop` because that's where OpenAI-style **function** tools work.
> **Do not add server tools to Chat Completions.** `x_search`/`web_search` are **Responses-API only**;
> **`live_search` is deprecated**. Sending them yields `422 unknown variant`.

Responses-API text extraction: prefer `response.output_text`, else walk
`response.output[].content[]` for `type==="output_text"`. Usage is **snake_case** under
`response.usage.{input_tokens, output_tokens}` (different shape from Chat Completions).

**Why it matters to v2.** v2 *already ingests xAI X-data* but via **Chat-Completions LiveSearch**:
[data/sources/xai_twitter.py](apps/engine/cosmu/data/sources/xai_twitter.py) sets
`_XAI_BASE_URL="https://api.x.ai/v1"`, `_XAI_MODEL="grok-3-mini"`, queries
`"BTC OR ETH OR crypto market sentiment -is:retweet lang:en"` and comments "queries the xAI
LiveSearch API". v1's note says `live_search` on Chat is *deprecated* and real browsing lives on
`/v1/responses`. **This is a live risk for v2's authority/voices/sentiment lanes** — the X-search
path could be on a deprecated surface. Loot = v1's documented endpoint map; **action = verify v2's
xAI X-search against current xAI docs** (Chat Completions now uses a `search_parameters` extension;
`web_search`/`x_search` server tools are Responses-API). Don't let v2 silently degrade to `[]`.

**Where in v2.** The Mind's live-read seam: [mind/news_intel.py](apps/engine/cosmu/mind/news_intel.py),
[data/sources/xai_twitter.py](apps/engine/cosmu/data/sources/xai_twitter.py),
[lab/llm.py](apps/engine/cosmu/lab/llm.py) (which already pins `XAI_URL` to Chat Completions). When the
LLM lane needs *live browse* (the operator's pump.fun-live / realtime-GPT ambition), use the
Responses-API browse path, not a deprecated Chat tool.

---

### B — The anti-hallucination grounding block  **[LOOT — drop-in, highest ROI]**

**What v1 did.** `prompt-context.ts:RESEARCH_GROUNDING_BLOCK`, appended to **every** xAI research
system prompt:

```
GROUNDING RULES (critical — your output feeds live trading decisions):
• Today's date is {YYYY-MM-DD}. Any cited news, tweet, or price MUST come from a search you actually
  ran this turn — you have web_search and x_search tools available.
• For ANY claim about recent prices, news, tweets, or market events: call a search tool first.
  Never cite a date, username, or headline you did not just retrieve.
• If a search returns no results / tools are unavailable, say so explicitly ("unable to retrieve
  live data for X") and do NOT invent content. A short, honest report beats a detailed fabricated one.
• When quoting tweets/posts, include the exact retrieved timestamp. When citing prices, state source
  and time. Do not round timestamps to "today" unless they actually are today.
```

The commit note records *why*: **"Without it, Grok confidently fabricates tweets with plausible past
dates (observed 2024-dated fake tweets in 2026 runs before this was added)."**

**Why it matters to v2.** v2's [xai_twitter.py](apps/engine/cosmu/data/sources/xai_twitter.py) fixture
tweets are literally dated `2024-01-01` — the exact fabrication failure mode. v2's defenses are
*structural* (ABSTAIN when no analyst has data in [agent_loop.py](apps/engine/cosmu/strategy/agent_loop.py);
source-trust scoring) but there is **no prompt-level grounding guard** when an LLM browses live. This
is the cheapest, highest-leverage loot — a ~6-line prompt constant.

**Where in v2.** The LLM-strategy guardrails / creation_playbook surface and the live-read prompt
builders: [mind/source_trust.py](apps/engine/cosmu/mind/source_trust.py),
[mind/claims.py](apps/engine/cosmu/mind/claims.py), and any prompt that feeds Grok/LLM live text
(authority ingestion, voices, news_intel). Make "honest-degradation > fabrication" a *prompt*
invariant, mirroring the *structural* ABSTAIN invariant v2 already holds.

---

### C — Heavy per-LLM-call observability  **[LOOT — fills the specced agent-trace replay]**

**What v1 did.** Every LLM attempt (success *or* failure) persisted via
`lib/store/llm-calls.ts:storeLLMCall`: `runId, phase (research|trader), provider, model,
inputMessages (jsonb), outputText, inputTokens, outputTokens, latencyMs, attempt, strategy, error`.
Trader records embed the **full `toolCalls` array (name, input, output, latency, error)** and
**`iterations`** inside `input_messages` jsonb; the UI reads them back via `-> 'toolCalls'` /
`-> 'iterations'`. The run-detail UI (`apps/web/app/bots/[botId]/run-detail.tsx`,
`run-detail-row.tsx`) shows:

- a **pipeline ribbon**: Research → Trader → Validator blocks, each with tokens + latency, colored
  by phase / red on fail; plus totals;
- a **Structured ↔ Raw** toggle: structured view labels the *injected-data sections*
  (SESSION / WALLET / TRADING SCOPE / PORTFOLIO / PERFORMANCE / EXECUTION RULES / LIVE PRICES) and
  separates "written prompt" from "injected data"; raw view shows the unsplit prompts;
- a **validation banner** listing dropped-order issues;
- per-call cards: phase · provider/model · in/out tokens · elapsed · attempt# · strategy · error,
  with expandable **tool calls** (input/output/latency).

**Why it matters to v2.** This is the "**HEAVY observability of what the LLM was doing**" the operator
remembers — and v2's epic ([§9](docs/epics/agentic-lane.md)) *specs exactly this* as P5
"agent-trace replay (steps · analyst debate · sources · disconfirmers · admission · fill)" and ranks
Observability as **build-sequence step 2** ("$0, immediate value, lets us *see* while building").
Today v2 records a decision payload + `trace[]` strings as one audit event
([agent_executor.py](apps/engine/cosmu/strategy/agent_executor.py) `_record_decision`) — good, but
**no per-call token/latency/attempt/tool-IO telemetry** and no inspection UI at v1's depth. v1 is a
ready blueprint for that step.

**Where in v2.** Schema: extend the knowledge store events (or a dedicated `llm_calls`-style table) to
capture per-call telemetry alongside the existing `agent_decision`/`agent_abstain` events. UI: the
front is "monitoring not creation" — the run-detail ribbon + structured/raw + tool-IO drill-down maps
onto the agent-trace replay page. Keep v2's `trace[]` (it's the analyst-panel reasoning) and **add**
v1's call-level telemetry around it.

---

### D — The live execution safety belt  **[LOOT — for the live-arm, build step 6]**

v2's agentic lane is **observe-only today** (zero capital). When DAA/VAA/ADM (or a degen/snipe lane)
*arms live*, v1's robustness is directly relevant. Pieces:

1. **Guardian loop** (`services/guardian.ts`): a separate ~10 s tick that loads active positions,
   pulls fresh tickers per mode, and fires an app-side **market sell** when price crosses SL/TP — SL
   checked first (more conservative). SL/TP are **not** trusted to the exchange alone; they're enforced
   in-app *and* backed by an exchange-side "safety stop". Guards: `inFlight` re-entry lock,
   `CLOSE_BACKOFF_MS` (60 s) between retries, `MAX_CLOSE_ATTEMPTS` (5) then **give up + Slack alert**.
2. **Boot-time safety-stop reconciliation** (`reconcileSafetyStops`): on startup, for each position with
   a `safety_stop_order_id`, query Binance — if it **filled while the app was down**, record the
   execution + close the position; if cancelled/expired, clear the ref. (Survives restarts/deploys.)
3. **Atomic run-claim** (`lib/store/bots.ts:claimRun`): a single
   `UPDATE … WHERE last_run_started_at IS NULL OR last_run_started_at <= now() - (frequency*60 - 10s)
   RETURNING id`. If another tick source (internal loop, cron, manual) already claimed the window,
   `runBot` bails `{status:"skipped"}`. **The UPDATE *is* the claim** — no separate `last_run_at` write.
4. **Idempotent orders + "uncertain"** (`adapters/binance.ts:executeOrders`): `newClientOrderId` derived
   from the run id (`runId(20)-index`); a failed/timeout submit is recorded as **`status:"uncertain"`**
   (never silently lost) so it can be reconciled; the run status becomes `uncertain` if any leg is.
5. **USDC/USDT peg guard** (`ensureStableQuoteLiquidity`): before a buy short on the target stable,
   market-swap via `USDCUSDT` **only if the peg is within 0.2 % of 1:1**; otherwise abort the swap and
   let the exchange reject. Never trade into a broken peg.

**Why it matters to v2.** v2 has backtest/paper exit-tools (trailing-SL/ATR, #375) and a paper-twin,
but the *live* loop needs: enforce-don't-trust SL/TP, survive a restart mid-position, never
double-fire across the Modal cron fleet (which already has a heartbeat dead-man's-switch), never lose
an uncertain fill, and never swap stables into a depeg. These are exactly the failure modes that bite
on day one of real money.

**Where in v2.** [adapters/exec/binance.py](apps/engine/cosmu/adapters/exec/binance.py) +
[adapters/exec/kraken.py](apps/engine/cosmu/adapters/exec/kraken.py), the live order path, and the
Modal cron orchestration. Adopt: the atomic-claim idempotency, the uncertain+reconcile status, and a
guardian/reconcile equivalent **before** the first live arm. (Caveat: v1 is Binance-spot specific —
the *patterns* port; the venue mechanics don't.)

---

### E — Agentic tool-loop robustness  **[LOOT — partial; graft the gaps]**

**What v1 did.** `pipeline.ts:runTraderAgent` + `providers/xai.ts:runXaiAgentLoop`: a bounded tool-use
loop (`maxIterations = 6`, `tool_choice:"auto"`); each iteration runs tool calls, pushes
`{role:"tool", …}` results, loops; finish reasons `stop` / `tool_iterations_exhausted` / `empty`.
Strict JSON forced via a **fallback chain**: attempt 1 `response_format:{type:"json_object"}`, attempt
2 no format; `extractJson` strips ```` ```json ```` fences and leading prose before the first `{`; a
parse failure throws `DecisionParseError` **carrying the raw text** (so the bad output is inspectable,
not discarded). The `binance_symbol_lookup` tool returns the **canonical pair + current price +
minQty/minNotional/tickSize/stepSize** so the LLM sizes SL/TP against *ground truth*, not a guess.

**Why it matters to v2.** v2's [lab/llm.py](apps/engine/cosmu/lab/llm.py) already does the important
half — structured proposal + Pydantic validation + retry + offline fallback + secrets-server-side. The
loot is the *agentic* extras for when the Mind gets a **live tool-calling** seam: bounded iterations,
the JSON-fence/brace `extractJson` robustness, keeping the raw text on parse failure, and the
**"give the LLM authoritative filters/price so it fills validated slots correctly"** pattern
(`binance_symbol_lookup`). The latter is the cleanest expression of "the LLM fills only validated
slots": don't let it invent a tick size — hand it the real one.

**Where in v2.** [lab/llm.py](apps/engine/cosmu/lab/llm.py) (graft `extractJson` + raw-on-failure),
and a future tool-calling Mind seam ([mind/thinker.py](apps/engine/cosmu/mind/thinker.py) /
[mind/analysts.py](apps/engine/cosmu/mind/analysts.py)). The exec adapters already hold the venue
filters — expose a read-only "resolve symbol → price + filters" helper for the LLM context.

---

### F — MCP-shaped tool registry + multi-provider adapters  **[ADAPT — pattern only]**

`mcp/index.ts` + `mcp/types.ts`: `ToolDefinition {name, description, inputSchema?, agentFacing?,
execute(input, ctx)}`; `register()`, `callTool(name, input, ctx)` (returns `{output, latencyMs,
error}`), `getAgentFacingTools()` exposes only `agentFacing:true` tools to the model.
`providers/tool-adapters.ts` converts one internal schema to OpenAI / Anthropic / Gemini wire shapes
("add a provider = write one adapter, reuse all tools"). v2 has its own registry
([adapters/exec/registry.py](apps/engine/cosmu/adapters/exec/registry.py)); the loot is just the
*shape* (latency/error captured per call; agent-facing vs internal split; one-schema-many-providers) if
v2 ever exposes engine tools to a tool-calling LLM.

---

### G — Slack fire-and-forget notifier  **[ADAPT — likely already have]**

`services/notifier.ts`: `try { postToSlack(text) } catch { log }` — a Slack outage can never block a
run. Events: trade opened/closed, run failure, bot enabled/disabled, **guardian gave-up**. v2 has
[cosmu/notify/](apps/engine/cosmu/notify/); worth confirming the same fire-and-forget discipline and
the guardian-give-up alert exist for the live lane.

---

## 3. What to LEAVE (v2 is better — do **not** regress)

| v1 thing | Why LEAVE it | v2's better answer |
|----------|--------------|--------------------|
| **Binary order-drop validator** (invalid order silently dropped; buys *must* carry SL/TP or dropped) | Drop = lost alpha; the operator is a "risk machine" | [agent_decision.py](apps/engine/cosmu/strategy/agent_decision.py) **sizes down** thin/low-conf signals (never discards) + mandatory exit on every Decision, not just buys |
| **LLM "formatter" prompt per venue** (`venue_prompt_versions`) to shape order params | An LLM shaping tick/lot/notional invites hallucinated params + leakage | v2 formats orders **deterministically** per venue in [adapters/exec/](apps/engine/cosmu/adapters/exec/) (binance/kraken/polymarket/alpaca). Keep venue *constraints as context*, never let the LLM emit final params |
| **Two-prompt research→trader chain** | A single linear chain | v2's **Mind analyst panel + injected judge** ([mind/analysts.py](apps/engine/cosmu/mind/analysts.py), [agent_loop.py](apps/engine/cosmu/strategy/agent_loop.py)) is a richer, testable, pure-function consensus; offline-by-default, cheap LLM at runtime |
| **Separate research/trader/formatter prompt-version tables + restore UI** | Prompt sprawl | v2: a strategy is "**mostly a natural-language summary**" — one `AgentSpec.rationale`, versioned via `strategy_versions` |
| **Single venue (Binance spot), testnet+live only, paper excluded** | Narrow | v2 is **multi-venue** (symbol×venue product axis) + has a **paper-twin** forward-test and human-armed live |
| **TradingDecision Zod schema** (mode/orders[]/targetAllocations) | Fine, but flatter | v2's `Decision` adds `entry_low/high` validity zone, `trace[]`, per-decision exit override, `size_request` clamped by unified caps; exit is *first-class mandatory* |
| **Regex ticker extraction** `[A-Z]{2,10}USD[TC]` from prose | Brittle, USD-pair only | v2 reasons over an explicit `symbols` list per AgentSpec; no prose-scraping |
| **"store more than you send" context discipline** | Good principle | already v2 doctrine (PIT alt-data store; compact context to the model) |

**Hard rule:** the loot must not drag v1's narrowness (Binance-only, drop-don't-size, LLM-formats-orders,
prompt sprawl) back into v2. Take the *operational mechanics*, leave the *shape*.

---

## 4. Suggested sequencing (propose-only — nothing built here)

1. **B (grounding block)** — minutes, $0, drop-in to the LLM live-read prompts. Do first.
2. **A (xAI endpoint cross-check)** — verify [xai_twitter.py](apps/engine/cosmu/data/sources/xai_twitter.py)
   isn't on a deprecated Live-Search surface; pin the correct endpoint per xAI's *current* docs.
3. **C (observability)** — aligns with epic build-step 2; add per-LLM-call telemetry + the trace-replay
   UI. Highest "lets us see while building" value.
4. **E (tool-loop robustness)** — graft `extractJson` + raw-on-failure + symbol-resolve-for-sizing when
   the Mind gets a live tool-calling seam.
5. **D (live safety belt)** — gate to build-step 6 (first live arm): atomic claim, uncertain+reconcile,
   guardian/reconcile, peg guard. Do **before** real money, not after.

---

## 5. Pointers

- v1 product truth: `<repo> light/SYSTEM.md`
- v1 non-obvious mechanics (read this): `<repo> light/ARCHITECTURE.md`
- v2 LLM-lane design: [docs/epics/agentic-lane.md](docs/epics/agentic-lane.md)
- v2 LLM contract: [strategy/agent_spec.py](apps/engine/cosmu/strategy/agent_spec.py)
- v2 reasoning/dispose: [strategy/agent_loop.py](apps/engine/cosmu/strategy/agent_loop.py),
  [strategy/agent_decision.py](apps/engine/cosmu/strategy/agent_decision.py),
  [strategy/agent_executor.py](apps/engine/cosmu/strategy/agent_executor.py)
