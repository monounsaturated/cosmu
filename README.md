# Cosmu

**Ask a trading question in plain English and get an honest, fee-aware answer.**

Cosmu turns a natural-language idea into a typed strategy, backtests it on real prices and real news net
of every fee, and lets a deterministic statistical gate (not the AI) decide whether the edge is real.

This repo is now the **landing page** for that project. The full engine lives in [`archive/`](archive/)
and at the tag `v1-engine-archive`.

## What was built (Apr–Jul 2026)

- **361** merged PRs · **1,322** commits · **3,181** automated tests · ~**97k** lines of Python
- A deterministic funding gate: deflated Sharpe, CSCV-PBO, untouched holdout, regime folds and a
  cohort-level Benjamini-Hochberg FDR, so generating more ideas can't manufacture a winner
- 11+ point-in-time data sources (GDELT news, Reddit, X, Polymarket, FRED, funding, on-chain…)
- Paper trading on real prices, each strategy on its own track; live trading behind 5 interlocks
- Built by directing parallel Claude Code agents (one branch each, merge train, 28 runnable skills)

Honest results are part of the story: a pre-registered crypto funding-carry strategy **failed** the gate
and was dropped. Three defensive asset-rotation strategies **passed** it unchanged.

## The landing page

`apps/web`: a static Next.js site (no backend), deployable on Vercel's free tier.

```bash
pnpm install
pnpm dev          # http://localhost:3000
pnpm verify       # typecheck + static build → apps/web/out
```

The demo ("buy 1 share of CIBR every time a major hack makes national news, 2021–2025") uses **real**
daily closes. Regenerate it with:

```bash
pnpm demo:data    # scripts/landing/build_cibr_demo.py → apps/web/lib/cibr-hacks.json
```

Research project, not investment advice.
