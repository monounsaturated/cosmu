# ARCHITECTURE — non-obvious things the code relies on

A one-pass reference for humans and LLMs. `SYSTEM.md` holds product truth; this file holds
implementation specifics that are easy to forget and hard to rediscover from the code alone.

## Pipeline shape

One run = Research → Trader → Validator → Execution, orchestrated in
[apps/api/src/services/run-bot.ts](apps/api/src/services/run-bot.ts).

- **Research** ([pipeline.ts:runResearchAgent](apps/api/src/services/pipeline.ts)) — free-form text, no tools, no structured output.
- **Trader** ([pipeline.ts:runTraderAgent](apps/api/src/services/pipeline.ts)) — agentic: runs a tool-use loop via [xai.ts:runXaiAgentLoop](apps/api/src/providers/xai.ts), must return strict JSON matching `tradingDecisionSchema`. Up to 6 tool iterations.
- **Validator** ([services/validator.ts](apps/api/src/services/validator.ts)) — deterministic, non-LLM. Invalid *orders* are silently dropped (added to `issues` as `"Dropped SYMBOL side: reason"`); the whole decision is only rejected for kill-switch / unknown venue.
- **Execution** ([adapters/binance.ts:executeOrders](apps/api/src/adapters/binance.ts)) — places MARKET/LIMIT, then OCO (LIMIT_MAKER above / STOP_LOSS_LIMIT below) for SL/TP on buys.

## Triple-run / double-fire protection

Runs are atomically claimed in [lib/store/bots.ts:claimRun](apps/api/src/lib/store/bots.ts): a single `UPDATE … WHERE last_run_started_at IS NULL OR last_run_started_at <= now() - (frequency_minutes*60 - 10s) RETURNING id`. If another tick source (internal 15s loop, Railway cron, manual trigger) already claimed the window, `runBot` bails with `{runId:null, status:"skipped"}`. **Do not** add a separate "last_run_at" write anywhere — the UPDATE is the claim.

Kill-mode liquidation ([services/kill-bot.ts](apps/api/src/services/kill-bot.ts)) skips `claimRun` because `killBot` disables the bot *first*, so the scheduler can't race it.

## USDT / USDC agnosticism

Cash = USDT + USDC at 1:1. Non-obvious details:

- [adapters/binance.ts:lookupBinanceSymbols](apps/api/src/adapters/binance.ts) accepts bare base (`NEIRO`) or either pair (`NEIROUSDT`, `NEIROUSDC`) and returns a canonical `{symbol, quoteAsset}`. USDT preferred, USDC fallback. **The trader must place orders using the returned `symbol`, not its input** — this is enforced only by prompt discipline, not by code, so keep the prompt nudge in [services/prompt-context.ts](apps/api/src/services/prompt-context.ts).
- Pre-trade swap in [adapters/binance.ts:ensureStableQuoteLiquidity](apps/api/src/adapters/binance.ts): before a buy, if the target stable is short but the other stable covers the shortfall, market-swap on `USDCUSDT` (BUY to acquire USDC, SELL to acquire USDT). A **0.2% peg guard** aborts the swap silently — we accept the small spread when it exists but never trade into a broken peg. If the swap fails we still attempt the order and let the exchange reject on insufficient balance.
- Logical balances ([lib/logical-balances.ts](apps/api/src/lib/logical-balances.ts)) merge USDT+USDC into one `usdt` field; base-asset stripping handles `USD[TC]$`. Fees paid in either stable are deducted from cash.
- Dashboard aggregation ([services/dashboard.ts](apps/api/src/services/dashboard.ts)) prices held assets via `priceMap[BASEUSDT] ?? priceMap[BASEUSDC] ?? 0`, so a coin that only trades against USDC still values correctly.

## xAI provider quirks

Live implementation in [apps/api/src/providers/xai.ts](apps/api/src/providers/xai.ts).

- **Research and trader use different xAI endpoints.** Research calls [xai.ts:runXaiResearchWithBrowsing](apps/api/src/providers/xai.ts) against `/v1/responses` with `web_search` + `x_search` server tools so the model can actually browse. Trader uses `/v1/chat/completions` via [xai.ts:runXaiAgentLoop](apps/api/src/providers/xai.ts) because that's where OpenAI-style function tools work (our `binance_symbol_lookup` is a local function tool).
- **Do not add server tools to Chat Completions.** `x_search` / `web_search` are Responses-API only; `live_search` is deprecated. Sending them yields `422 unknown variant`. `XAI_SERVER_TOOLS` is intentionally empty and gated — leave it that way on the trader path.
- Responses-API text extraction: prefer `response.output_text`, fall back to walking `response.output[].content[]` for `type === "output_text"` parts. Usage lives at `response.usage.{input_tokens, output_tokens}` (snake_case — different shape from Chat Completions).
- `x_search` is xAI-specific (not in the OpenAI SDK's `Tool` union), so the tools array is cast to `any` when passed through.
- Anti-hallucination guard: [prompt-context.ts:RESEARCH_GROUNDING_BLOCK](apps/api/src/services/prompt-context.ts) is appended to every research system prompt. It injects today's date and forbids citing prices/tweets/news that weren't just retrieved via the tools. Without it, Grok confidently fabricates tweets with plausible past dates (observed 2024-dated fake tweets in 2026 runs before this was added).

## MCP tools (local registry, MCP-shaped)

Registered at startup in [apps/api/src/mcp/index.ts](apps/api/src/mcp/index.ts). Agent-facing tools are auto-exposed to the trader via `getAgentFacingTools()` in [pipeline.ts:buildAgenticTools](apps/api/src/services/pipeline.ts). **To add a new tool**: create a `ToolDefinition` with `agentFacing: true`, register it, and update its prompt hint in [services/prompt-context.ts](apps/api/src/services/prompt-context.ts). No provider-side wiring needed — shape-adapters in [providers/tool-adapters.ts](apps/api/src/providers/tool-adapters.ts) handle OpenAI/Anthropic/Gemini formats.

## LLM call tracing

Every LLM attempt (success or failure) is persisted via [lib/store/llm-calls.ts:storeLLMCall](apps/api/src/lib/store/llm-calls.ts). Trader-phase records store the full `toolCalls` array (name, input, output, latency, error) and iteration count inside `input_messages` as jsonb — the UI reads these back via `-> 'toolCalls'` / `-> 'iterations'` in the same file.

## Things that will bite you

- `normalizeSymbol` strips non-alphanumerics but does **not** uppercase base asset — downstream code already uppercases; don't duplicate.
- `validateTradability` uses `venueContext.symbolRules[symbol]` as ground truth. A symbol missing there fails hard — always ensure it's included via `derivedSymbols` in [loadVenueContext](apps/api/src/adapters/binance.ts).
- OCO placement is best-effort: failure is logged but does not fail the parent buy. If you need hard SL/TP guarantees, audit this.
- Slack notifications are fire-and-forget via [services/notifier.ts](apps/api/src/services/notifier.ts) — a Slack outage cannot block a run, by design.
