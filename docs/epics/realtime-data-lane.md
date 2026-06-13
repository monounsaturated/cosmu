# EPIC — Real-time data lane (bots live · data live · marks live) + event-driven research

> Status: ACTIVE (2026-06-11, operator-approved sequencing). Owner: operator + engine sessions.
> North star fit: the single biggest latency unlock between "the machine knows" and "the machine acts",
> PLUS the orthogonal-data axis the search campaign concluded is the only remaining unlock
> (DECISIONS 2026-06-07: "pivot = orthogonal data, not more search"). Operator goal: *bots that react
> very quickly to news, Polymarket, tweets — smart, with access to quality data — to make money asap.*

## 0. Operator decisions (2026-06-11 — locked for this epic)

1. **Sequencing = P0→P4 below** (prerequisites + event-study harness on owned data first, credibility
   pipeline next, then the always-on worker, then exploratory lane / event-driven executor).
2. **Tweets/X**: NO paid archive, NO X API for now. Live accrual via xAI/Grok LiveSearch (existing
   credits) + a later **local Chrome lane**: the operator's local Claude session drives Chrome
   (with `.env.local`) to collect voice timelines. Collected backfills are honest *event-study* inputs
   (event ts = post time; we measure the market after it) but are stamped `available_at = scrape time`
   — they are NEVER point-in-time trading features (no backdated availability). To avoid
   pick-the-famous-tweet survivorship, the Chrome lane collects **complete timelines of a
   pre-registered handle list**, never individual viral posts.
3. **Per-strategy summaries**: written by **Claude Code** (flat Max sub, $0 marginal) at authoring time
   + a bulk backfill path; stored server-side; the web shows an honest "no summary yet" empty state.
   No per-token engine auto-generation for now.
4. **Light gate**: decision still open — see §8 (analysis + recommendation). The real Gate's
   thresholds never loosen for anything funding-eligible (DECISIONS 2026-06-07 calibration verdict).

## 1. Problem

Everything in the deployed loop is **cron-shaped, not stream-shaped**. Worst-case reaction time to an
external event was **~24h**. Target: **seconds-to-minutes** for the sources that justify it.

| Loop | Cadence (pre-epic) | Now (Tier 1 shipped 2026-06-11) |
|---|---|---|
| Alt-data ingest | every 6h | **every 15 min** |
| Autonomy tick (author → gate → fund) | every 4h | unchanged (4h) |
| Forward-test executor | daily 22:10 UTC | **daily 00:10 + 22:10 UTC full clock · hourly lane for 1h/4h tracks** |
| Mark-to-market | daily (inside 22:10) | **hourly** (the hourly lane re-marks everything) |
| Arm-fleet rotation re-arm | daily 22:40 UTC | unchanged |

Plus the PRE-LIVE bar-cache freshness fix (shipped 2026-06-11): the crypto providers serve **closed
candles only**, refetch stale covering caches, and repair poisoned rows — the hard prerequisite for any
executor cadence increase. (The Yahoo equity provider still serves an in-progress day bar; daily/equity
tracks therefore stay on the daily clocks — the hourly lane is scoped to sub-daily crypto horizons.)

## 2. Target (tiered — each tier is shippable and useful alone)

| Tier | What changes | Reaction latency | Incremental cost / mo (verify before buying) |
|---|---|---|---|
| **0 — before** | crons 6h/4h/daily | 6–24h | $0 |
| **1 — fast crons** ✅ shipped 2026-06-11 | ingest 15min · hourly mark · hourly executor lane (1h/4h) · 00:10 crypto-daily clock | 15–60 min | ~$2–5 (Railway cron compute; sources stay free) |
| **2 — always-on worker** | one small always-on Railway service: Binance WS (klines), Polymarket WS, short-poll collectors (RSS/Reddit/CryptoPanic 1–5 min, jitter + budget guard) · 1m/5m bar store with retention · **event recorder** (§5) · heartbeat → events table | seconds (market) · 1–5 min (news/social proxies) | ~$5–15 worker + ~$0–25 Supabase growth · data $0 |
| **3 — paid real-time social** | X API (~$200/mo — verify), LunarCrush paid, CryptoPanic Pro | seconds (social) | ~$230–450 — **only behind the profit gate**: trailing-30d live net P&L > 2× the social spend |

## 3. Architecture (Tier 2 core)

