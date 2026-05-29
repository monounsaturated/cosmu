# Cosmu Agent Map

This is the mandatory pre-prompt for coding agents in this repo. Keep it lean and current. If this file grows past roughly 200 lines, prune stale memory before adding more.

## Mission
Cosmu is an internal investment operating system. Preserve the working core: create bots, ingest data, observe markets, standardize signals, run research, make decisions, execute through explicit venues, and review outcomes.

Primary product flow:

```text
Source -> Record -> Signal -> Index -> Research -> Strategy -> Decision -> Execution -> Outcome
```

There is one kind of agent: a **bot** (the Cosmu trading bot). No light/research/pro workspace modes — bots differ only by `venue` and whether execution is enabled.

## Read Order
1. Read this file first.
2. Identify the module involved from the map below.
3. Use `rg` / `rg --files` to inspect exact code paths.
4. Read only the files needed for the task.
5. Expand scope only when imports, shared schemas, or failing tests prove it is necessary.

Do not crawl the whole repo by default. Do not do broad cleanup while fixing a narrow issue.

## Vocabulary
- `Source`: provider, tool, feed, or API that returns data.
- `Record`: captured source data with provenance, timestamp, raw payload, and content hash when practical.
- `Signal`: standardized interpretation of one or more records.
- `Research`: synthesis, test, or experiment workflow using records, signals, datasets, and tools.
- `Strategy`: reusable investment/trading idea or policy.
- `Decision`: agent output before validation and execution.
- `Execution`: venue order, fill, fee, position, and venue response.
- `Outcome`: result, PnL, fees, review, and lesson.
- `Index`: scheduled bot that monitors Sources and applies a standardized prompt to quantify a topic over time. Derived view over Signals, not a new raw store. (Future hook — not built yet.)
- `Venue`: actual trading or market venue, for example `Binance`, `Binance Testnet`, `IBKR`, or `Polymarket`.
- `AgentStep`: audited model/tool phase.

Use the actual venue name everywhere — UI, code, and DB. The only venue concepts are `Binance` (`binance`) and `Binance Testnet` (`binance-testnet`). Never use generic labels such as paper, live mode, or testnet mode.

## Module Map
Each `services/`, `lib/store/`, `adapters/`, `providers/`, and `research/` file starts with a one-line `// module:` memo — read that first to know what it does before opening the file.

- Web app: `apps/web/app`. Dashboard, bot creation/editing, Signals, Research, Settings, optional modules.
- API: `apps/api/src`. Express routes, services, store modules, background jobs, venue adapters.
- Shared contracts: `packages/shared/src` (barrel at `index.ts`, split by domain: `venue`, `trading`, `signals`, `research`, `agent`, `settings`). Zod schemas, app defaults, public types. Change carefully.
- Venues/execution: `apps/api/src/adapters`, `apps/api/src/services/validator.ts`, execution stores, positions, snapshots.
- Signals/data: `apps/api/src/routes/signals.ts`, `apps/api/src/lib/store/signals.ts`, `raw_observations`, `standardized_signals`.
- Research: `apps/api/src/routes/research.ts`, `apps/api/src/research`, `apps/api/src/lib/store/research*.ts`, `apps/web/app/research`.
- Settings/secrets: `apps/web/app/settings`, app settings stores. Secrets stay in env, not DB.
- Shelved reference: `TradingAgents-main` (vendored OSS) and `apps/trading-agents` wrapper are set aside — do not read, crawl, or couple runtime to them.

## Data Rules
- Raw external information should become a `Record` before it is reused.
- Interpreted information should become a `Signal`.
- Strategies should consume records, signals, datasets, and venue context, not UI state.
- LLM/tool work should leave `AgentStep` or `run_llm_calls` traces.
- Money state belongs in executions, positions, and portfolio snapshots.
- Derived outputs should be reproducible from stored records/signals/context.
- Future indexes are derived views over signals, not a new raw-data system.

## Current Trading Flow
The current loop is valid and should not be broken:

```text
Research prompt -> source/tool calls -> research output -> trader prompt -> Decision -> validator -> Execution
```

Improve it incrementally by storing reusable source data as records and standardized interpretations as signals.

## Stop Conditions
Stop and report before:
- broad renames or product vocabulary changes;
- DB/schema changes unless explicitly requested;
- destructive commands or data resets;
- touching unrelated modules;
- changing live execution behavior;
- moving secrets into DB or frontend-editable config;
- coupling live trading to external reference repos.

## Verification
- Web changes: `pnpm --filter @cosmu/web typecheck`.
- API changes: `pnpm --filter @cosmu/api typecheck`.
- Shared/schema changes: `pnpm typecheck` when practical.
- UI changes: verify desktop and mobile widths in the browser when the dev server is available.

## Repo Memory
- [venues] Venue is the single source of truth for testnet vs live: `binance` = live, `binance-testnet` = testnet. There is no separate execution-mode field. Show actual venue names everywhere.
- [data] Preserve raw source payloads/provenance when practical; derived signals, indexes, and reviews should be recomputable.
- [research] Research can use tools and venue data, but execution still goes through the validator and venue adapter.
- [secrets] API keys, exchange keys, and provider secrets stay in `.env.local` locally and server env in deployments.
- [agents] Keep edits scoped. The code is the source of detail; this file is only the map and invariant memory.
