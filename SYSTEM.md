# SYSTEM

## 1. Purpose

This file is the current source of truth for the app.

It exists to keep the product direction, architecture, implementation posture, and active build scope clear enough that the system can evolve quickly without drifting into confusion or avoidable technical debt.

This file should stay:
- lean
- explicit
- practical
- easy to reread
- easy to edit by section
- easy to update as the product changes

This file should not become:
- a diary
- a changelog
- a vague vision statement
- a task tracker
- a duplicate of GitHub history

GitHub is the detailed implementation history.
This file keeps the current truth, the important reasoning, the current priorities, and the main information that must not be lost.

This file is editable later. When product direction, stack, or implementation posture changes, this file should be updated so it always reflects the current truth.

---

## 2. Snapshot

This app is a lean, prompt-driven autonomous trading platform built to run scheduled bots, let an LLM produce structured portfolio decisions, validate those decisions, execute them on Binance, and preserve a clear record of what happened and why.

The product exists to make money.

The product should not try to win through heavy infrastructure, excessive abstraction, or academic complexity. It should win through iteration speed:
- faster experimentation
- faster deployment
- faster prompt changes
- faster model changes
- faster feedback loops
- faster learning from live runs

The current official target is one serious live-capable bot with one clear autonomous loop.

The product is the beginning of a platform, but V1 must stay narrow in scope and strong in boundaries.

Current posture:
- TypeScript-first
- pnpm monorepo
- Node backend
- Next.js frontend
- Supabase Postgres
- Railway for backend and scheduling
- Vercel for the internal frontend
- GitHub for workflow and history
- Binance first
- spot only in V1
- testnet and live only in V1
- internal frontend first
- Slack only in V1
- REST market data as the current default for V1
- 3-phase pipeline: Research Agent → Trader Agent → Deterministic Validator/Executor
- internal MCP tool layer wrapping venue adapter calls
- LLM provider abstraction (swappable providers)
- per-LLM-call tracing via `run_llm_calls` table
- global kill switch for emergency halt

Why this posture:
- it is fast to ship
- easy to operate
- coherent across backend and frontend
- strong enough for a real V1
- light enough to avoid overbuilding

This product is a lean, prompt-driven autonomous spot trading platform that runs scheduled bots, lets an LLM produce structured portfolio decisions, validates and executes those decisions on Binance, records what happened clearly, and is designed so it can later support more bots, more providers, more venues, richer workflows, and future learning systems without forcing a rebuild.

The product exists to make money, but the first version is not judged primarily by returns. V1 is judged first by whether it produces a real, understandable, extensible autonomous trading loop with strong observability, strong traceability, and fast iteration.

The system should always be understood as both:
- a trading engine, which acts in live markets
- an iteration engine, which improves what acts by preserving comparable history across prompts, models, decisions, executions, and portfolio outcomes

---

## 3. How to read this file

Use these meanings consistently.

### 3.1 Locked
Official current truth. Do not change casually.

### 3.2 Current default
Preferred choice now. Use it unless there is a strong reason not to. It may change later.

### 3.3 Required now
Capability or rule required for the current build target.

### 3.4 Next
Likely near-term after the current target.

### 3.5 Later
Expected future candidate, but not currently committed.

### 3.6 Open
Possible future direction. Not committed. Not prohibited.

### 3.7 Avoid
Wrong direction under the current product logic. Avoid does not automatically mean forever impossible, but it does mean do not build it under the current rules.

---

## 4. Core locked principles

### 4.1 Business goal

Locked:
- the product exists to generate trading performance

Why:
- this is not a research project for its own sake
- this is not an exercise in building an elegant AI platform disconnected from outcomes

### 4.2 Product edge

Locked:
- the product should win through iteration speed

This means:
- fast prompt testing
- fast model switching
- fast deployment
- fast improvement from live runs
- fast removal of what does not work

Why:
- the intended edge is rapidity, not heaviness

### 4.3 V1 philosophy

