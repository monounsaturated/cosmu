# Cosmu Idea Inbox

> Append-only inbox for **product/engineering** ideas — NOT trading strategies (those go to `apps/engine/strategies/inbox/`).
>
> **The loop:** IDEAS.md → `/triage-ideas` → `BACKLOG.md` → `/fan-out` → PRs → `main`.
>
> Drop a one-liner under **Inbox** in this format: `- [YYYY-MM-DD] <idea> — <why it matters>`.
> `/triage-ideas` promotes ripe ideas into the backlog (with tags), then moves them down to **Archived**. Keep the Inbox lean — only un-triaged ideas live here.

## 🗑️ DUMP ZONE — your ONE inbox: write ANYTHING here (ideas · trades · features · gripes)
> No rules, no format. Half-baked, one word, a link, "scrape X and score it", a screenshot note, a trade hunch — dump it.
> **This is the only file you have to touch.** On the next `/triage-ideas`, Claude runs the whole loop for you:
> **read → sort → route** (product/infra → `BACKLOG.md` as a defined **user story**; trade → `/strategize` → typed spec → the **Gate**; junk → dropped) **→ prioritize → `/fan-out` builds it (Claude Code) → CI tests it.** Then it clears this zone.
> You dump; the machine defines, builds, and tests. Review the result in `BACKLOG.md` / the app.

<!-- ↓↓↓ DUMP BELOW THIS LINE ↓↓↓ -->

<!-- ↑↑↑ DUMP ABOVE THIS LINE ↑↑↑ -->

## Inbox (append below)
- [2026-06-13] **Costs editing model — REVISED: editable from the page AND from Claude Code (one source of truth).** The operator wants to add/edit/delete subscriptions & one-off spends directly in the Costs page (cadence: Monthly/Weekly/Yearly/One-off, with a renews/spent date) and see the waterfall + totals recompute live. Source of truth = `costs/subscriptions.yaml` (or a `cost_entries` table); the page form POSTs to the engine which writes the file/table; Claude Code can edit the same file by hand. Usage costs (per-fill fees, LLM calls) stay AUTO from the engine (read-only). How dynamic: fully — live optimistic recompute in the client, persisted server-side, rendered from the single source on reload. (engine+web, sonnet)

- [2026-06-13] **"Stop" semantics + realized P&L persistence (web + engine)** — the live kill button is "Stop": market-sell every open position to USDC, kill the bots, place NO further orders (per-strategy "Stop" on the sheet + global "Stop" on the Live page). CRITICAL data requirement: a stopped/killed strategy must KEEP its realized P&L on the live wallet and keep its stats visible on dashboards forever (no survivorship erasure). Engine: realized P&L stays in the track's terminal value after defund+kill; the live-wallet aggregate (and the strategies table row) must count a stopped strategy's realized contribution, not drop it. Web: Live dashboard "P&L"/"Total" includes realized-from-stopped; a stopped row shows its final live P&L, not "—". (engine+web)

