# Cosmu Idea Inbox

> Append-only inbox for **product/engineering** ideas — NOT trading strategies (those go to `apps/engine/strategies/inbox/`).
>
> **The loop:** IDEAS.md → `/triage-ideas` → `BACKLOG.md` → `/fan-out` → PRs → `main`.
>
> Drop a one-liner under **Inbox** in this format: `- [YYYY-MM-DD] <idea> — <why it matters>`.
> `/triage-ideas` promotes ripe ideas into the backlog (with tags), then moves them down to **Archived**. Keep the Inbox lean — only un-triaged ideas live here.

## 🗑️ DUMP ZONE — write ANYTHING here, any time, any format
> No rules. Half-baked, one word, a link, "scrape X and score it", a screenshot note, a complaint, a trade hunch — dump it.
> **Claude reads this every `/triage-ideas` run**, cleans it up, sorts it (feature → BACKLOG, trade → `/strategize`, junk → dropped), assigns priority, and clears this zone. You never have to format anything.

<!-- ↓↓↓ DUMP BELOW THIS LINE ↓↓↓ -->


<!-- ↑↑↑ DUMP ABOVE THIS LINE ↑↑↑ -->

## Inbox (append below)
- [2026-06-03] Mission-control UI: extend `/mind` into one visual surface (pipeline funnel, data freshness, backlog state, open PRs/agents, ML model status, gate efficiency) — one glance answers "is the machine healthy and earning?"
- [2026-06-03] Decide ML compute home: VPS worker vs scheduled cloud-session cron for nightly survival-model training — picks where the heavy ML loop runs without OOMing the Air or burning API tokens.

- [2026-06-04] Qual→quant from media: drop a URL / screenshot / YouTube transcript / essay / chat idea → LLM extracts a thesis → quantify it into a tested index-score or StrategySpec on RAW data, so a qualitative hunch becomes a mathematically-checked edge (LLM-idea + LLM-formatting as a creative iteration step; the gate verifies).
- [2026-06-04] Beautiful lean platform: compact, powerful cockpit — pick data sources (greyed if no key), dashboards, indexes, strategies; integrated, not cluttered.
- [2026-06-04] LLM-reviewed scores/indexes: per-source + composite index scores (LunarCrush/social/OSINT/…) with a short LLM "what this means" review, all point-in-time and gate-checkable.

- [2026-06-04] SIM→live variance attribution (HIGH, missing): when a live track diverges from its SIM track, decompose realized-vs-expected P&L into fees · slippage · funding · signal-decay · regime — so the auto-defund/Console recommendation has a REASON, not just a number. Serves §5+§9.
- [2026-06-04] Profile-source data-trust audit (HIGH): before a NEW alt-source becomes a feature (in /add-data-source), auto-profile coverage · gaps · staleness · distribution sanity · look-ahead smell · point-in-time integrity → emit a go/no-go. Garbage-in defense, made mechanical.
- [2026-06-04] Backtest integrity audit w/ severity framework: flag implausibly-smooth equity, identical cross-fold metrics, leakage smells, too-few-trades as RELEASE-BLOCKING before a strategy earns a track. Sharpens "adversarial validation".
- [2026-06-04] LLM research-desk for Polymarket ONLY: structured event research (gather → estimate probability → find where the market is least confident) → a gated Polymarket StrategySpec. The one safe home for "LLM research" — never in the money path (avoids v1 "LLM read news and bought" slop).
- [2026-06-04] Adaptive scraper → PIT feature: a scraper that studies how a site loads + self-handles pagination → continuously-updating alt-data → profile-audit → feature registry → gate. The engine behind "qual→quant from media".
- [2026-06-04] Pipeline ordering = explore→validate sandwich: /profile-source (BEFORE) → Gate (during) → integrity-audit (AFTER, before a track is funded).
- [2026-06-04] UI rethink — modular, Notion-vibe, data-rich, less clutter: pick-what-to-display, beautiful data-viz, deep-detail on demand; replace the "$ dollars" KPIs with tool-aligned metrics; logic + buttons + run-command-on-hover modals, not walls of explanatory text. Keep live + research coexisting cleanly.
- [2026-06-04] Strategy × asset × timeframe matrix (THE core ML feature): test each strategy across assets + timeframes, tailor/decline it per asset — this is why we need big compute + deep data + ML.
- [2026-06-04] LLM-quality-scores as standardized features: LLM-generated quality/sentiment scores for specific indexes, stored point-in-time WITH HISTORY → train ML on them; the agent can mint new index-scores. Qualitative→quantitative, standardized — the leverage.

- [2026-06-04] External validation (top-firm AI-in-trading writeups): the reusable kernel is "AI = research-throughput compressor + adversarial reviewer + unstructured→typed signal, NOT the money-decision-maker." Keep REJECTING the Bridgewater "AI as primary decision-maker" model — LLM proposes, the deterministic gate disposes (our locked non-negotiable). GPU/datacenter scale-ups are anti-thesis to lean. The one practical nudge already in the plan: every authored hypothesis should ship with a disconfirmer (gate-side proven by #57; author-side still open).

- [2026-06-05] Polymarket smart-money flow as a PIT alt-data feature (news/scoring, NOT copy-trading): index the on-chain Polymarket ledger (top-decile-profitable + insider-flagged wallet net-flow per market) → `/profile-source` audit → feature registry → Gate. Treat like a sentiment/news score: confirm/veto in liquid markets, may *originate* in prediction markets (§7). Passive copy-trading is rejected — latency means you always fill after the whale; any "insider z-score" runs through OUR deflated-Sharpe/PBO gate, not theirs. Powers the reserved "LLM research-desk for Polymarket ONLY" idea above. (Inspired by CrowdIntel's Postgres-MCP-over-ledger writeup.)

## Archived
<!-- Triaged ideas move here with their disposition: promoted / deferred / dropped. -->