Locked:
- V1 must be lean, serious, live-capable, understandable, auditable, and reusable as a foundation

Why:
- the system must not become either a throwaway bot or a giant hypothetical platform

### 4.4 Future-shaping rule

Locked:
- if a future idea is not required for the first live autonomous loop, it must not shape V1 beyond preserving clean boundaries

Why:
- future readiness should come from clean concepts and clean boundaries, not from building future complexity now

### 4.5 Historical leverage

Locked:
- every run should leave behind useful historical structure

Why:
- the product is both a trading engine and an iteration engine
- the system should compound knowledge over time

### 4.6 Reversibility

Locked:
- future-oriented modules should be easy to add, replace, disable, and remove

Why:
- extensibility without reversibility creates sticky complexity

---

## 5. Locked current truth

### 5.1 Product shape

Locked:
- V1 is an internal-use autonomous trading product
- V1 is one serious bot first
- V1 is one clear live-capable loop
- V1 uses prompt-driven reasoning
- V1 requires clear decision, validation, execution, and persistence discipline

Locked non-goals for V1:
- no full multi-venue platform
- no futures platform
- no deep research platform
- no heavy policy or manual risk platform
- no multi-agent orchestration platform
- no polished external consumer product

Why:
- one serious bot first is the smallest serious system that can go live and teach useful lessons

### 5.2 Stack posture

Locked:
- TypeScript-first
- pnpm monorepo with `apps/api`, `apps/web`, `packages/shared`
- Node backend
- Next.js frontend
- Supabase Postgres
- Railway for API, workers, and scheduler
- Vercel for internal frontend
- GitHub-centered workflow
- Python only later if justified by a specific need

Locked rule:
- shared business types live in `packages/shared`
- do not duplicate business types across backend and frontend

Why:
- this stack supports speed, coherence, shared contracts, and low operational drag

### 5.3 Frontend posture

Locked:
- the frontend is internal-first
- the frontend is an admin, control, and observability layer
- the frontend is also a rapid validation layer
- the frontend is not the product center of gravity in V1
- the frontend is not a consumer UX project in V1

Why:
- the frontend exists early to inspect system behavior quickly, especially when implementation is accelerated by AI tools

### 5.4 Frontend access posture

Locked:
- internal-only posture in V1
- lightweight protection is enough initially
- full product-grade auth is deferred until clearly needed

Current default:
- Vercel deployment protection or equivalent lightweight access control

Why:
- V1 should not be distorted by premature auth complexity

### 5.5 Venue and asset-class posture

Locked:
- Binance first
- spot only in V1
- no futures logic in V1
- no futures toggle in V1
- no futures adapter in V1
- `asset_class = 'spot'` must be stored on executions and portfolio snapshots
- `asset_class = 'spot'` should also exist in bot runtime configuration

Why:
- V1 stays narrow and realistic
- the historical record remains extensible later without painful migration

### 5.6 Provider posture

Locked:
- LLM providers are abstracted behind a common `LLMProvider` interface (`apps/api/src/providers/llm.ts`)
- providers expose a single `chat(input)` method returning `LLMResponse` with usage metrics
- prompts and model profiles must remain separate concepts
- new providers are registered via `registerProvider()` and resolved via `getProvider(name)`

Current default:
- xAI (Grok) as the starting provider (`apps/api/src/providers/xai.ts`)
- provider abstraction is in place — adding a new provider means implementing the `LLMProvider` interface and registering it

Why:
- provider flexibility is a first-class concern; swapping or adding providers should not require touching pipeline code

### 5.7 Bot and workflow posture

Locked:
- one bot first
- data model must still support multiple bots
- no hardcoded single-bot assumption in DB or API
- no watchdog loop in V1
- no multi-bot orchestration in V1
- no multi-step workflow in V1

Why:
- V1 should stay simple
- the data model should not force a rebuild later

### 5.8 Execution modes

Locked:
- V1 supports testnet and live only
- paper mode is excluded from V1

