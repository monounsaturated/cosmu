# Cosmu

**Your AI trading analyst. Most trading ideas lose money: know before yours does.** Describe any
strategy in plain English, numbers ("buy Bitcoin after a 10% crash") or news ("buy defense stocks when a
war breaks out"). Cosmu tests it on real prices, with your broker's fees, against 10,000 random entry
dates, and gives a straight verdict.

**Live:** https://cosmu.vercel.app

## What's in this repo

| Path | What it is |
|------|------------|
| `apps/web` | The landing page: static Next.js, no backend, deployed on Vercel. |
| `scripts/landing` | The research harness behind the page's examples: 53 news and event ideas, one method. |
| `archive/` | The engine that came first: AI-authored strategies, backtests on point-in-time data, a deterministic statistical gate, per-strategy paper trading, live execution behind 5 locks. Also at tag `v1-engine-archive`. |

## By the numbers: the archived engine, June to August 2026

Aggregates from its production database, snapshotted by `scripts/landing/engine_stats.py` into
[`apps/web/lib/engine-stats.json`](apps/web/lib/engine-stats.json):

| | |
|---|---|
| Strategies written and tested | **3,661**, 53% of them on non-price data (on-chain flows, positioning and macro, social sentiment, news) |
| Backtests (strategy × market × venue) | **146,059** across 66 markets and 3 venues, 1-minute to daily bars |
| Simulated trades | **2.3 million** |
| Survived the first screen / earned paper trading | **335 / 11** |
| Dead ends kept on record | **3,464** |
| Point-in-time data collected | **14.8 million** data points, 72 metrics, 23 providers |

Almost nothing survived real costs and the luck tests. That result is the product: the valuable part was the
judge, not the robot.

## How it was built

With Claude Code agents working under written rules ([`archive/AGENTS.md`](archive/AGENTS.md)): the AI
proposes, deterministic code decides, and no language model sits in the scoring or money path. The
research reports in [`archive/docs/reports/`](archive/docs/reports/) record the decisions, including the
ideas that failed.

## Run

Needs Node 22+, pnpm 10 and Python 3.10+ (the research scripts use only the standard library).

```bash
pnpm install
pnpm dev          # landing page on http://localhost:3000
pnpm verify       # typecheck + research tests + static build → apps/web/out (CI runs this too)
```

## Research

```bash
pnpm research:fetch    # download the inputs (prices, Wikipedia views, GDELT news volume) → scripts/landing/cache/
pnpm research          # event ideas through one harness, ranked
pnpm research:spikes   # news-volume spike ideas (GDELT), ranked
pnpm research:wiki     # public-attention spike ideas (Wikipedia pageviews), ranked
pnpm demo:data         # rebuild the page's data → apps/web/lib/showcase.json
```

**Method.** Every idea runs the same way: buy at the close of the first trading day *after* the news broke,
hold a fixed period (events: 1 month; news and attention spikes: 2 weeks), subtract the broker's costs,
then compare with the same asset bought on 10,000 random sets of dates drawn from the same years
(`scripts/landing/test_hypotheses.py` checks these three rules). The page shows **Beats random** when the
result is better than 80% of those random draws, otherwise **No edge**.

**Honest result.** 53 ideas were tested. One clears the stricter bar (10+ events, better than 95%):
layoff-news spikes → Nasdaq. Corrected for testing 53 ideas at once (Benjamini-Hochberg, 10% false-discovery
rate), **none survives**: the layoff result is the best of the batch, not proof. Nine more ideas could not be
tested (data not downloadable, or no trigger fired); `apps/web/lib/showcase.json` lists them with the reason.

**Sources.** Prices: Yahoo Finance daily closes (2020–2025, dividends included). News volume: GDELT (strictly
rate-limited, so `research:fetch` may need a second run). Public attention: Wikipedia pageviews. Headlines
shown for news spikes: Google News RSS, restricted to the spike day, saved in
`scripts/landing/data/headlines.json`. Big-event dates are hand-picked from public reporting.

Research tool, not investment advice.
