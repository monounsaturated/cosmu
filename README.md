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
pnpm research          # event ideas through one harness, ranked
pnpm research:spikes   # news-volume spike ideas (GDELT), ranked
pnpm demo:data         # export the page's data → apps/web/lib/showcase.json
```

Every idea runs the same way: buy at the close of the first trading day after the news broke, hold a
fixed period (events: 1 month; news spikes: 2 weeks), subtract costs, then compare with the same asset
bought on 10,000 random sets of dates drawn from the same years. An idea passes only with at least 10
events and a result better than 95% of those random draws. Of 26 ideas tested, 1 passed (layoff-news
spikes → Nasdaq). Prices: Yahoo Finance daily closes (2020–2025, dividends included). News volume: GDELT.
Big-event dates are hand-curated from public reporting.

Research tool, not investment advice.