Testnet means:
- real exchange integration path
- no real funds

Live means:
- real orders
- real funds

Why:
- testnet exercises the real path without real capital
- live capability is part of V1 seriousness
- paper mode adds another operating path that is not the chosen V1 model

### 5.9 Notifications

Locked:
- Slack only in V1
- notification delivery must not block the run pipeline

Required events:
- trade opened
- trade closed
- run failure or critical error
- bot enabled or disabled

Why:
- notifications are operationally useful from V1, but should stay simple

### 5.10 Prompt versioning

Locked:
- prompts live in the database
- prompt edits create immutable prompt versions
- bots reference prompt versions
- runs record the exact prompt version used
- prompts must not live as mutable hidden strings in code

Why:
- prompt iteration is one of the main product engines
- comparison later requires exact historical traceability

### 5.11 Strategic direction

Locked:
- the product should keep V2-style simplicity as the backbone
- while preserving selected structural discipline from V1
- and avoiding both underbuilt chaos and overbuilt platform complexity

Why:
- the first version should stay focused on one clean autonomous loop
- but it should use enough separation and modularity that later additions feel like extension, not reconstruction

### 5.12 Build workflow posture

Current default:
- Cursor -> GitHub -> Vercel preview -> direct testing
- Railway for the always-on backend path

Why:
- much of the implementation may be AI-assisted
- fast preview-and-check cycles are strategically important
- the frontend exists early partly to validate what AI-generated or AI-assisted code actually does

---

## 6. Current defaults

These are current preferred implementation choices, not eternal laws.

### 6.1 Market data default

Current default:
- use REST for all market data in V1
- fetch balances, holdings, and prices at run start
- cache symbol metadata and exchange info lightly
- handle rate limits and 429s gracefully

Why:
- scheduled bot cadence does not justify current WebSocket complexity
- REST is simpler and sufficient for the current loop

Important nuance:
- REST-only is the current V1 default
- WebSocket is not part of the build now
- WebSocket is not forbidden forever
- if future requirements justify it, it should be added inside the adapter layer without changing the overall product model

### 6.2 Scheduler default

Current default:
- simple generic scheduling
- Railway cron or equivalent scheduled trigger
- no strategy logic in the scheduler

Why:
- scheduling should stay boring and predictable

### 6.3 Frequency default

Current default:
- 15-minute default frequency

Required supported values now:
- 1 minute
- 5 minutes
- 15 minutes
- 30 minutes
- 60 minutes

Why:
- frequency is an operational setting, not a prompt concern and not a scheduler hardcode

### 6.4 Provider default

Current default:
- xAI (Grok) via provider abstraction layer
- providers implement `LLMProvider` interface and are resolved by name at runtime

Why:
- one provider first reduces complexity
- provider abstraction is implemented — adding new providers is a single-file implementation task

### 6.5 UI ordering default

Current default V1 UI priority:
- portfolio and PnL first
- then run history
- then bot config
- then prompt management
- then logs

Why:
- portfolio state and execution understanding are the fastest way to validate whether the system is behaving sensibly

---

## 7. Canonical product model

The core product must think in internal business concepts, not raw exchange payloads.

Canonical concepts:
- `Bot`
- `Prompt`
- `PromptVersion`
- `ModelProfile`
- `RuntimeConfig`
- `Run`
- `Decision`
- `ValidationResult`
- `OrderIntent`
- `Execution`
- `PortfolioSnapshot`

Operational meaning:
- a bot is the trading actor
- a prompt defines how the bot thinks
- a prompt version is immutable historical instruction
- a model profile defines provider, model, and invocation settings
- a runtime config defines how the bot operates
- a run is one full decision cycle
- a decision is what the model proposed
- an execution is what the venue actually did

Locked rule:
- the Binance adapter translates `OrderIntent` into Binance requests and Binance responses into `Execution`
- nothing outside the adapter should depend directly on Binance-specific payload types

Why:
- venue payloads are implementation detail, not product truth

---

