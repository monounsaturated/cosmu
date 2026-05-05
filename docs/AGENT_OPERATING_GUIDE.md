# Agent Operating Guide

## Mission

Help Cosmu become a modular autonomous research and trading platform without breaking the current Light trading loop. The end goal is full automation: Cosmu Pro proposes hypotheses, tests them in Research, promotes what survives review, trades within capped limits, reviews outcomes, and self-improves. The path there is incremental and reversible.

## Mode Segregation (do not break)

- A bot's `workspace_mode` (`light` | `research` | `pro`) decides which workspace can see and act on it. `BotTable` filters by this column.
- Light is a quick-iteration tool. Light bots never appear in Research or Pro.
- Research bots are paper-only on `binance-testnet`. They appear only in the Research workspace.
- Pro bots only exist by promotion from a Research candidate, gated by an `approval_requests` row. They appear only in the Pro workspace.
- Promotion path is one-directional: Research → approval inbox → Pro. Approval creates a Pro bot with `execution.enabled = false`; a human still has to enable trading.

## Rules for Future AI Agents

- Read `SYSTEM.md`, `ARCHITECTURE.md`, `docs/AGENTIC_PLATFORM_PLAN.md`, and `docs/DECISIONS.md` before major edits.
- Keep Light behavior stable unless the user explicitly asks for trading behavior changes.
- Never let Research place live orders. Research bots stay on `binance-testnet`.
- Never bypass the deterministic validator, the global kill switch, or the approval gate.
- Prefer small, observable changes over hidden framework rewrites.
- Every new background task must have a frontend-visible status and an audit trail (`agent_steps` for product-level traces).
- Use Postgres-backed state for product memory before adding opaque vector/retrieval systems.
- Never put secrets in frontend-editable config.
- Never couple live trading to external reference repos (TradingAgents, autoresearch, MemPalace, Hermes Agent are pinned references — wrap, do not import into the live runtime).
- Run `pnpm typecheck` and `pnpm build` before handing off when feasible.

## Preferred Patterns

- TypeScript orchestrates product workflows.
- Python is allowed for isolated Research jobs only.
- New live venues must start as data/paper adapters before execution.
- Agent tools must be permissioned by role.
- Research outputs should be structured enough to compare, reject, and promote.

## Toward Full Autonomy

When extending Cosmu, optimize for the autonomous Pro end state:

- New observability primitives should be cheap to read by other agents (Postgres rows, structured JSON, not opaque blobs).
- New approval types should follow the `approval_requests` pattern so a future scheduler can introspect and prioritize them.
- Promotion thresholds, capped auto-live policies, and post-trade self-review hooks should be configured from the frontend — never hard-coded.
- Treat the human approval step as a default that an explicit, frontend-visible policy could one day relax — never as something the code silently routes around.
