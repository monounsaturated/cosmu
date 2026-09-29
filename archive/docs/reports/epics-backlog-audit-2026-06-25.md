# Epics & Backlog audit — what's forgotten or half-done (2026-06-25)

> READ-ONLY audit. Branch from `origin/main` @ `81bff01` (#373). Cross-referenced every epic/plan doc against
> the actual code and the git log of PRs #339–#373. Goal: find epics that were DESIGN-approved but never built,
> half-done work, and money/honesty items flagged in past audits that were never closed. Honest, not a rubber
> stamp — half-done work is flagged as HALF-DONE with file/line evidence.

## Method

- Read every epic (`docs/epics/*.md`), every plan (`docs/plans/*.md`), the entry/handoff docs
  (`OPEN_THREADS`, `HANDOFF_NEXT`, `AGENT_TASKS`, `MASTER_PLAN`, `DECISIONS`, the 06-16 checkpoint), and
  `BACKLOG.md`'s prioritised sections.
- Verified each claim against code: `grep`/`Read` over `apps/engine/cosmu/**` and `apps/web/**`, plus
  `git show --stat` on the relevant PRs.
- A doc that says "SHIPPED" but whose code doesn't match → flagged. A doc that says "PLAN ONLY" with no code →
  NOT-STARTED (correctly, if a conscious park) or worth-picking-up (if it's now the money path).

---

## Epic / major-thread status table

| Epic / thread | Status | Evidence (file · PR) | What's left |
|---|---|---|---|
| **Realtime data lane** (`epics/realtime-data-lane.md`) — P0 fast crons · P1 event store + event-study · P2 credibility pipeline · P3 worker · P4 executor · P5 paid social | **HALF-DONE** | P0 shipped (Modal crons). Event store `data/events_store.py` + `market_events` in `schema_postgres.sql` exist; event-study core `research/event_study_run.py` exists. P3 worker CODE shipped (`cosmu/realtime/{worker,binance_ws,collectors,bars_store}.py`) but **OFF by default** (`settings.py:195 realtime_worker_enabled=False`, gated in `api/_lifespan.py:67`) — never activated/verified in prod. | **Activate + verify the worker** (the P3 acceptance: 1m bar queryable <30s after close, 7 days, 0 restarts — never run). **P2 credibility pipeline (`mind/{claims,outcomes,authority}.py`) is built but DORMANT** — never wired to a cron, never run on real data, no source scoreboard on the web. **P1 first event-study run** (GDELT→BTC minute bars) — harness exists, the pre-registered run hasn't produced a persisted verdict. P4/P5 correctly deferred. |
| **Agentic / LLM lane — Gate B** (`epics/agentic-lane.md`, BACKLOG P0.0–P0.6) | **HALF-DONE** | P0.0 done (#291 taxonomy). **P0.4 core SHIPPED + LIVE** (`strategy/agent_{spec,author,decision,loop,executor}.py`, `kind` discriminator in `spec.py:230`, wired into the Modal tick, 2 observe-only agents in prod). | **P0.1 partial** — `kind` exists on `StrategySpec`; the DB CHECK + dispatch-by-kind path is the observe loop only. **P0.2 NOT built** — no unified leaderboard badge language and, critically, **no web agent-trace replay** ("voir le processus" — zero `apps/web` files reference `agent_decision`/`agent-trace`). **P0.3 Gate B NOT built** — no critic agents, no source/catalyst forensics module, no alpha-vs-beta/ticker-anon disconfirmer harness. **`kind='llm'` paper track NOT wired** — `run_agent_strategies` is ZERO-capital observe-only (`agent_executor.py:3`); the loop opens paper tracks for quant only (`evolution/loop.py:739`). P0.5 (LLM-spend cap UI) + P0.6 (live + guardrails + Slack HITL) NOT built. |
| **Social / LLM / niche edge lane** (`plans/social-llm-edge-lane.md`, PR #367, **the current priority-1**) | **NOT-STARTED (plan only, ready)** | Plan added 2026-06-25; declares the lane "~80% built" because it reuses existing wiring. | **Build item 1: leakage tripwire as a standing CI check** (P0, the highest-stakes Gate-invisible failure mode — exists only as the `profile-source` skill, no automated wrapper). **Item 2: social-source ingest one feed at a time** (X/Grok timelines, pre-registered handles). **Item 3: Polymarket per-market hourly odds + UMA resolution join + panel Gate** (see below). **Item 4: Gate B forward harness** (= agentic-lane P0.3/track). None coded yet. |
| **Regime / context deep-analysis** (`epics/regime-context-deep-analysis.md`) | **NOT-STARTED (PARKED — correctly)** | "PLAN ONLY." Banked pieces exist unused: CPCV (`master/cpcv.py`), slippage-stress (`data/slippage.py:stress_returns`), Markov regime (`research/regime_cohort.py`). The multi-axis context labeler, scenario lab, fan-out summaries, RL lane = MISSING. | Explicitly parked by the 2026-06-14 alignment check ("park new feature epics … until the funnel produces ≥1 funded survivor"). Correct to leave parked. Note: regime-as-edge is CLOSED honest (DECISIONS 06-07) — only the regime-aware *gate hardening* (Phase 2) has standalone value, and it touches the locked bar (needs sign-off). |
| **Indexes** (`epics/indexes.md`) | **DONE (engine + web)** — one operator step + one follow-up open | Full module `cosmu/indexes/{spec,registry,compute,monitor,routing,run}.py` + API router + web `/indexes` + `/indexes/[id]` pages + migration `migrations/2026-06-15_indexes.sql`. | Operator must **apply the migration** in Supabase (else `available:false`). Follow-up: wire `store_provider_with_indexes` into the gate/backtest construction sites so a spec can key off an index end-to-end (the "strategies on top of indexes" step) + add a `cosmu.indexes.run` Modal job. |
| **Hot/cold data stack** (`epics/hot-cold-data-stack.md`) | **DONE (superseded by the actual migration)** | Phase 1 (cold-tier store + export) shipped; per memory, the Supabase→R2 migration completed in prod (DB 6.5GB→282MB, PR #246/#247). | Phase 3 "recent hot window in PG for the live gate" + bars-into-Parquet = later/optional. Not forgotten — done beyond the doc's "Phases 2–3 operator-gated" framing. |
| **Web redesign compat** (`epics/web-redesign-compat.md`) | **MOSTLY DONE** | The v18 redesign shipped (memory). The 4 named gaps: live/paper money split + `value_usd`/`invested_usd` largely addressed by the paper-readout work (#357 error bars, leaderboard per-cell backtest). | Gap 3 **"Liquidate-all really sells"** — `/live/defund` historically zeroed `positions.qty` in DB without a real adapter sell; #354 added a live-trades cancel panel but verify the market-sell-to-USDC path is real, not a DB zero. Gap 4 "Pause all paper" — confirm an endpoint exists. |
| **Per-symbol honest data-model** (BACKLOG rank #1, the CORE fix) | **DONE** | First-class `backtest_symbols` table is live and wired across `lab/finder.py`, `knowledge/store.py`, `master/{tracks,screen_universe}.py`, `evolution/loop.py`, the leaderboard/strategy API + web (#347–#357 persist per-cell OOS window, per-cell equity curve, error bars, own-window annualization). The #306 JSON dead-end was retired. | The honest gate-on-EFFECTIVE-N / ROBUST-not-MAX discipline is the harder half — verify it's actually enforced (cluster representatives + thin-trade guard ≥15). Largely shipped; treat as DONE pending that spot-check. |
| **Universe widening — survivorship-honest** (BACKLOG rank #3) | **DONE (Tier-0)** | PIT `UniverseCalendar` wired into the crypto screen (#355, kills survivorship + look-ahead); universe widened to ~30 Kraken-listed names + liquidity-tiered slippage (#371). `data/universe_build.py`, `data/market.py` carry the calendar. | Tier-1 breadth (~100–150 on Modal batch) + Tier-2 deep on-demand are later. Delisted-pair backfill from Binance Vision — verify depth. Tier-0 is the survivorship-honest floor and it's in. |
| **Money-path / venue off-ramp** (Binance→Kraken, capital guard) | **DONE / IN-PROGRESS** | Binance→Kraken bars off-ramp via `COSMU_BARS_VENUE` (#360); regime check FAILS CLOSED on error (#364); SANDBOX per-combo wallet (#368); capital-protection supervisor + exec heartbeat (#366); crowding cap + vol-target sizing in backtest (#359); Kraken live-arming readiness doc (#372). | Kraken live arming is **prepped, not armed** — one-step when keys land (operator action, by design). Live remains OFF. |
| **Frameworks buy-vs-build → Gate-stats parity** (PR #373) | **HALF-DONE (recommendation only)** | `docs/reports/frameworks-buy-vs-build-2026-06-25.md` — the #1 recommendation is **parity-pin PSR/DSR/expected-max-Sharpe/CSCV-PBO** against an independent reference (hand-rolled in `master/scorer.py`/`cpcv.py`, **no parity test today**). | **The parity test does not exist** — `tests/test_*parity*.py` covers fdr/spearman/cost/schema but NOT DSR/PSR/PBO. This is the doc's own "highest-leverage" honesty item and it's unbuilt. (This is what the prompt called "gate-stats parity in flight" — it is a doc, not yet code.) |
| **Slack notifier + cost monitor** (AGENT_TASKS L + M) | **DONE** | `notify/slack.py` POSTs (urllib, key-gated) and is subscribed in `research/loop.py`, `ingest/health.py`, `master/scheduler.py`, `ops/heartbeat.py`, `api/_lifespan.py`. Cost monitor: `costs/` ledger + alerts + Modal cost refresh folded into the tick. | Nothing material. The old AGENT_TASKS "Slack is a SEAM, not wired" note is **stale** — it's wired. |
| **TASK G — gate hardening** (06-16 checkpoint, branch `fix/gate-hardening`) | **UNKNOWN / likely SUPERSEDED** | The checkpoint says only TASK G remained (5 items: data_source default, narrative placebo seeds, MIN_TRADES in screening, purged/embargoed split, CI no-fake-passed_gates test). Later deploy-hardening commits touched arm self-stamps/DSR floors. | **Verify each of the 5 items individually** — several were likely absorbed by later PRs (#368 per-combo wallet, regime fail-closed #364, deploy-lane deflation per memory). Don't re-run blind; confirm item-by-item. Low residual risk. |
| **Polymarket autonomous lane** (resolution + hourly odds) | **HALF-DONE (data gap open)** | Exec adapter + CLOB live (`adapters/exec/polymarket.py`, `payoutNumerators` used in the ORDER path). Data side `adapters/data/prediction.py` has the no-resolved-look-ahead guard (resolved → leaves universe). | **The research/alt-data resolution JOIN is missing** — `payoutNumerators`/UMA authoritative outcome is used only for execution, not to label the odds series for backtesting; odds are daily (~1 trade/market) so the per-cell min-trades Gate correctly refuses. Unlock = hourly odds + resolution join + panel/cross-market Gate (social-lane item 3). |

---

## Stale / done-but-not-marked in OPEN_THREADS & friends

- **`docs/OPEN_THREADS.md` is STALE (frozen at 2026-06-07).** Its "🔴 NEXT" still says "search phase DONE, two tracks";
  PRs #134–#143 listed as "OPEN — reconcile" are long since merged or superseded; the "STUBBED HOLDOUT" P0 was
  FIXED 2026-06-07 (`research/equity_holdout.py`, DECISIONS). It no longer reflects the money-path/venue work of the
  last 200+ PRs. **Recommend retiring it** (or replacing with a pointer to `BACKLOG.md`'s prioritised section + the
  social-llm-edge-lane plan, which are the live priority docs).
- **`docs/AGENT_TASKS.md` is STALE** — Tasks L/M (Slack, cost monitor) are DONE in code; the "Slack is a SEAM" claim
  is false now. Tasks G/J/K describe a 06-05/06-16 world. Useful as history, misleading as a queue.
- **`docs/HANDOFF_NEXT.md`** correctly marks itself superseded → points at the 06-16 checkpoint. Fine.
- **`docs/MASTER_PLAN.md` §2 gaps** are mostly closed (paper maturity shipped, evolve-strategy armable, breadth
  partly live) but the doc still reads as if no dollar has been made — true (live is OFF), but the gap list predates
  the per-symbol/universe/venue work. Lightly stale, not wrong.

---

## TOP 5 genuinely-unfinished things worth picking up (ranked by leverage)

### 1. Gate-stats parity-pin for PSR / DSR / expected-max-Sharpe / CSCV-PBO — HONESTY, highest leverage
The frameworks survey (#373, 2026-06-25) named this its own #1: the hand-rolled Gate math in `master/scorer.py` +
`master/cpcv.py` is correctness-critical (a subtle bug **funds noise**) and has **no parity test against an
independent reference** — unlike BH-FDR (statsmodels-pinned) and Spearman (scipy-pinned), which are the gold
standard to copy. This is pure honesty insurance on the one thing that can silently waste runway. Small, bounded,
no gate-loosening (parity-pin only). `tests/test_*parity*.py` has the pattern; just no DSR/PSR/PBO file.

### 2. Activate + verify the realtime worker, then wake the dormant credibility pipeline — THROUGHPUT/edge
The P3 worker is fully coded but `realtime_worker_enabled=False` and never run; the P2 credibility pipeline
(`mind/{claims,outcomes,authority}.py`) is built, offline-tested, and has **never touched real data or a cron**.
This is the single biggest "built but dark" asset — flipping it on (after the documented local-test gate) unlocks
recorded-live event/source data, which is the substrate the priority-1 social lane needs. Highest realized-value
per unit effort because the code already exists.

### 3. Social/LLM/niche lane build-item 1 — the leakage tripwire as a standing CI check — HONESTY/money
The current priority-1 plan (`plans/social-llm-edge-lane.md`) names this its own P0 and the "single highest-stakes
item" — a leakage bug UPSTREAM of the Gate produces a survivor that is real on paper and zero/negative live, and
the Gate **cannot see it**. Today it exists only as the manual `profile-source` skill + ad-hoc shuffle disconfirmers;
there is no automated, gate-adjacent wrapper every new social source must pass. Build this BEFORE ingesting any new
scraped/social feed, or the whole lane risks manufacturing invisible false positives.

### 4. Wire the `kind='llm'` paper track + the web agent-trace replay — money-path + the operator's explicit ask
The LLM lane is observe-only/zero-capital (`agent_executor.py`) and the loop funds `kind='quant'` only
(`evolution/loop.py:739`). To turn the 2 prod observe-agents into a real forward-proof lane, wire a paper track for
`kind='llm'` (the Gate B forward harness) AND build the web agent-trace replay (agentic-lane P0.2 — "voir le
processus"), which **does not exist** in `apps/web`. Without the trace view the operator can't be the launch
guardrail the whole design rests on. Medium effort; it's the last mile of a mostly-built lane.

### 5. Polymarket per-market hourly odds + UMA resolution join + panel Gate — money (niche-market edge)
The favorite-bias edge is real cross-market (+7–13% in the probe) but the data side joins odds without the
authoritative resolved outcome (`payoutNumerators` is used only in the exec adapter, not the research path), and
daily odds = ~1 trade/market so the per-cell min-trades Gate correctly refuses it. The unlock is exactly three
things: hourly odds (trade frequency), the UMA resolution join (kills the look-ahead caveat), and a panel/cross-
market Gate evaluation (each market = 1 clustered obs, held-out markets). This is the one niche-market lane with
prior evidence — the cleanest shot at a first forward survivor from the axis the giants ignore.

---

## Honest caveats on this audit

- "DONE" means the code is present and matches the doc — **not** that it's been verified live in prod (live is OFF
  by design). Several "DONE" items still carry an operator step (apply a migration, arm a venue).
- TASK G (gate hardening) is the one item I could not fully resolve from code alone — its 5 sub-items need an
  item-by-item check against later PRs before re-dispatching; residual risk is low but non-zero.
- The DECISIONS tail I read is frozen at 2026-06-07 (large file); the live priority frame is `BACKLOG.md`'s
  2026-06-17 prioritised section + the 2026-06-25 social-llm-edge-lane plan, which is what I anchored ranking to.