## 8. Single most important architectural rule

Locked:
- the system must clearly separate what the model decided from what the exchange actually executed

The following must remain distinct:
- prompt version
- model profile
- runtime context
- raw model output
- parsed structured decision
- backend validation result
- order intent
- venue execution result
- resulting portfolio state

Why:
- if this separation is lost, the system becomes hard to trust, hard to debug, hard to compare, and hard to extend

---

## 9. Required now: V1 capabilities

These are required capabilities for the current build target.

### 9.1 Autonomous run capability

Required now:
- determine when a bot is due
- trigger one full run
- persist the result of that run
- distinguish success, failure, and uncertain outcomes

### 9.2 Decision production capability

Required now:
- build compact runtime context
- call the model
- receive strict structured JSON
- validate the result with shared schema and Zod
- reject or retry invalid outputs

### 9.3 Execution capability

Required now:
- validate practical order correctness
- translate internal order intent to Binance
- attempt execution on Binance spot
- preserve raw venue responses
- distinguish model proposal from venue reality

### 9.4 Persistence capability

Required now, per run:
- bot identity
- runtime config used
- prompt version used
- model profile used
- compact context sent
- raw model output
- parsed structured decision
- validation result
- order intent(s)
- exchange submission / result
- raw venue response
- portfolio snapshot before run
- portfolio snapshot after run
- timestamps
- statuses
- error state if any

### 9.5 Observability capability

Required now:
- the operator can inspect what the bot did
- the operator can inspect why it did it
- the operator can inspect what was sent to the model
- the operator can inspect what came back
- the operator can inspect what the backend accepted or rejected
- the operator can inspect what the exchange executed
- the operator can inspect the resulting portfolio state

### 9.6 Prompt iteration capability

Required now:
- create prompts
- create prompt versions
- inspect prompt history
- assign prompt versions to bots
- switch active prompt versions
- record exact prompt version usage per run

### 9.7 Runtime control capability

Required now:
- runtime config includes at least enabled / disabled, venue, frequency, mode, asset class, and execution-related toggles when needed
- runtime behavior must live in runtime config, not in prompt text and not in scheduler logic

### 9.8 Mode distinction capability

Required now:
- preserve a real distinction between testnet and live
- mode must affect execution path, not just labeling

### 9.9 Notification capability

Required now:
- send Slack notifications for required V1 events
- notification failure must not block runs

### 9.10 Execution-economics capability

Required now:
- preserve fee amount
- preserve fee asset
- preserve gross PnL from snapshots
- preserve approximate net PnL from gross minus fees
- preserve slippage where reasonably possible

Why:
- otherwise the system can misclassify a weak strategy as profitable

### 9.11 Idempotency and reconciliation capability

Required now:
- reduce accidental duplicate live orders
- preserve enough information to reconcile after timeouts, retries, or uncertain exchange outcomes

### 9.12 Portfolio capability

Required now:
- the bot may manage a multi-position portfolio
- V1 is not limited to a single asset action
- structured decisions must support portfolio allocation thinking, not only isolated single-asset buy/sell actions

Why:
- the intended V1 decision model is portfolio-oriented, even though execution stays lean

---

## 10. Core autonomous loop

The v2 heartbeat is a 3-phase pipeline:

**Phase 0 — Scheduling & safety**
1. scheduler checks active bots
2. global kill switch is checked — if on, all bots are skipped
3. a bot is due

**Phase 1 — Research Agent** (`apps/api/src/services/pipeline.ts: runResearchAgent`)
4. system loads active prompt version, model profile, runtime config
5. system fetches wallet and market state via MCP tools
6. system builds compact context
7. LLM produces free-form research analysis (text)
8. candidate symbols are extracted from research text
9. LLM call is logged to `run_llm_calls` (provider, model, tokens, latency, attempt)

