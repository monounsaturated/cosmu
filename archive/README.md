# Archive: the Cosmu engine and cockpit (v1)

This folder holds the full system, built between April and July 2026. Its autonomous loop kept running
until August 13, 2026, and it is no longer deployed. The landing page at the repo root showcases it. The
exact pre-archive tree is also tagged `v1-engine-archive`.

**What it did** (from its production database, see `apps/web/lib/engine-stats.json`):

1. **3,661 strategies** written and tested: 1,733 on price alone, 1,928 on other data (887 on-chain
   flow, 752 macro and positioning, 276 social sentiment, 13 news and events).
2. **146,059 backtests** (strategy × market × venue) across 66 markets on Binance, Kraken and
   Polymarket, **2.3 million** simulated trades.
3. **335** survived the first screen. **11** earned paper trading. **3,464** dead ends kept on record.
4. **14.8 million** point-in-time data points: 1.1M in Postgres and 13.7M in a Parquet lake on
   Cloudflare R2.

**Where to start reading:** `docs/reports/edge-sprint-synthesis-2026-06-25.md` (why every tested idea
died), `docs/reports/phase0-carry-verdict.md` (pass criteria written before the run),
`apps/engine/cosmu/research/gate.py` and `apps/engine/cosmu/master/fdr.py` (the judge), `AGENTS.md`
(the rules the AI agents worked under).

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

**Run the engine's tests** (no keys, no network; the full suite has ~3,200 tests, so start small):

```bash
cd archive/apps/engine
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest tests/test_fdr_parity.py     # the false-discovery-rate control, ~2 s
```

The exact pre-archive tree, with its own root scripts, is at the tag:

```bash
git checkout v1-engine-archive
```
