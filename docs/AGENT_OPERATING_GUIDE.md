# Agent Operating Guide

## Mission

Help Cosmu become a modular autonomous research and trading platform without breaking the current Light trading loop.

## Rules for Future AI Agents

- Read `SYSTEM.md`, `ARCHITECTURE.md`, `docs/AGENTIC_PLATFORM_PLAN.md`, and `docs/DECISIONS.md` before major edits.
- Keep Light behavior stable unless the user explicitly asks for trading behavior changes.
- Prefer small, observable changes over hidden framework rewrites.
- Every new background task should have a frontend-visible status and an audit trail.
- Use Postgres-backed state for product memory before adding opaque vector/retrieval systems.
- Never put secrets in frontend-editable config.
- Never couple live trading to external reference repos.
- Run `pnpm typecheck` and `pnpm build` before handing off when feasible.

## Preferred Patterns

- TypeScript orchestrates product workflows.
- Python is allowed for isolated Research jobs only.
- New live venues must start as data/paper adapters before execution.
- Agent tools must be permissioned by role.
- Research outputs should be structured enough to compare, reject, and promote.