**Phase 2 — Trader Agent** (`apps/api/src/services/pipeline.ts: runTraderAgent`)
10. research output, market data, and portfolio state are assembled into trader prompt
11. LLM returns strict structured JSON decision (`TradingDecision` schema)
12. multi-strategy retry: tries json_schema → json_object → text, with temperature fallback
13. each LLM attempt is logged to `run_llm_calls`

**Phase 3 — Deterministic Validator/Executor** (`apps/api/src/services/validator.ts`)
14. global kill switch check (redundant safety)
15. venue authorization check
16. authorized pairs enforcement (when symbolScope is "selected")
17. existing validation: tradability, precision, lot size, wallet sufficiency
18. adapter translates to venue order requests via MCP tools
19. execution is attempted
20. full run trace is stored (decision, raw model output, executions, portfolio snapshots)
21. UI reflects latest state
22. Slack notifies important events

**MCP tool layer** (`apps/api/src/mcp/`)
- all venue interactions go through the internal MCP registry
- registered tools: `get_account`, `get_prices`, `get_symbols`, `get_exchange_info`, `execute_order`, `cancel_orders`
- tools are typed, registered at startup, and callable by name via `callTool(name, input, context)`

This is the product core.
Everything else is extension.

---

## 11. Decision, context, and validator rules

### 11.1 Decision contract

Required now:
- use strict structured JSON whenever the API supports it
- do not parse prose
- do not rely on regex
- do not rely on heuristic extraction
- validate the structure with Zod
- reject or retry invalid responses

The schema should be explicit and shared.

It should be rich enough for:
- decision mode such as rebalance / enter / exit / hold / adjust
- portfolio intent
- per-asset actions
- order preference
- optional limit price
- optional stop loss
- optional take profit
- confidence or conviction
- rationale summary
- global rationale
- optional time horizon

### 11.2 Model autonomy

Locked:
- the model should have broad freedom to choose tradable spot assets, actions, allocations, and stop-loss / take-profit logic

Responsibility split:
- model proposes
- backend validates
- exchange executes

Locked rule:
- the backend must not become a second strategy brain

### 11.3 Asset universe philosophy

Required now:
- no heavy allowed-universe engine
- no large manual filtering system
- the server verifies whether the selected asset is tradable now on the selected venue

Why:
- this is enough for V1 and avoids pointless complexity

### 11.4 Context philosophy

Locked:
- store more than you send

Required now:
- send compact relevant context only

Minimum context should include:
- balances and wallet state
- current spot holdings or positions
- current prices for held and candidate assets
- selected venue
- bot identity or role context
- active prompt version
- execution constraints or output schema

Default context should not include:
- giant logs
- huge raw histories
- automatic past-N-decision dumps
- bloated market dumps
- speculative memory payloads
- unnecessary JSON walls

### 11.5 Backend validator philosophy

Required now:
- the validator stays simple but strict

Its job is practical correctness, such as:
- asset tradability on Binance spot
- order type validity
- quantity, precision, and lot size validity
- wallet sufficiency
- mode compatibility
- submission success
- response trackability

Deterministic guardrails (non-LLM):
- global kill switch — halts all execution immediately when enabled
- venue authorization — only configured venues are allowed
- authorized pairs enforcement — when `symbolScope` is "selected", only whitelisted pairs pass
- these checks run before any existing validation logic

It must not become:
- a heavy rule engine
- a strategic decision-maker
- a large policy subsystem

---

## 12. Venue, market data, and execution rules

### 12.1 Venue architecture

Required now:
- small internal business vocabulary
- Binance adapter module
- server-side tradability and validity checks
- raw venue responses stored for debugging and audit

### 12.2 Rate-limit posture

Required now:
- respect Binance REST limits
- handle 429 responses with backoff
- cache static metadata lightly
- avoid repeated unnecessary metadata fetches per run

### 12.3 Execution safety posture

Required now:
- reduce accidental duplicate live orders
- support reconciliation after uncertain exchange outcomes
- preserve enough state to inspect what was attempted and what actually happened

### 12.4 Order capability posture