```
                ┌────────────────────────────────────────────┐
                │  cosmu.realtime.worker  (Railway, always-on)│
                │                                            │
  Binance WS ──▶│  ws consumers (reconnect+backoff, dedup)   │
  Polymarket WS▶│  poll collectors (RSS/Reddit/CryptoPanic)  │──▶ alt_data (PIT: available_at = receipt ts)
                │  EVENT RECORDER (typed unstructured events)│──▶ market_events (PIT event store, §5)
                │  bar builder (1m/5m → bars store)          │──▶ bars_intraday (retention, §6)
                │  heartbeat → events table every 60s        │──▶ "bar_closed" / "source_updated"
                └────────────────────────────────────────────┘
                                   │
                                   ▼
                  executor trigger (intraday lane): on bar_closed for a
                  symbol×timeframe with an active intraday track → run the
                  SAME forward_step path (one order path, real fees, slippage)
```

Principles (non-negotiable, inherited from AGENTS.md):
- **One order path.** The intraday lane calls the existing `forward_step` / `execute_orders` gauntlet —
  no second execution code path; kill-switch checked every tick; decision-bar client_order_ids make
  any re-run a no-op (already true today).
- **PIT honesty.** `available_at` = wall-clock receipt time, never the event's claimed time. A
  real-time source has **no trustworthy backfilled history** for *trading features* — it must
  accumulate recorded-live history before the Gate may use it (`/profile-source` applies). A scraped
  archive may feed *event studies* (market-reaction measurement) but never a backdated feature.
- **Crons stay as the fallback lane.** Worker dies → freshness decays to Tier-1; nothing breaks.
  Stale heartbeat = a visible badge, not a silent failure.
- **LLMs stay out of the hot path.** LLMs *format* (extract typed events from text — versioned prompt,
  content-only, cached, deterministic fallback); the deterministic spec/Gate machinery decides.
  No "LLM reads a tweet and fires an order", ever.

## 4. The event-driven research axis (NEW — the operator's core ask)

**Goal:** backtest unstructured/qualitative events (news, tweets, Polymarket moves, weather…) honestly;
score *sources* (accounts/outlets) for real alpha vs echo; later trade event signals live through the
same deterministic machinery.

**Why this can be different from the closed LLM-narrative axis** (DECISIONS 2026-06-07: honest FAIL,
dSR 0.889, momentum-in-disguise + partial look-ahead): that test aggregated LLM headline scores into a
**daily** signal on daily bars. Event reactions in crypto live at **minutes-to-hours** (Musk-tweet event
studies: most of the move within 5–60 min; macro-surprise studies: ~10 min) — a daily bar smears the
reaction into noise and competes head-on with momentum. The event-study harness measures reactions in
**event time on minute bars** (free + deep via Binance Vision, plumbing already in
`data/intraday_binance_vision.py`), conditions on the *event*, and is sparse (fees scale with events,
not bars — unlike the always-on intraday TA the matrix sweep showed fees kill). It may still honestly
FAIL — that is a valid verdict and the machine's job.

### 4.1 Methodology (research-backed; the harness pins these)

Sources: Kothari & Warner (event-study econometrics) · Ante 2023 (Musk/DOGE minute-bar CARs) ·
Lopez-Lira & Tang 2023 + Sarkar & Vafa 2024 + Glasserman & Lin 2023 (LLM look-ahead/distraction) ·
Kakhbod et al. "Finfluencers" (28% skilled / 56% ANTI-skilled; followers = anti-signal) · Bradley et
al. WSB (alpha dies post-publicity) · Tetlock 2011 (stale news = reversal signal) · RavenPack novelty
scoring (root-event dedup). Full citations in the session research notes.

1. **Abnormal returns, never raw returns:** per event, returns are measured as market-model residuals
   (asset minus β·BTC for alts), volatility-standardized by trailing per-bar σ.
2. **Event windows:** CAR over [0,+5m], [0,+30m], [0,+60m], [0,+24h] + a **[−30m,0) pre-window** —
   a significant pre-move means the "news" was late (echo / leak), which is itself a feature.
3. **Root-event dedup:** cluster items by content similarity + time window; the first item is the
   breaker, later items are echoes with decaying novelty. Staleness is a signal (retail overreacts to
   stale news → reversals), not just a filter.
4. **Confounder discipline:** drop events with another same-asset root event within ±2h; flag windows
   where the market itself moved > z·σ (the move was beta, not the event).
5. **Inference = randomization:** ≥1k placebo pseudo-events matched on weekday × hour × trailing-vol
   tercile, identical pipeline; RI p-value = fraction of placebo outcomes ≥ observed. **BH-FDR across
   the (event_type × source) grid** via the existing `master/fdr.py`. Time-split holdout.