- [2026-06-13] **Web redesign — 5 gaps to not forget before/just-after ship** (full review in chat 2026-06-13): (1) GLOBAL live ARM + 5-interlock visibility has no home — put the 2-step arm toggle + interlock checklist on the Live page header (the old Console owned this; it's the core safety model and must be visible/operable). (2) IDEA INTAKE — the app that mass-produces strategies has zero capture surface; add a tiny "+ capture idea" that POSTs to /lab/inbox (no LLM, phone-friendly). (3) EVENTS/ALERTS surface — the running-dot shows liveness but nothing tells the operator WHAT happened (strategy died / drift / daily-loss auto-disarm / track hit live-ready). Surface the `events` table as a small notifications/feed (bell or activity panel); money+safety events especially. (4) DAY-1 / EMPTY-STATE onboarding — when 0 live/0 paper, every surface must explain "what now" honestly (invariant: never fabricate). (5) FILL↔SIGNAL provenance — on a trade, show the signal that fired vs the venue fill (the model-decision/venue-execution separation invariant) so "why did this trade happen" is answerable.
- [2026-06-13] **Cadence-awareness for the real-time future** — the whole sheet assumes daily cadence ("47 paper days", daily marks, phase chart). When intraday/news bots land (realtime epic), surface per-strategy bar_size + last-tick time, and make "days/freshness" cadence-aware so a 5-min bot doesn't read as stale. Design the LeaderboardRow + sheet with a `cadence`/`last_tick_at` field now.

- [2026-06-11] **KPI pedagogy in the UI** — every ratio surfaced (simple Sharpe, Deflated Sharpe, Sortino, Max Drawdown, PBO, Calmar, win rate) gets a plain-language one-liner + "why it matters" tooltip; the operator wants to LEARN the ratios while using the app. Include raw simple Sharpe next to DSR on strategy sheets/comparison tables (web redesign requirement, not just an idea).
- [2026-06-11] **Data depth > interface** (operator principle, from variant-a1-prime's strategy page) — the real strategy sheet must carry the FULL trade log (not 6 rows), all past decisions, every data point received; pagination/virtualization rather than truncation. Depth is the product.
- [2026-06-11] **Costs v2 — live spend + subscriptions** — plug provider APIs (Railway/Vercel/Supabase usage endpoints) for live actuals; model SUBSCRIPTIONS as first-class (provider, monthly price, renewal date, manual entry; Claude Max = flat sub → $0 marginal for Claude Code; OpenRouter = per-token actuals already tracked); allow manual backfill of ALL past spending; Costs page shows live month-to-date vs subs vs per-token. (web+engine)
- [2026-06-11] **De-emphasize /run-gate as a separate flow** — gate is already inside strategize/create→backtest→gate; keep the skill as a DIAGNOSTIC (re-judge an existing spec after data refresh / debug) but remove it from primary operator-facing lists (Commands page) so the mental model stays "create → gate happens automatically". Don't delete the skill.


## Archived
<!-- Triaged ideas move here with their disposition: promoted / deferred / dropped. -->

### Shipped (do not re-add)
- [2026-06-03] Mission-control UI → **SHIPPED** (#152, 2026-06-07): control-room overview + Theories surface. ML compute home → **DECIDED**: Modal (heavy compute, scale-to-zero) + Railway crons; see docs/COMPUTE.md.
- [2026-06-04] Beautiful lean platform → **SHIPPED** (#155, 2026-06-07): full premium frontend overhaul.
- [2026-06-04] SIM→live variance attribution → **SHIPPED** (#58, 2026-06-04): `cosmu/research/attribution.py` + `/variance-attribution` skill.
- [2026-06-04] Profile-source data-trust audit → **SHIPPED** (#58, 2026-06-04): `cosmu/ingest/profile_source.py` + `/profile-source` skill.
- [2026-06-04] Pipeline ordering = explore→validate sandwich → **SHIPPED**: built into `/add-data-source` step 6.
- [2026-06-04] UI rethink → **SHIPPED** (#155, 2026-06-07): premium overhaul with data-rich design system, no emojis, grouped nav.
- [2026-06-04] Backtest integrity audit → **PARTIALLY SHIPPED**: `master/cpcv.py` (combinatorial purged CV) + `master/risk_metrics.py` (Calmar/Recovery Factor) in #148. Severity-framework surface deferred to post-first-survivor.

### Deferred (ripe when the Gate has a survivor)
- [2026-06-04] Qual→quant from media (URL/screenshot/YouTube → LLM thesis → Gate) → **DEFERRED**: requires the LLM-narrative pipeline (built, honest FAIL so far) + a deep PIT corpus. Re-evaluate when Gate has a survivor. See docs/HANDOFF_NEXT.md Track 2.
- [2026-06-04] LLM-reviewed scores/indexes (per-source composite index scores + LLM "what this means") → **DEFERRED**: wire after the first Gate survivor (need a proven data surface first).
- [2026-06-04] LLM research-desk for Polymarket ONLY → **DEFERRED**: the LLM-narrative harness is built; re-run on Polymarket historical odds when data depth warrants.
- [2026-06-04] Adaptive scraper → PIT feature → **DEFERRED**: too speculative; use existing registered sources first.
- [2026-06-04] Strategy × asset × timeframe matrix → **PROMOTED to BACKLOG** (in docs/HANDOFF_NEXT.md §8 item 1): highest-leverage search move, runs on Modal.
- [2026-06-04] LLM-quality-scores as standardized features → **DEFERRED**: wait until a survivor exists to train on.
- [2026-06-05] Polymarket smart-money flow as PIT alt-data → **DEFERRED**: CrowdIntel retroactive scores = look-ahead NO-GO; raw ledger indexing is viable but low priority until the equity lane has a survivor.
- [2026-06-06] NL backtest/stress-test UX polish → **DEFERRED**: MCP layer is shipped (#128); full UX polish deferred post-survivor.
- [2026-06-06] Generalization barbell / Lane B (domain-agnostic COSMU) → **DEFERRED**: see docs/reports/generalization-plan-2026-06-06.md; re-evaluate when finance vertical is proven.

### Dropped / decided
- [2026-06-05] CrowdIntel → **DROPPED**: retroactively recomputed scores = look-ahead bias. NO-GO. Revisit only if they expose frozen as-of-event snapshots. Banked in memory/buy_vs_build_decisions.md.
- [2026-06-05] "ML-for-noobs" general product → **DROPPED**: crowded space; COSMU's edge is trading-specific. Not building.
- [2026-06-04] External validation (AI-in-trading writeups) → **META-NOTE** (not a buildable item): locked rule is "LLM proposes, Gate disposes." Already an invariant in AGENTS.md.
- [2026-06-06] Product vision / user tailoring → **META-NOTE**: operator profile captured in docs/reports/product-vision-user-profile.md. Informs UX decisions, not a standalone buildable item.