Required now:
- market orders
- limit orders
- a stop-loss / take-profit-capable decision structure when clearly needed by the intended first strategies

Current default:
- keep the execution layer lean
- only implement the order semantics actually needed for the first serious strategies

Important nuance:
- this does not require building a giant execution framework
- if stop-loss / take-profit behavior is needed, the adapter should translate internal intent into the most appropriate Binance-supported structure, including native mechanisms such as OCO or conditional-style order handling where applicable

---

## 13. Scheduling and runtime rules

### 13.1 Scheduler posture

Required now:
- scheduler determines which bots are due
- scheduler triggers runs
- scheduler records success or failure
- scheduler stays out of strategy logic

### 13.2 Runtime config posture

Locked:
- runtime behavior belongs in runtime config, not in prompt text and not in scheduler code
- bots are enabled by default upon creation
- bot names are optional (default to just "Bot #N")

Runtime config should include at least:
- enabled / disabled
- venue
- refresh frequency
- mode: testnet / live
- asset class: default `spot`
- execution-related toggles
- future optional flags when needed

### 13.3 UI-operable runtime posture

Next:
- normal operational controls should be available per bot from the UI

This should include:
- enabled / disabled
- refresh frequency
- active prompt version
- active model profile
- mode: testnet / live
- bot-level execution toggles that are part of normal operation

Locked rule:
- secrets and infrastructure-level configuration must remain environment-based and must not be editable from the UI

---

## 14. Data model and persistence rules

### 14.1 Data posture

Locked:
- the database should be small, serious, and useful

It should support:
- auditability
- replayability
- debugging
- comparison
- historical leverage
- future retrieval or ML opportunities

It should not become speculative or bloated.

### 14.2 Minimum serious V1 entities

Required now:
- `prompts`
- `prompt_versions`
- `model_profiles`
- `bots`
- `bot_runtime_configs`
- `runs`
- `decisions`
- `executions`
- `portfolio_snapshots`
- `run_llm_calls` — per-LLM-call tracing (phase, provider, model, tokens, latency, attempt, strategy, error)
- `app_settings` — key-value store for global settings (e.g. `global_kill_switch`)
- `venue_prompt_versions` — venue-specific prompt versions (e.g. formatter prompts per venue)

Required asset-class posture:
- `bot_runtime_configs.asset_class = 'spot'`
- `executions.asset_class = 'spot'`
- `portfolio_snapshots.asset_class = 'spot'`

### 14.3 Historical leverage posture

Locked:
- run history is a strategic asset, not just logging

Every run should help answer:
- what the model saw
- what it proposed
- what the backend accepted
- what the venue executed
- what happened after
- which prompt version was used
- which model profile was used
- which setup worked better over time

### 14.4 Future learning posture

Locked:
- V1 does not build ML, retrieval, or learning systems

Required posture:
- do not build those systems now
- do preserve enough structure so they remain possible later without rebuilding the core data layer

Additional learning posture:
- prefer simpler approaches first
- only add heavier learning systems when they clearly justify their complexity
- do not write the architecture in a way that artificially closes off approaches that may become practical later

---

## 15. Dashboard and observability rules

### 15.1 Observability posture

Locked:
- observability is a major product requirement

The operator must be able to inspect:
- what the bot did
- why it did it
- what was sent to the model
- what came back
- what the backend accepted or rejected
- what the exchange executed
- what the resulting state became

### 15.2 Why the dashboard exists early

Locked:
- the dashboard exists early to improve observability, debugging, confidence, control, and iteration speed
- it is also a rapid validation layer for AI-generated or AI-assisted changes

### 15.3 Minimum V1 read capabilities

Required now:
- view list of bots
- view enabled or disabled status
- view refresh frequency
- view active prompt version
- view active model profile
- view mode: testnet / live
- view last run status
- view latest decision summary
- view latest orders or executions
- view current holdings or positions
- view recent PnL or portfolio state
- view logs or recent errors
- view prompt version history

### 15.4 Minimum V1 editing capabilities