6. **LLM = frozen extractor, never decider:** typed schema (event_type, entities, direction,
   magnitude, confidence), content-only prompt, temperature 0, content-hash cached, versioned
   (`extractor_version`), deterministic lexicon fallback — the `llm_formatter`/`claims.py` discipline.
   Look-ahead controls: time-shuffle placebo (existing pattern) + report masked vs unmasked entity
   runs; treat disagreement as distrust.
7. **Source scoring is walk-forward and PIT:** a source's score as-of t uses only events resolved
   before t; frozen source panel per rebalance; min-N events; empirical-Bayes shrinkage toward zero
   (the Brier-skill-vs-base-rate shrinkage in `mind/outcomes.py` already does exactly this);
   follower count is an anti-prior; expect WSB-style alpha death after popularity.

### 4.2 What already EXISTS for this (do not rebuild)

- **Credibility pipeline, Phases 0–3, dormant:** `data/sources/voices.py` (raw voice timelines:
  X-via-Grok / Reddit / RSS, PIT-stamped) → `mind/claims.py` (LLM claim extraction, typed+validated) →
  `mind/outcomes.py` (deterministic resolution, Brier skill vs base rate, sample-shrunk) →
  `mind/authority.py` (primacy + lead-lag **vs an event timeline** + skill-anchored PageRank;
  influence ≠ authority). Registered features: `author_authority`, `authority_weighted_claim_signal`.
  Tested offline; never wired to a cron/UI; never run on real data. **The event store (§5) is the
  event timeline `authority.py` already wants.**
- **LLM-narrative machinery:** content-only scoring, content-hash cache, shuffle-placebo + momentum
  control (`research/llm_narrative_pipeline.py`, `llm_narrative_cohort.py`) — reuse the discipline and
  the corpus (115k GDELT GKG items, 10 assets, 2023→2026, on the Modal volume).
- **1m bars, free + deep:** `data/intraday_binance_vision.py` + `data/binance_vision_backfill.py`
  (years of 1m klines, no key, PIT close-time seam).
- **InfluencerHitRateStore stub** in `data/sources/xai_twitter.py` — supersede with Phase 2/3 scores.

### 4.3 First experiments (pre-registered, in order)

1. **GDELT news → BTC/ETH/majors, minute bars**: do clustered news root-events carry abnormal forward
   returns at [+5m..+24h] after costs? (Corpus owned; 1m bars backfillable free. The binding question
   GDELT can answer despite its 15-min batch granularity: the +30m..+24h windows.)
2. **Polymarket prob-velocity events → crypto** (backfill CLOB history first — never run in prod;
   `polymarket_backfill_coverage.md` documents the gap).
3. **Source-credibility first real run**: voices Phase 0 pull (pre-registered handle list) → claims →
   outcomes → authority on recorded data; surface per-source skill on the web (source scoreboard).
4. **Recorded-live tweets** (worker + Grok LiveSearch): accrue ≥30 days, then the same harness.

## 5. Storage: the event store (`market_events`)

`alt_data` is numeric-only; events need text + typing + clustering. New append-only table (+ JSONL
offline twin, same dual-store pattern as alt_data):

```
market_events(id, provider, source, event_type, symbols(json), ts, available_at,
              title, content_hash UNIQUE(provider,content_hash), root_event_id,
              novelty, direction, magnitude, confidence, extractor_version, ingested_at)
```

- `ts` = the event's own publish/claim time (event-study x-axis); `available_at` = OUR receipt time
  (trading-feature x-axis). The two never conflate (voices.py invariant, now global).
