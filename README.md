# Cosmu

**Turn any headline into a backtest.** Ask in plain English ("what if I'd bought Nvidia every time a big
AI model launched?"). Cosmu finds the matching news, tests it on real prices with your broker's fees, and
tells you whether it beat random timing.

This repo holds the landing page (`apps/web`) and the research harness behind its examples
(`scripts/landing`). The earlier engine (deterministic statistical gate, paper trading, point-in-time
data) is kept in [`archive/`](archive/) and at the tag `v1-engine-archive`.

## Run

```bash
pnpm install
pnpm dev          # landing page on http://localhost:3000
pnpm verify       # typecheck + static build → apps/web/out
```

## Research

```bash
pnpm research     # every idea through one harness, ranked
pnpm demo:data    # export the ideas shown on the page → apps/web/lib/showcase.json
```

Every idea runs the same way: buy at the close of the first trading day after the news broke, sell 20
trading days later, subtract costs, then compare against the same asset bought on 10,000 random sets of
dates. Prices are real Yahoo Finance daily closes (2020–2025, dividends included). Event dates are
hand-curated from public reporting.

Research tool, not investment advice.