Next:
- the dashboard should let the operator manage prompts, prompt versions, model selection, frequency, enabled state, testnet / live mode, and bot assignment of prompt / model / config

Locked rules:
- mode visibility must be clear
- switching to live should require strong confirmation

---

## 16. Next

These are likely near-term additions after the first serious end-to-end loop.

Next:
- UI controls for prompt version management
- UI controls for model switching
- UI controls for frequency editing
- UI controls for testnet / live switching
- better run inspection details
- clearer execution inspection
- richer Slack summaries
- stronger operator control and iteration speed

These are next because they improve operation and iteration speed directly, not because they change the core product logic.

---

## 17. Later and Open

These are future directions, not current implementation instructions.

Later:
- prompt-to-prompt comparison views
- model-to-model comparison views
- cleaner history navigation
- more bots
- more providers
- more venues
- futures or other asset classes
- reviewed workflow mode per bot
- policy layer
- retrieval
- learning-oriented modules
- advanced strategy comparison
- other notification channels
- community indicators
- ML-heavy experiments
- optional external agent-assisted modules

Open:
- Hyperliquid
- KuCoin
- Polymarket or other non-standard venues
- OpenAI
- Claude
- OpenRouter
- agentic research helpers
- richer multi-step workflows
- model distillation
- reinforcement-style learning
- optional harness-assisted workflows

Important rule:
- these items influence boundaries
- they do not silently expand the present scope
- they are not instructions to implement now

---

## 18. Avoid

These are structural mistakes under the current product logic.

Avoid:
- overbuilding for hypothetical future needs
- large abstractions for workflows that do not exist yet
- mixing Binance-specific logic with core business logic
- fusing model output with execution result
- unversioned prompts
- hardcoded runtime behavior in code paths
- scheduler logic mixed with strategy logic
- weak run or execution traceability
- UI becoming the place where core business rules live
- raw Binance payloads used as internal product types
- discarded fee data
- missing raw model output or raw venue response in run records
- hardcoded single-bot assumptions in the data layer
- premature enterprise auth or permission systems
- speculative signal frameworks in V1
- Telegram or Discord notifications in V1
- paper mode added as a third V1 mode

Important nuance:
- Avoid is not the same as Later
- Avoid is not the same as Open
- Avoid is not the same as Next
- WebSocket is not in Avoid
- WebSocket is simply not the current default for V1

---

## 19. Optional future workflow flexibility

Locked:
- the default V1 loop is single-step because that is the fastest path to a serious live system

Later:
- a bot may support direct mode or reviewed mode

If reviewed mode is introduced later:
- it should be configurable per bot
- main reasoning prompt and model should remain selectable
- review prompt and model should remain selectable
- final structured decision should still pass through the same validation and execution path
- research output, reviewed decision output, validation result, execution result, and resulting portfolio state must remain clearly separate

Why:
- workflow flexibility should remain possible later without distorting V1 now

Later, per-bot workflow control should remain possible from the internal UI.

This should allow, when relevant later:
- choosing whether a bot runs in direct mode or reviewed mode
- choosing which prompt version and model profile power the main reasoning step
- choosing which prompt version and model profile power the review layer, if reviewed mode exists

Why:
- workflow flexibility should remain a per-bot option, not a platform-wide forced pattern

---

## 20. External agents and core guarantees

Locked:
- the platform must not depend on external agent harnesses for its core guarantees

Core guarantees must remain native:
- scheduling
- persistence
- decision traceability
- validation
- execution tracking
- auditability

Open later:
- optional external agent layers may support research, monitoring, reporting, context enrichment, or experimentation

Locked rule:
- such layers must remain optional and pluggable, not foundational

Important nuance:
- the system should not be written as if external agent-based tooling were forbidden forever
- such tooling may later help with research, monitoring, reporting, context enrichment, or experimentation
- but core guarantees must remain native to the platform itself

---

## 21. Open implementation decisions

These are open implementation decisions, not open philosophy.