- Raw text policy: titles/snippets are small (≪ alt_data's numeric volume); full bodies stay OUT of
  PG (score-and-discard on Modal, or object storage later — HANDOFF §6b stance unchanged).
- Derived numeric features (event counts, novelty-weighted scores, authority signals) flow into
  `alt_data` as ordinary PIT features so the existing join/Gate path consumes them unchanged.

## 6. Storage & load math (why this is safe)

- 1m bars × ~30 symbols ≈ 43k rows/day ≈ 1.3M rows/mo (~150–300 MB/mo with indexes). Retention: 1m for
  90 days, roll up to 5m/1h beyond. Tick data out of scope.
- Poll collectors at 1–5 min stay within free-tier limits with per-source jitter + a budget guard
  (skip-and-log, never hammer). **Known Tier-1 caveat:** the 15-min ingest cron multiplies per-symbol
  key-gated calls (LunarCrush); a rate-limited pass degrades honestly ([] + next pass) — the budget
  guard lands with the worker.
- Supabase Pro headroom ~2 GB (6/8 GB used) — months of runway; hot/cold parquet tiering (BACKLOG) is
  the relief valve.

## 7. Tech-debt & risk register (a daemon is a commitment)

| Risk | Mitigation |
|---|---|
| WS disconnects / silent staleness | reconnect + exponential backoff; staleness watchdog flips the source badge; heartbeat events |
| Duplicate/missed messages on reconnect | idempotent writes keyed (provider, symbol, metric, ts) / (provider, content_hash); resume from last stored ts |
| Memory leaks in a long-lived process | bounded queues; restart-safe (Railway restarts are normal) |
| Worker cost creep | one small instance; alert when monthly compute > `costs` budget line |
| In-progress candle decisions | ✅ closed-candle guard shipped (data/market.py, 2026-06-11); worker bar-builder emits only closed bars |
| Two execution cadences diverging | both lanes call the same `forward_step`; `horizon.bar_size` routes — no per-lane forks |
| LLM look-ahead in event backtests | content-only + versioned prompts + time-shuffle placebo + masked/unmasked comparison (§4.1.6) |
| Source-scoring survivorship | pre-registered handle lists, complete timelines, walk-forward scores, shrinkage (§4.1.7) |

## 8. The "light gate" question (operator asked: explore; don't loosen blindly)

Operator intent: *harness LLM inference power, accept some hallucination risk, keep a deterministic
guardrail; maybe a lighter gate so slower/weaker-but-real signals aren't invisible.*

Options considered:
- **(a) Loosen the existing Gate (dSR 0.95 → ~0.8, drop holdout, FDR q up).** REJECTED. The 2026-06-07
  calibration review is unambiguous: every near-miss across 16 spaces was unmasked by the holdout or a
  placebo as noise — a looser bar would have *funded* those. Loosening the discovery gate manufactures
  false positives by construction (it is a multiple-testing bar, not a taste setting). It is also the
  one thing DECISIONS locks ("correctly STRICT — never loosen").
- **(b) A second, parallel "light" statistical gate.** WEAK. Two maintained bars invite
  meta-overfitting (iterate against the lighter one, graduate to the stricter one with contaminated
  trials) and double the surface area for subtle bugs.
- **(c) EXPLORATORY LANE (recommended).** A third typed lane (`lane: "exploratory"`, extending the
  existing `gate|deploy` literal — the architecture already routes by lane). Entry bar = SANITY ONLY
  (compiles, features bind, ≥N trades, positive net-of-cost OOS return, no look-ahead flags). Funded
  with a small capped SIM track, clearly badged, **never live-eligible**. The judge is the **live
  forward test itself** — real-time OOS data cannot be overfit. Graduation to funding-eligible =
  the full existing Gate, with BH-FDR applied across the exploratory cohort's forward records at
  graduation (volume still can't manufacture a winner). Cap concurrent exploratory tracks (e.g. 25).
  This is *less* machinery than a second statistical gate, reuses the forward-test clock as-is, and is
  exactly where LLM-authored event strategies can run wild safely: SIM is free; the operator's "run
  each strategy twice" collapses into lane routing (full-Gate pass → gate-lane; fail-but-sane →
  exploratory) with no duplicate tracks.
- **(d) No new lane; rely on the Theories surface.** Cheapest, but near-misses accrue no forward
  evidence and slow/weak-but-real event signals stay invisible — fails the operator's goal.

**DECIDED 2026-06-11 (operator): stay as-is — no new gate, no new lane for now.** The strictness is
load-bearing (every near-miss across 16 spaces was unmasked as noise), and a lane only pays off once event
strategies exist to route into it. Revisit AFTER the first event-study verdict: if a cell passes, decide
then — with real candidates in hand — between the existing deploy-lane bar and the exploratory lane in (c).

## 8b. Cost picture for P2/P3 (operator ask 2026-06-11: fees, vs now, how to limit)

**Now (post-Tier-1):** Railway engine + crons ~$5–20/mo (the 15-min ingest adds ~$2–5 of that) · data $0
(all free tiers) · LLM at ingest ≈ pennies/day — news scoring is content-hash cached (only NEW headlines
bill, ~$2.5e-6/call on the cheap tier; the 115k-item narrative corpus cost $4.77 TOTAL).

**Audit finding (fixed 2026-06-11):** the 15-min cron would have multiplied the two PAID per-pass LLM
sources (xAI LiveSearch twitter sentiment, llm_index rubric scores) ×24 — calls scaled with cron cadence,
not data freshness. Fixed: `llm_source_min_interval_minutes` (default 60) skips a paid source while its
stored series is fresh. Spend is now bounded by the interval regardless of cron speed.

**P2 (credibility pipeline):** compute $0 marginal (runs inside existing crons). LLM cost = claim
extraction only — one cheap call per NEW post (content-cached, never re-extracted), bounded by hard caps
(max posts/handle/pass + the pass throttle). A 20-handle panel polled hourly ≈ low hundreds of new posts/day
≈ **well under $1/mo** on the cheap tier; Grok LiveSearch pulls ride the existing xAI credits, same throttle.
Phases 2–3 (resolution, authority) are deterministic — $0.

**P3 (worker):** the always-on instance is the cost: **~$5–15/mo** Railway + ~$0–25/mo Supabase growth
(within Pro). Its collectors are the same free APIs; its LLM enrichment inherits the same content-hash
caching + budget guard. Hard rule: alert when monthly compute exceeds the `costs` budget line.

## 9. Per-strategy plain-language summaries (decision: Claude Code + backfill)

- Storage: `research_notes` (kind=`summary`) — table already exists with `strategy_version_id`,
  `body_md`, `structured`; zero schema change. `structured` carries `{facts_hash, model, prompt_version}`;
  `facts_hash` = hash of the deterministic inputs (gate verdict, kill reasons, key metrics, lane,
  forward stats) so a summary goes visibly **stale** when the numbers change, and backfill is targeted.
- Write path: Claude Code at bulk-author time + a `/backfill-summaries` skill (reads strategies missing
  a summary or with stale facts_hash → writes via the engine API or DB). $0 marginal on the Max sub.
- Read path: strategy detail API includes the latest summary + staleness flag; the strategy page renders
  it with an honest "no summary yet" empty state. Advisory-only — displayed beside, never instead of,
  the deterministic facts.

## 10. Phases & acceptance criteria

- **P0 (Tier 1 + prerequisites)** ✅ SHIPPED 2026-06-11: closed-candle guard · ingest 15min ·
  hourly mark+intraday lane · 00:10 crypto clock.
  ✓ when: `tracks.updated_at` never older than ~70 min while Railway is up (verify post-deploy).
- **P1 (event store + event-study harness):** `market_events` store (PG+JSONL) · deterministic
  event-study core (`research/event_study.py`: market-model SCARs, CAR windows, pre-window leakage,
  confounder exclusion, matched placebos, RI p-values, BH-FDR) · GDELT corpus bridge · first
  pre-registered run (§4.3.1) executed by the operator (Modal/local).
  ✓ when: a reproducible verdict (PASS/FAIL/INSUFFICIENT) exists for experiment 1 with placebo +
  FDR discipline, persisted to `gate_verdicts`.
- **P2 (credibility pipeline live):** voices Phase 0 wired to a cron with a pre-registered handle
  list · claims/outcomes/authority running on recorded data · source scoreboard on the web reading
  per-source skill/authority (+ the `/profile-source` freshness badge pattern).
  ✓ when: ≥10 sources carry walk-forward skill scores with honest n; `authority_weighted_claim_signal`
  accrues as a PIT feature.
- **P3 (worker, the Tier-2 core)** ✅ CODE SHIPPED 2026-06-11 — **IN-PROCESS, OFF BY DEFAULT** (two
  operator decisions same day: no second Railway service — lean — and inert until local testing;
  `REALTIME_WORKER_ENABLED=1` activates). `cosmu/realtime/`: Binance WS closed-1m-candles →
  `bars_intraday` (PG-durable, 1m→5m retention rollup) · budget-guarded poll collectors
  (RSS/CryptoPanic/Polymarket) → `market_events` with receipt-time `available_at` · 60s heartbeat →
  events ledger · `GET /realtime/status` + the Strategies-page staleness badge · standalone entrypoint
  kept as the split-later option. The worker RECORDS, never executes.
  ✓ when (post-activation): a 1m bar is queryable < 30s after close, 7 consecutive days, zero manual
  restarts; events carry receipt-time `available_at` from day one.
- **P4 (event-driven executor + exploratory lane, gated on §8 sign-off):** `bar_closed` triggers the
  intraday lane through the one order path · exploratory lane if approved.
  ✓ when: an intraday paper track reacts within one bar period with fills through the standard
  gauntlet, and the daily lane is untouched.
- **P5 (paid social, profit-gated):** X API / LunarCrush evaluation only when trailing-30d live net
  P&L > 2× the spend; any new feed needs a `/profile-source` GO on ≥30 days recorded-live history.

## 11. Out of scope

HFT, order-book/microstructure strategies, colocation, tick storage, any paid feed before the profit
gate, any LLM in the order path, and backdating scraped archives into trading features.
