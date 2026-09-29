# Archive: the Cosmu engine and cockpit (v1)

This folder holds the full system built between April and July 2026. It's no longer deployed. The
landing page at the repo root showcases it. The exact pre-archive tree is also tagged `v1-engine-archive`.

| Path | What it is |
|------|------------|
| `apps/engine/` | Python 3.12 FastAPI engine: strategy compiler, backtester, deterministic gate (deflated Sharpe, CSCV-PBO, holdout, regime folds, cohort BH-FDR), paper clock, 5-interlock live execution, 11+ point-in-time data sources, ML survival/regime models, the "Mind" analyst panel. ~3,200 tests. |
| `apps/engine/strategies/inbox/` | 419 typed strategy specs authored for the gate. |
| `apps/web-cockpit/` | Next.js operator cockpit (Iris Bento design system): strategies screener, paper and live wallets, costs, keys. |
| `packages/contracts-ts/` | TypeScript types generated from the engine's OpenAPI schema. |
| `mcp/` | MCP servers that let Claude read engine state (read-only; no tool moves money). |
| `skills/` | 28 Claude Code playbooks (create-strategy, run-gate, fan-out, …) used to drive the build with parallel agents. |
| `docs/` | Master plan, architecture, decisions, lessons, and the research reports (incl. the failed carry verdict and the defensive TAA pass). |
| `tooling/` | Old scripts, git hooks, CI workflows, env templates, devcontainer. |
| `AGENTS.md` | The original agent entry doc: invariants and the non-negotiables. |

Nothing here runs from the root workspace. To revive it, check out the tag:

```bash
git checkout v1-engine-archive
```