Open implementation decisions currently include:
- exact first decision schema cut and which fields are mandatory vs optional
- exact first order capability cut beyond market, limit, and simple SL/TP structure
- exact persistence normalization level for runs, fills, snapshots, and raw payloads
- exact idempotency and reconciliation mechanism
- exact first dashboard information architecture
- exact retry policy for LLM failure, schema failure, and exchange uncertainty
- exact model profile granularity
- exact API route breakdown and service boundaries
- exact first serious test strategy
- exact policy for promoting a future direction from Later to Next or Required now

Cursor may propose concrete solutions here, as long as locked principles are respected.

---

## 22. Current success definition

V1 is successful when:
- a bot runs autonomously on schedule
- it uses a prompt version and model profile cleanly
- it produces structured decisions
- the backend validates correctly
- it executes properly on Binance spot
- the operator can use testnet or live appropriately
- the system records each run clearly and completely
- the UI makes the system understandable
- prompt and runtime iteration are fast
- Slack notifications fire on key events
- the codebase remains lean, modular, and adaptable

Second-level success:
- every run increases historical leverage
- prompts become comparable
- model behavior becomes comparable
- decisions become comparable
- execution history becomes interpretable
- the system compounds knowledge instead of producing chaos

Important nuance:
- exceptional returns are not the first success condition of V1
- the first success condition is a real, understandable, extensible autonomous trading loop
- financial performance remains the ultimate business goal, but V1 should first optimize the preconditions for sustainable performance: live capability, disciplined execution, interpretability, and iteration speed

---

## 23. Cursor operating rules

### 23.1 Maintain this file correctly

When something changes:
- update only the affected block
- do not rewrite the whole file
- do not flatten unchanged principles
- keep wording explicit where ambiguity would cost time later
- keep wording tight where extra verbosity adds no protection

This file can be edited later and should be kept current.

### 23.2 Git rule

After each meaningful edit or small coherent set of edits:
- commit
- push immediately

Do not let important local changes remain uncommitted or unpushed for long.

Why:
- GitHub is the detailed implementation history
- frequent pushes reduce drift and make progress visible
- small coherent commits are easier to understand and roll back than large delayed commits

### 23.3 External docs rule

When working with external APIs, SDKs, libraries, platforms, services, or apps:
- check current official documentation first
- verify current behavior before implementing assumptions
- do not rely only on memory for evolving tools
- prefer primary sources over summaries when implementation details matter

Examples:
- Binance -> Binance official docs
- xAI -> xAI official docs
- Supabase -> Supabase official docs
- Railway -> Railway official docs
- Vercel -> Vercel official docs
- Next.js -> Next.js official docs
- pnpm -> pnpm official docs

Why:
- external tools change
- implementation details drift
- current docs reduce avoidable mistakes

### 23.4 Scope rules

Do not silently expand scope.

Do not treat:
- Later as Avoid
- Open as committed
- Next as fully specified implementation detail
- Current default as eternal law
- future-ready as permission to overbuild now

### 23.5 Maintenance rules

When a completed capability leaves active build focus:
- keep it in `SYSTEM.md` only if it remains part of the app’s current operating truth
- otherwise remove it from `SYSTEM.md`
- let GitHub keep the detailed history

### 23.6 Architecture rules

Always preserve:
- decision vs execution separation
- internal types vs venue payloads
- prompt vs model vs runtime config separation
- lean validator scope
- lean scheduler scope
- frontend as internal admin and observability tool
- run traceability
- raw output preservation
- fee preservation
- asset-class preservation on executions and portfolio snapshots
- no hardcoded single-bot assumptions in the data layer

### 23.7 Build-order rule

Do not build a separate "Phase 0" foundation project.

The first meaningful deliverable should be a real end-to-end autonomous loop.
Foundation pieces should be built as part of that loop, not as an abstract preliminary platform.

Why:
- the product learns fastest from a real loop
- abstract infrastructure built too early tends to over-expand and lose relevance