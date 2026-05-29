# Cosmu Agent Map

This is the mandatory pre-prompt for coding agents in this repo. Keep it lean and current. If this file grows past roughly 200 lines, prune stale memory before adding more.

## Mission
Cosmu is an internal investment operating system. Preserve the working core: create agents, ingest data, observe markets, standardize signals, run research, make decisions, execute through explicit venues, and review outcomes.

Primary product flow:

```text
Source -> Record -> Signal -> Research -> Strategy -> Decision -> Execution -> Outcome
```

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
- `Venue`: actual trading or market venue, for example `Binance`, `Binance Testnet`, `IBKR`, or `Polymarket`.
- `AgentStep`: audited model/tool phase.

Show the actual venue name in product UI. Avoid generic labels such as paper, live mode, or testnet mode. Existing DB values may keep older names temporarily for compatibility, but new UI and docs should use venue-first language.

## Module Map
- Web app: `apps/web/app`. Dashboard, agent creation/editing, Signals, Research, Settings, optional modules.
- API: `apps/api/src`. Express routes, services, store modules, background jobs, venue adapters.
- Shared contracts: `packages/shared/src/index.ts`. Zod schemas, app defaults, public types. Change carefully.
- Venues/execution: `apps/api/src/adapters`, `apps/api/src/services/validator.ts`, execution stores, positions, snapshots.
- Signals/data: `apps/api/src/routes/signals.ts`, `apps/api/src/lib/store/signals.ts`, `raw_observations`, `standardized_signals`.
- Research: `apps/api/src/routes/research.ts`, `apps/api/src/research`, `apps/api/src/lib/store/research*.ts`, `apps/web/app/research`.
- Settings/secrets: `apps/web/app/settings`, app settings stores. Secrets stay in env, not DB.
- TradingAgents reference: `apps/trading-agents` wrapper and `TradingAgents-main` upstream copy. Do not couple live runtime to upstream internals.

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
- [venues] Show actual venue names such as `Binance` and `Binance Testnet`. Avoid generic paper/live/testnet mode labels in product UI.
- [data] Preserve raw source payloads/provenance when practical; derived signals, indexes, and reviews should be recomputable.
- [research] Research can use tools and venue data, but execution still goes through the validator and venue adapter.
- [secrets] API keys, exchange keys, and provider secrets stay in `.env.local` locally and server env in deployments.
- [agents] Keep edits scoped. The code is the source of detail; this file is only the map and invariant memory.
