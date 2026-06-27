# Cosmu v2 — Implementation Log

> Tracks what is actually built and the decisions taken, so `VISION.md` (contract) and `docs/archive/BUILD_PLAN.md` (historical how) stay honest. When code and the big docs diverge, reconcile here on purpose.

## Built

### Independent replication cohort (R3) — the GWAS "replication is the final arbiter" gate (2026-06-27)
*Cross-disciplinary playbook bridge #5 + the meta-lesson "validation lives on data the discovery never touched"
(`docs/reports/cross-disciplinary-playbook-2026-06-26.md`). Full writeup:
`docs/reports/replication-cohort-r3-and-sequential-paper-test-2026-06-27.md`.*
- **`research/replication_cohort.py` — the R3 step.** Takes a Gate (R1) survivor's **FROZEN** spec (`params_hash`,
  **no refit**) and re-runs it on **3–5 HELD-OUT symbols it was NOT discovered on**, demanding a **replication
  quorum (≥ 2 of N replicate net-of-fees)** before the survivor is credible — no replication = a single-cell overfit
  the BRUT per-combo Gate passed. `FrozenSurvivor` + `run_replication_cohort` enforce **no-refit** (a `params_hash`
  mismatch ⇒ verdict `DRIFT`, fail-closed), **held-out disjointness** (a held-out symbol overlapping the discovery
  universe is dropped), and the **locked per-cell predicate** (`n_obs ≥ 36` AND `net > 0` AND beats B&H on Sharpe OR
  a materially-lower drawdown — the SAME 0.75 bar `equity_faber_gtaa.validate()` uses).
- **Staged R-lane.** R1 = discovery Gate (time axis, LOCKED) → R2 = `equity_taa_robustness` (parameter axis) → **R3 =
  replication** (data axis, the GWAS final arbiter). R3 is **ADDITIVE**: it changes no `GateSettings` /
  `PREREGISTERED_BAR` constant, registers **no trials** (confirmation, not a search), and can only demote a
  credibility claim — never promote past R1, never move money.
- **Equity-TAA adapter + operation.** `faber_gtaa_survivor()` reuses Faber GTAA's own frozen single-asset 10m-SMA
  timing primitives (held-out QQQ/IWM/EEM/TLT/DBC, disjoint from the SPY/EFA/AGG/GLD/IEF/SHY sleeves). CLI
  `python -m cosmu.research.replication_cohort`; `persist_replication_verdict` writes one `gate_verdicts` row
  (`kind='replication'`, decision = the R3 verdict so it can never masquerade as a funding `PASS`) — no schema
  change. The real run needs the equities total-return cache (a data-network task → M2/Modal); absent it the CLI
  degrades to `INSUFFICIENT-DATA` honestly (never fabricates a number). Tests: `tests/test_replication_cohort.py`
  (18, offline/deterministic).
- **DESIGN ONLY (not built):** elevate the paper/forward lane from the 30-day time-WAIT (`PAPER_MIN_DAYS`) to a
  formal **anytime-valid sequential test** (e-process / mixture-SPRT over `live_eligibility.forward_daily_returns`),
  specified in the report §3. No live/money-path code touched.

### Honest trial-count ledger — the DSR deflates against the TRUE number of trials (2026-06-27)
*Closes the "scariest self-deception flaw" (docs/reports/cross-disciplinary-playbook-2026-06-26.md bridge #2 +
red-team #1): the DEPLOYED funding path is BRUT (`lab/finder.py` + `evolution/loop.py` → `cohort.promote_brut`),
which deflated each (strategy×symbol×venue) cell only by its OWN per-combo param-grid count and deliberately
registered NO global trial. So the N fed into `scorer.expected_max_sharpe` EXCLUDED the seeder sweep, the
exit-envelope sweep, every cell replayed for a signal family, and abandoned tunes — the Gate was rigorously
strict on a DISHONEST, undercounted N.*
- **New `trial_ledger` table** (schema.sql + schema_postgres.sql + migration `2026-06-27_trial_ledger.sql`,
  schema-probe gated `store.trial_ledger_available` so a pre-migration prod table no-ops): one row per LOOK,
  tagged `lane` · `family` (the signal family looks decorrelate within) · `symbol` · `venue` · `sharpe_per_obs`
  · `rho_bar` (the family's measured avg pairwise return corr). Separate from the legacy `trials` family-counter
  the research/FDR gate reads, so **no existing gate verdict or funding decision changes** — only an audit table
  is added. Append-only, out of any LLM's reach.
- **The BRUT finder + loop now record every look** (`record_looks`, best-effort) under their spec's family with
  the family's measured `rho_bar` — seeds, mutations, wildcards, the exit-envelope fan, AND every abandoned tune.
  The locked per-cell BRUT verdict math is UNCHANGED (`test_finder_registers_no_trials_brut` still holds — the
  legacy `trials` count stays 0; the per-cell DSR invariance/parity tests stay green).
- **Decorrelated EFFECTIVE-N** (`master/trial_ledger.effective_n`) = Σ over families of
  `scorer.effective_trials(K_family, ρ̄_family)` — REUSES the locked correlation haircut N/(1+(N-1)·ρ̄). A dense
  correlated family collapses toward 1/ρ̄; across families looks are independent and summed (no cross-family
  haircut ⇒ N errs HIGHER = stricter = honest). Folds in the legacy `trials` rows for the whole-machine count.
- **Survivor recompute** (`recompute_dsr_at_honest_n` + CLI `scripts/research/recompute_survivor_dsr.py`):
  recomputes a survivor's Deflated Sharpe at the honest effective-N and reports whether it STILL clears the
  LOCKED DSR 0.95 gate. Only N changes — DSR 0.95 / min-trades / PBO / FDR-q are untouched. On the offline
  fixture the seeded survivor still cleared (synthetic correlated symbols → tiny decorrelated N; synthetic
  sharpe_per_obs=0.73 → DSR pinned at 1.0), but for a REALISTIC modest survivor (sharpe_per_obs=0.12, n_obs=250)
  the same real math flips it: DSR 0.970 (clears) at the dishonest N=1 → 0.546 (fails) once N is made honest.
- 16 new tests (`tests/test_trial_ledger.py`). Compute stays bounded (SQL group-by + arithmetic; recording rides
  the existing screens — no new backtests).

### Realtime-data-lane P0+P1 — closed-candle guard, Tier-1 cadences, the event-study machine (2026-06-11)
*Operator-approved epic (`docs/epics/realtime-data-lane.md`): cut reaction latency from ~24h toward minutes AND
open the orthogonal-data axis the search campaign demanded — backtesting unstructured events (news/tweets/
Polymarket) honestly, in event time, on intraday bars.*
- **Closed-candle bar guard (the PRE-LIVE freshness gate, shipped).** All three crypto providers
  (`data/market.py`) drop the exchange's in-progress candle before caching, refetch a covering-but-stale cache,
  and let fetched rows repair poisoned cached rows on ts collision; offline behaviour still degrades to the
  cache. Clock injectable; regression suite `tests/test_market_cache_freshness.py`. (Yahoo equity still serves
  an in-progress day bar — daily/equity tracks stay on the daily clocks.)
- **Tier-1 cadences (`railway.toml`).** Ingest 6h → 15 min · a second full forward-test clock at 00:10 UTC
  (crypto daily tracks act minutes after their close) · an HOURLY lane (`cosmu.orchestrator.loop --intraday`)
  that steps only sub-daily (1h/4h) tracks (`step_tracks(bar_sizes=…)`) and re-marks every held position —
  "24h perf" is now at most ~1h stale. Same-closed-bar re-runs stay no-ops (decision-bar client_order_ids).
- **The event machine (epic §4–5).** `data/events_store.py` — typed `MarketEvent` records with TWO clocks
  (ts = publish time for event studies; available_at = receipt time, the only honest trading-feature axis;
  scraped archives are never backdated), JSONL + PG twins, deduped append-only, `market_events` DDL in both
  schemas (PG applies out-of-band on Supabase — operator action). `research/event_corpus.py` — RavenPack-style
  root-event clustering (breaker vs echoes, decaying novelty) on the deterministic keyless embedding +
  honest-availability corpus loaders. `research/event_study.py` — market-model SCARs on intraday bars,
  pre-registered CAR windows + a PRE-event leakage window, confounder/market-comove exclusion, randomization
  inference vs weekday×hour×vol-matched placebos, BH-FDR across cells; estimation window ends before the
  pre-window; thin cells abstain. `enrich_market_events` (folded into `ingest/llm_formatter.py` — the ONE
  formatter) fills typed event fields content-only with a lexicon fallback that never fabricates a category.
  `research/event_study_run.py` — the runnable pre-registered experiment CLI (corpus → cluster → enrich →
  cached 1m bars → verdict table + JSON report). ~40 offline tests across the five new test files.
- **P2 — credibility pipeline LIVE (same day).** The dormant Phases 0–3 wired end-to-end, cost-capped:
  `config/voices.py` (PRE-REGISTERED panel, ships empty — registering a voice is a deliberate operator act,
  the anti-survivorship discipline) → `ingest/voices_pass.py` (hourly cron: key-gated timeline pulls →
  durable deduped posts in `market_events` → LLM claim extraction on NEW posts only, hard per-pass caps →
  `voice_claims` → deterministic Brier-skill/primacy/PageRank → the flat human-readable `voice_scoreboard`
  + the two `social_authority` PIT features accruing in `alt_data`). Surface: `GET /mind/credibility` + a
  Source-credibility section on `/mind/sources` (nulls = "untested", never 0). Plus the paid-LLM ingest
  throttle (`llm_source_min_interval_minutes`, default 60): xAI/llm_index spend now scales with data
  freshness, not cron cadence. Decision recorded (epic §8): NO new gate / lighter lane — revisit only after
  the first event-study verdict.
- **P3 — realtime recording worker CODE SHIPPED (same day, operator decisions: in-process — no second
  Railway service — and OFF by default until local testing; `REALTIME_WORKER_ENABLED=1` activates).**
  `cosmu/realtime/`: Binance WS closed-1m-candle consumer (reconnect + backoff + jitter, injectable
  connect seam, import-guarded `websockets` dep) → durable deduped `bars_intraday` with 1m→5m retention
  rollup (no-loss-window delete) · budget-guarded poll collectors (RSS keyless / CryptoPanic key-gated /
  Polymarket) → `market_events` with receipt-time `available_at` + lexicon enrichment ($0) · supervised
  crash-isolated task tree + 60s heartbeat → events ledger · `GET /realtime/status`
  (off|never|fresh|stale) + the Strategies-page staleness badge · standalone entrypoint kept as the
  split-later option. The worker RECORDS, never executes; crons remain the fallback lane. 14 offline
  tests (`tests/test_realtime_worker.py`). Activation steps live in
  `docs/epics/tasks/local-agent-post-merge-actions.md` (its launch prompt replaced the P3 task file).

### Trust workflows — SIM→live variance attribution + a data-trust source audit (2026-06-04)
*Two review-only "trust" surfaces, both deterministic + offline + out of the gate/money path. They EXPLAIN and
RECOMMEND; the deterministic lifecycle + live toggle alone dispose of capital, and a human still wires a feature.*
- **`cosmu/research/attribution.py` (new) + `/variance-attribution` skill.** Decomposes a funded track's
  `(live − sim)` per-period divergence into named, signed buckets — **fees · slippage · funding · signal-decay ·
  regime** — plus a first-class **residual** (components reconstruct the divergence exactly; the unexplained part
  is named, never hidden). Cost legs read the `is_paper` line of the `executions` ledger (sim vs live fills, signal
  and fill never collapsed); `signal_decay` reuses `master/drift`'s edge-decay fit; `regime` is a Brinson
  allocation effect on the regime mix. Turns "the backtest was a lie" into "…BECAUSE costs / a dead edge / a regime
  draw". `python3 -m cosmu.research.attribution <version_id>`; offline tests in `tests/test_attribution.py`.
- **`cosmu/ingest/profile_source.py` (new) + `/profile-source` skill.** Auto-profiles a NEW alt-source's
  point-in-time history into **GO / REVIEW / NO-GO** before it can become a feature. Composes `ingest/coverage.py`
  for coverage · gaps · staleness · look-ahead, then adds the two checks coverage can't make about an untrusted
  feed: **PIT-lag honesty** (a feed that claims it's known sooner than its declared release lag is a latent
  look-ahead leak → hard NO-GO) and **revision safety**. Wired as step 6 of `add-data-source`. `python3 -m
  cosmu.ingest.profile_source <provider> <symbol> <metric> --declared-lag-hours N`; tests in
  `tests/test_profile_source.py`.

### The Mind — standardized self-knowledge + a railguarded analyst-panel debate (2026-06-03)
*Owner ask: make the agent's reasoning legible and "smart, not a side project" — a standardized view of what the
machine knows, how it thinks, and what it has learned (ML as a pillar but not the only one: technical, macro,
sentiment, social/news, positioning, OSINT), inspired by the multi-agent "TradingAgents" debate. Railguarded:
LLMs may help narrate, but the **deterministic Gate alone disposes of money** — the Mind never funds or fires.*
- **`cosmu/mind/` (new module).** `analysts.py` — a TradingAgents-style panel where each perspective reads ONE
  family of the agent's **existing** point-in-time signals and emits a standardized `Stance` (lean · conviction ·
  rationale · evidence). **Market** analysts (Technical from the regime classifier · Macro from FRED · Sentiment
  from Fear&Greed · Social&News from `news_sentiment` · Positioning from funding/liquidations · OSINT from air
  activity) vote a direction; **process** pillars (ML survival model · graveyard Memory) report the machine's
  self-knowledge. A perspective with no ingested feed **abstains** — it never fabricates a read. `debate.py`
  combines them into a deterministic `MindSnapshot` (consensus · conviction · panel agreement · bull/bear case ·
  contested flag · plain-language narrative). `snapshot.py` `build_mind()` bundles **KNOWS** (sources grouped by
  perspective + freshness), **THINKS** (the panel + debate), **LEARNED** (memory insights, ML state, regime
  coverage, gate efficiency). Deterministic, offline, LLM-optional; **zero LLM in any scoring/gate/money path.**
- **Reflection memory.** `reflect()` persists a point-in-time record of the debate (additive `mind_reflections`
  table) and an audit event each autonomous tick, so the agent accrues a memory of HOW IT THOUGHT over time.
  Defensive writer: the event always records; the richer row degrades gracefully on a prod DB that hasn't applied
  the additive migration yet (`knowledge/migrations/2026-06-03_mind_reflections.sql`, owner-applied out-of-band).
- **Schema (additive, owner-applied).** `mind_reflections` added to `schema.sql` + `schema_postgres.sql`; the
  `alt_data` table added to the SQLite schema too so the store-backed point-in-time read (and the Mind's "what it
  knows" freshness) works uniformly local + prod. Nothing renamed, nothing dropped.
- **API + contracts.** `GET /mind` → `MindResponse` (panel · debate · knows · learnings); TS contracts
  regenerated from OpenAPI (never hand-typed). Wired `reflect()` into `POST /autonomy/tick`.
- **Web — the Mind page (`/mind`, new first-class destination).** Consolidates the previously **scattered**
  brain/memory/intelligence/skills surfaces into one clean view: **How it thinks** (consensus card + analyst
  stance cards, with a "Reasons · never funds" railguard badge), **What it knows** (sources by perspective +
  freshness, honest "not ingested yet"), **What it has learned** (ML model state · regime-coverage grid · gate
  efficiency · memory insights · distilled skills). New nav entry (Brain icon). The duplicated "what the machine
  has learned" block was removed from `/lab` (it now lives on the Mind). `typecheck` + `next build` green (18
  routes incl. `/mind`); naming guard green. `tests/test_mind.py` (7 tests) locks: honest abstention on an empty
  store, ingested signals driving a consensus, determinism, the contested-read flag, and `reflect()` persisting +
  degrading gracefully when the table is absent.

### Fee single-source, funnel data, skills, closed research loop (2026-06-03)
- **One source of fee truth.** `VenueCatalog.venue_for(spec.universe.venues)` resolves the venue a spec is PRICED against; the Lab screen (`lab/finder.py`, `evolution/loop.py`) and the gate (`research/gate.py`) now derive fees from it instead of hardcoding Binance. An IBKR-equity spec is screened at IBKR fees, not 10 bps — the multi-venue fee model is now actually exercised, not just defined. (`tests/test_venue_fees.py` locks `venue_for`.) *Honest scope:* the engine is long-only spot, so there is no perp-funding cost to deduct — modeling one would fabricate perp mechanics; funding stays a point-in-time signal.
- **Strategies funnel is now data, not a button row.** The `/strategies` pipeline strip is a non-clickable stepper carrying live per-stage counts (`PopulationResponse.live` added); it shows the funnel kill-rate instead of duplicating the nav.
- **`.claude/skills/` created** — the 10 runnable playbooks `AGENTS.md` references now exist (scan-signals, groom, create-strategy, add-data-source, add-venue, run-gate, deploy-check, deploy-iterate, debug-strategy, import-pine).
- **Agentic research loop CLOSED.** `research.py:run_research_pass` already gathered context off the propose-only tool bus but never used it; it now distils prior-art features (`_prior_art_from_context`) and the author CONDITIONS on them (`draft_from_brief(prior_art=…)`) — folded in, asset-class-validated, memory-pruned, with citations on the audit trail. The LLM proposal seam receives the research context too. Still LLM-optional, offline-deterministic, ZERO LLM calls in CI, and the deterministic Gate alone disposes. (`tests/test_research_agent.py`.)

### Per-venue fee realism + jurisdiction (2026-06-03)
- `spine/venue.py` — venues now carry **volume-tiered fee schedules** (`VenueFeeTier`), a `live_enabled` flag (data/paper venues can't move money), and `restricted_jurisdictions`. `Venue.effective_fee(volume_30d_usd)` picks the richest tier met; `Venue.live_legal_in(country)` and `VenueCatalog.live_legal_venues(country)` make live availability a venue+country fact, not a global toggle. Catalog gains **Kraken, Coinbase, Alpaca** alongside Binance/IBKR/Polymarket with realistic fees — encoding the finding that **US-legal crypto (Kraken ~26 / Coinbase ~60 bps taker) is worse than Binance (~10), while IBKR equities are <1 bp**. Binance/Polymarket are `restricted_jurisdictions=["US"]`; Alpaca is data/paper (`live_enabled=False`).
- `execution/costopt.py` — `FeeSchedule.from_venue(venue, volume_30d_usd)` is the single bridge from the catalog to the cost model, so a backtest/paper prices the **same fees the live venue would charge** at the account's volume. `tests/test_venue_fees.py` locks all of this.
- New skills: **`/scan-signals`** (unbiased cross-asset signal sweep → testable hypotheses with disconfirmers → the gate; propose-only) and **`/groom`** (self-maintenance: prune dead code, graveyard stale strategies, keep docs/memory lean, `pnpm verify` green). Registered in `AGENTS.md`.
- *Note:* `universe.py` `VENUES_WITH_DATA` stays Binance-only — the new venues appear in the catalog and show "no data yet" until their data/exec adapters are wired (honest, not faked).

### Spine & control plane
- `spine/engine.py` — deterministic facade (`run_backtest`/`run_sandbox`/`run_live`), `VenueCatalog`, fill-log, seeded determinism. Live blocked unless the global toggle is on.
- `knowledge/store.py` — SQLite/Postgres-ready store. **Batched writes:** `Store.batch()` yields one connection + one transaction for a whole cohort (400 candidates persist in ~0.15s vs thousands of connections before). WAL + `synchronous=NORMAL`.
- `master/scorer.py` + `master/risk.py` — deterministic scorer (deflated Sharpe, PBO, gates) and risk gauntlet. **Out of the agent's reach.**

### Autonomous evolution loop (`evolution/`) — the differentiator
- `loop.py` `FarmLoop.run_cohort(...)` — generates a wide population (seeds + chat briefs + Pine imports → exploit mutations + explore wildcards), compiles + static-checks each, runs a cheap deterministic real-bar Binance spot screen, scores through the out-of-reach scorer, keeps gate-passers as standalone SIM tracks (default `$1,000`, `sim_track_capital`), sends the rest to the graveyard **with kill reasons**. Seeded/reproducible for a fixed bar cache/provider.
- `mutator.py` — §F operator catalog (`swap_feature`, `widen/narrow_param`, `tighten/loosen_risk`, `change_horizon`, `add_condition`, `crossover`) + wildcard generators. Two lanes (exploit single-operator for clean attribution; explore unrestricted).
- `seeder.py` — diverse seed templates (breakout, mean-reversion, carry, momentum) so the population never starts collapsed.

### Market data + honest Lab screen
- `data/market.py` — Binance spot OHLCV provider with ccxt first and stdlib REST fallback, cached on disk under `.cosmu/market_data/binance`. Tests inject a fixture provider so CI does not depend on the current exchange/network.
- `data/backtest.py` — deterministic long-only bar backtest for the Lab screen. Signals use prior-bar data, fills occur at the next bar with conservative slippage, exits charge Binance taker fees, and the last fifth of bars is reserved as holdout evidence. Unsupported non-price features produce no trades instead of invented edge.

### Pine Script import
- `strategy/pine.py` `translate_pine(source)` — TradingView Pine → typed `StrategySpec`. Maps `ta.*` to the feature registry; resolves `input.*` vars, tuple destructuring (`[macd, signal, _] = ta.macd(...)`), and band breakouts (`close > upper` → `bb_z`). **Key invariant:** Pine's hardcoded thresholds/lengths are **lifted into a fitted `param_space`** — magic numbers become a search space, never baked in.
- `strategy/pine_samples.py` — community-style sample library (RSI, MACD, golden cross, Bollinger, ADX); every sample is asserted to translate + compile in tests.

### Chat strategy authoring (`lab/author.py`)
- `draft_from_brief(brief, features?, venues?)` — plain-language brief → validated `StrategySpec` draft. Picks a base template by intent, retargets universe/horizon/risk, detects/accepts features, derives **data sources** from the feature registry. **Guardrails:** structure-only (thresholds stay in `param_space`), money-adjacent intent flagged for approval, scorer never in this path. LLM-optional: deterministic template-match today; an OpenRouter call slots into the same seam when a key is set.

### API & frontend
- New endpoints: `POST /evolution/run`, `GET /population`, `POST /strategy/pine`, `GET /strategy/pine/samples`, `POST /lab/author`, `POST /lab/author/run`. TS contracts regenerated from OpenAPI (no hand-typing).
- Web (`apps/web`, Next 16 + Tailwind v4 + shadcn-style "Obsidian Iris" theme): Dashboard, **Farm** (run cohorts, watch the funnel, graveyard, Pine import + sample picker + file upload), Leaderboard, Strategy detail, and a **chat authoring Console** (brief → draft → send to farm). Graceful offline-demo fallback throughout.

### Universe gate (operator settings)
- `spine/universe.py` — the global "what may we trade" gate, backed by `venues.enabled` (no new schema). `enabled_universe(store)` returns the enabled venue/asset-class sets; `set_venue_enabled` flips a venue **audited** (appends a `venue_toggle_changed` event) and **refuses to disable the last venue**. `VENUES_WITH_DATA`/`CLASSES_WITH_DATA` mark which paths actually have data wired today (Binance/crypto only).
- The evolution loop reads the gate once per cohort: a disabled venue/asset-class yields no symbols → no trades → killed. `POST /evolution/run` returns a clear 400 when no live-data venue is enabled.
- API: `GET /universe`, `POST /universe/venue` (typed, contracts regenerated). Asset-class enablement is **derived** — a class is on iff ≥1 of its venues is on.
- Web: `components/universe/universe-settings.tsx` (ticking toggles, plain language, "no data yet" honesty markers, offline-safe) rendered both as a Dashboard card and on the new `/settings` route stub.

### Phase 0+1 wall & gate (BUILT)
- `master/scorer.py` — real PSR/Deflated-Sharpe (skew+kurtosis adjusted), expected-max-Sharpe with **global trial accounting**, and a **CSCV** PBO. `master/trials.py` (cumulative trial ledger), `master/holdout.py` (one-shot holdout, re-requests refused), `data/universe_calendar.py` (point-in-time listing → no survivorship), `data/altdata.py` (append-only point-in-time snapshots + causal `rolling_zscore`). `data/backtest.py` gained capacity-aware slippage + regime folds + per-obs moments. `research/gate.py` `evaluate_gate` (single-signal stop-or-go) + offline fixtures.

### Phase 1.5 — aggregation-edge ablation gate (BUILT)
- **Three free sources behind the alt-data seam** (`data/altdata.py`): `FundingRateProvider` (Binance fapi, long filter), `FearGreedProvider` (alternative.me), and a `NewsProvider`/`NewsItem` unstructured path — each with offline fixtures, append-only point-in-time snapshots.
- **LLM universal adapter** (`ingest/standardize.py`): unstructured headline → validated `StandardizedNews` (`event_type/sentiment/confidence`), **content-hash cached**, **frozen `TRANSFORM_VERSION`**, deterministic offline lexicon path so the gate runs with no key; the LLM slots in at one seam and **never runs in any backtest/scoring path**.
- **Ablation gate** (`research/gate.py` `evaluate_ablation`): three arms on the same universe/costs/wall — **price-only vs +alt-data vs buy-and-hold** — plus a **drop-one** per-source marginal-Sharpe report, CSCV over a diverse alt-arm grid, the pre-registered bar, and every arm counted in the global trial ledger. CLI `python3 -m cosmu.research.gate` prints the three-arm verdict offline. On the seeded fixture: PASS, alt > price-only > buy-and-hold, news is the paying source.

### Free-data ingestion pipeline (BUILT)
- `ingest/pipeline.py` — `ingest_free_sources(...)` pulls funding/OI, Fear&Greed (market-wide), and news headlines via the free providers into the **append-only point-in-time** `AltDataStore`; news is LLM-standardized to a numeric `news_sentiment` series **at ingest only** (cached). Idempotent (re-runs never change the as-of view), offline-safe via injected providers. This is the seam the *real* gate reads once a scheduled worker runs it live.

### Postgres / Supabase backend (BUILT + live-verified)
- `knowledge/store.py` — **dual backend, one code path.** `Store` auto-detects `DATABASE_URL`: `postgres(ql)://` → psycopg2 (RealDictCursor, pooled-DSN cleaned of `pgbouncer`/`connection_limit`), else SQLite (local/test). A `_Conn` wrapper unifies `?` placeholders + dict rows; `INSERT OR IGNORE` → dialect-neutral `ON CONFLICT (id) DO NOTHING`; Postgres `migrate()` assumes `schema_postgres.sql` was applied out-of-band and only seeds the live-toggle row. `settings.py` loads the repo-root `.env.local`. **Verified end-to-end against live Supabase**: migrate, venue seeding, events, universe round-trip, trials. 50 SQLite tests stay green.
- `data/altdata.py` `PgAltDataStore` — central append-only point-in-time alt-data over the `alt_data` table (`SELECT DISTINCT ON (ts) … ORDER BY ts, id DESC` = latest-revision-wins, available-by `as_of`). Drop-in for the JSONL store, so `ingest/pipeline.py` is unchanged. **Verified live** (point-in-time + revision).
- **Real data flowing:** live Fear & Greed (alternative.me) ingested into Supabase `alt_data` and read back point-in-time. Fixed a production bug: the alt-data HTTP providers now use the **certifi SSL context** (HTTPS failed on hosts without system CA certs — sandbox, slim images, Railway).
- Dep added: `psycopg2-binary`.

### Phase 1.6 — cross-asset extension (BUILT)
- **Asset-agnostic core contracts** (`core/interfaces.py`): one shape (`Instrument`/`Bar`/`Feature`/`Signal`/`Order`/`Fill` + `DataAdapter`/`ExecutionAdapter`/`Strategy`/`SignalProducer` Protocols) for crypto/equity/fx/prediction. Every market datum carries a point-in-time `available_at`; `delisted_at` doubles as prediction-market expiry (survivorship/expiry safety in one field).
- **Three free data adapters behind the core seam** (`adapters/data/`): `CryptoDataAdapter` (Binance spot + funding/fear-greed), `EquityDataAdapter` (free daily bars via `StooqDailyBarsProvider` + FRED macro — **free-bars survivorship limit declared, not hidden**: `survivorship_complete = False`, Norgate replaces at the live phase), `PredictionDataAdapter` (Polymarket public CLOB odds-as-price; **odds-as-data only, no execution this pass**; resolved markets leave `universe(as_of)`). New free providers: `FredMacroProvider` + `PolymarketOddsProvider` (numeric → no LLM), `StooqDailyBarsProvider`. All offline-testable via injected fixtures.
- **Cross-asset transfer features** (`config/feature_registry.py`): `pm_risk_on` (prediction-market odds → cross-asset risk-on/off tag), `xasset_risk_appetite` (crypto funding → cross-asset risk appetite), `macro_regime` (FRED → shared regime tag) — each with a one-line prior + pinned `transform_version`. The point is *transfer*: one market's price as another's feature.
- **Four-arm cross-asset ablation** (`research/gate.py` `evaluate_cross_asset_ablation`): on the same windows/costs/wall — (1) single-asset price-only · (2) single-asset+alt · **(3) cross-asset+alt** · (4) buy-and-hold — plus **per-source AND per-asset-class drop-one**. Pre-registered bar: arm (3) net return > arm (1) AND > arm (2) AND > buy-and-hold, plus the statistical gate (≥30 trades · PSR ≥ 0.95 after global-trial deflation · CSCV PBO < 0.5 · ≥2 regime folds · maxDD < 0.25 · ≤12 counted attempts). Verdict `PASS` / `STOP-narrow` (keep single-asset, cut classes that didn't pay). Built on the proven 1.5 primitives (reuses `_arm_metrics`/`_build_signal`/`_simulate`); drop-one is a diagnostic, not a counted trial. CLI `python3 -m cosmu.research.gate` prints the four-arm verdict offline. On the seeded fixture: **PASS**, cross-asset > single-asset+alt > price-only > buy-and-hold, and the **transfer features (risk_on, macro_regime) are genuine top payers** in the drop-one.
- **Real-data seam (ingest → store → gate, offline-proven):** `ingest/pipeline.py` `ingest_cross_asset_sources` extends the free-source pass with the two cross-asset transfer series — FRED macro (→ `macro_regime`) and Polymarket odds (→ `risk_on`), numeric → no LLM, the native-id→semantic-name map living at ingest. `data/altdata.py` gained `read_all` (full revision history) + `StoreBackedAltProvider`, which adapts the append-only point-in-time store into the gate's `AltDataProvider` seam — so `evaluate_cross_asset_ablation` runs unchanged on real ingested data. With `news_provider=None` the gate reads the pre-standardized `news_sentiment` series from the store, so the **gate/scoring path makes ZERO LLM calls** (asserted by poisoning the LLM seam in a test). End-to-end test: fixture providers → ingest into a temp `AltDataStore` → `StoreBackedAltProvider` → gate reproduces **PASS**; a re-run never changes the point-in-time view. Going live is now a provider swap (Stooq/FRED/Polymarket public APIs), not a rewrite.
- **Promotion/portfolio/execution/orchestration scaffolding** (Phase-2-facing, built + green): `master/cohort.py` (cohort promotion gate — register every candidate as a trial, promote only on per-candidate significance AND Benjamini-Hochberg FDR across the cohort, rank by net-of-cost profit), `master/fdr.py` (BH-FDR), `master/cv.py` (purged+embargoed CPCV), `portfolio/rotation.py` (per-track decay detection + defunding — no pooled allocation), `execution/costopt.py` (maker/taker net-of-cost choice + fee tiers), `orchestrator/{agent,efficiency}.py` (a pluggable stage pipeline inside a live/kill/pause safety envelope + capability-per-dollar meter). All deterministic, out of any LLM path.

### Functional next version — free sources, env profiles, UI restructure (BUILT)
*Owner decision (2026-06-01): make the app functional + usable now and add several free data sources, rather than keeping all UI/data work deferred to a real-data gate PASS. The gate-first discipline still holds for paid vendors, live execution, and the Phase-2 factory.*
- **Six free data providers** behind the existing seams: `KrakenSpotOHLCVProvider`, `BybitSpotOHLCVProvider`, `YahooDailyBarsProvider` (`survivorship_complete=False`, declared) in `data/market.py`; `CoinglassLiquidationProvider` (metric `liquidations`), `CboePutCallProvider` (market-wide `putcall_ratio`), `GdeltNewsProvider` (real headlines → existing LLM-standardize path) in `data/altdata.py`. All stdlib-HTTP + certifi SSL, disk-cached, separable parse fns, point-in-time `available_at`, offline-tested via canned payloads.
- **Feature**: `liquidation_cascade` (tier0 crypto, prior + pinned transform); `putcall_ratio` given a transform_version for consistency.
- **Ingest**: `ingest_extra_free_sources` (Coinglass + CBOE + GDELT news) added to `ingest/pipeline.py`, append-only/idempotent-in-view, offline-safe.
- **Env profiles**: `APP_ENV` (dev|test|qa|production) selects the env file — dev/test/qa→`.env.local` (local runs share the real dev credentials, 2026-06-16), production→process env only. The free cross-asset gate needs **zero** keys, so an absent `.env.local` still runs the suite hermetically (temp sqlite + offline fixtures). NOTE: the Modal `tests` job runs with `APP_ENV=test`, so it deliberately EXCLUDES `.env*.local` from its image (`remote/app.py` ignore list) to stay hermetic — never bundle prod secrets into the test image.
- **API**: `POST /research/cross-asset-gate` runs `evaluate_cross_asset_ablation` — `StoreBackedAltProvider` (`data_source="live"`) when the store has the ingested transfer series, else synthetic fallback; persists `gate_verdicts` + emits a `cross_asset_gate_run` event. Pydantic `CrossAssetVerdict` → OpenAPI → regenerated `contracts-ts` (the web consumes the generated type, not a hand-typed one).
- **Self-sustained loop (Karpathy "arrange once, hit go", cron-able — NOT a daemon):** `cosmu/ingest/run.py` `run_once()` — one append-only point-in-time pass over the free sources into the store (backend auto-picked by `database_url` like the API; per-source failure logged as a 0 count, never aborts); `python3 -m cosmu.ingest.run`. `cosmu/research/loop.py` `auto_research_pass()` — ingest → run `evaluate_cross_asset_ablation` (live store-backed when `risk_on`+`macro_regime` present, else synthetic) → persist `gate_verdicts` + emit event → return verdict; `python3 -m cosmu.research.loop --passes N [--ingest]`, bounded, deterministic, zero LLM in the gate path. **Live smoke (real APIs, zero keys):** funding (400 pts) + Fear&Greed (1000 pts) flowed; FRED/Polymarket/Coinglass/CBOE/GDELT degraded gracefully (need a free FRED key, a real Polymarket token id, or hit rate-limits) → those report 0 and the loop falls back to the synthetic gate. To run the gate on real cross-asset data: deploy as a Railway cron against Postgres + supply a FRED key + the real Polymarket market token.
- **Web — Overview-led, 4 routes** (`apps/web`): Overview (`/`, lean summary: headline net %, KPI row, one equity chart, "needs you", recent activity, compact gate status), Research (`/research`, merges Farm + a searchable Strategies table + the Edge gate + the new Cross-asset gate "Run" button + graveyard; `/farm` redirects here), Console (`/console`, its own page now — chat author + recommendations + audit stream), Settings (`/settings`). **Clutter removed**: "v2" subtitle dropped from the wordmark; strategy-detail back-arrow + competing header badge removed (single title block). Offline-demo fallback preserved. `pnpm --filter @cosmu/web typecheck` + `build` green.

### Trade-capable V1 — execution + live path (BUILT, dormant & safe)
*Owner decision (2026-06-01): build a complete, holistic V1 that is **ready to trade once keys are set** — capability, not proven edge. Live stays OFF; real money still requires the cross-asset gate to PASS on real data + explicit arming.*
- **Execution adapter** (`adapters/exec/binance.py`): `BinanceSpotExecutionAdapter` (ccxt) — submit/cancel/positions/fills, **idempotent on `client_order_id`**. `resolve_mode()` is the real-money interlock: TESTNET keys → testnet (default, fake money); real Binance ONLY with `BINANCE_API_KEY/SECRET` **and** `live.mode=="real"`; no keys → disabled/paper, no network. Secrets never stored/logged/returned. Pure parse layer unit-tested against a mock ccxt client.
- **Single order path** (`master/execution.py`): every intent clears `master/risk.py` `validate_order_full` (SL/TP required, per-strategy + global caps, min cash reserve, lot/min-notional, drawdown kill-switch, daily-loss auto-disarm, **martingale/averaging-down banned**, memoryless sizing) → submits live only when toggle ON + adapter active + gate-passed + caps free + not killed, else deterministic sim-fill. Persists `executions` + events + `positions`. Wired as the orchestrator's `execute_stage` (replaced the "plans not sent" stub).
- **Portfolio of record** (`master/portfolio.py`): holds positions (new `positions` table), marks-to-market, writes `portfolio_snapshots`, net-of-cost P&L + drawdown, daily-loss tracker. `GET /overview` (the aggregate read-out) now reflects real state (no fabricated numbers).
- **Live API**: `POST /toggle/live` hardened (requires `confirm`), `POST /live/activate` (confirm-gated, caps + eligible), `POST /live/defund`, `GET /live/positions` — all audited; Pydantic → regenerated `contracts-ts`.
- **Web `/live`** (gated, 5th route, dimmed until armed): 2-click activation modal (shows exactly what will trade + caps + a quiet gate note), real positions table, defund controls, daily-loss-vs-cap, mode badge. The web never decides whether an order is real — it surfaces the engine's verdict. Honest empty states replace the old fabricated equity/allocation fallback (demo only when the engine is unreachable).
- **Ops**: `railway.toml` keeps the API as the only persistent Railway process; ALL scheduling moved to the **Modal cron fleet** (`apps/engine/remote/app.py`, 5 schedules: ingest · 4h tick · heartbeat · weekly cold-tier · daily backup). The new `positions` table was applied to the **live Supabase** (additive). **Verified:** 162 engine tests pass · web typecheck + `next build` green (all routes incl. `/live`) · live live-types reconciled to the generated contract.

### Research brain — autonomous strategy authoring + pluggable sources (BUILT)
*Phase 3 (LLM factory), built gate-respecting: LLM **proposes**, the deterministic scorer **disposes**. Fully offline/LLM-optional.*
- **Pluggable data-source registry** (`data/sources/registry.py` — pre-existing seam, now populated): a typed `DataSource` protocol + registry so any agent discovers/queries a source by name; wraps the existing providers (thin adapter, no rewrite). The seam to upgrade data sources later.
- **OSINT example** (`data/sources/osint_adsb.py`): `AdsbDataSource` over the free OpenSky API → aircraft-activity as a point-in-time, availability-stamped, **low-confidence** numeric feature (declared prior, `transform_version`, offline fixture, degrades to fixture on network failure). Registered as `osint_air_activity` in the feature vocabulary — must earn its place via OOS like any source.
- **Propose-only research tool bus** (`lab/tools/research_tools.py` on the existing `ToolBus`): `web_search` (Tavily-opt), `news_read` (GDELT-opt), `social` (LunarCrush-opt), `pine_fetch`, `rag_read` — all read-only, LLM-optional with offline fixtures, keys bound server-side. **Execution is never on the bus** (the bus rejects non-readonly/execute/order-named tools).
- **Autonomous research pass** (`lab/research.py`): gather context off the bus → author N specs (`lab/author`, LLM-optional, referencing named features incl. OSINT) → compile + static-check → run the deterministic evolution screen + out-of-reach scorer → record survivors + graveyard with reasons. CLI `python3 -m cosmu.lab.research [--n N]`, bounded + reproducible. A poisoned router proves no LLM is reachable from the scoring path.

### Money clarity + mobile/desktop polish (BUILT)
- Every $/% now carries an explicit **SIM (simulated) / LIVE (armed)** badge + tooltip — resolves "what is this money?": SIM = simulated on live-shadow prices, no real funds; live = real, off until armed. Per-track % (per strategy) vs the aggregate read-out made unambiguous via a shared tooltip; a "Working strategies" section ranks funded tracks by net-of-fee %.
- Lean Overview answers at a glance: are we making money (headline net % + state label) · which strategies work · what the bot did · total profit — honest empty states, no fabricated numbers.
- Mobile + desktop pass: sticky-first-column scroll-x tables (no page overflow), single-column mobile cards, fluid headline, shrinking charts, smoother transitions, reduced-motion respected. `typecheck` + `next build` green (10 routes).

## Infra (settled) & next phase
- **Where it runs:** **Railway** = the always-on machine (engine API + farm/paper worker + bounded crons, e.g. `research.loop --ingest` 6h) · **Supabase** = Postgres + pgvector (truth) · **Vercel** = web · **Claude Code / local `.md`** (AGENTS.md, `# intent:` headers, skills) = how the coding agent builds/maintains it (non-24/7) · **Modal/E2B** = untrusted agent-written ML, later. Not either/or — the money-machine is hosted; the build/maintain loop is agentic.
- **ML-by-LLM (BUILT):** `ml/survival.py` — tabular survival model (XGBoost/LightGBM if importable, else a pure-Python logistic fallback so CI is dependency-free) trained on labeled store outcomes once ≥30 exist (chronological 75/25 OOS split + AUROC), **orders the validation queue, never vetoes** (rank = permutation only), cold-start = cheap heuristic until trained. `ml/regime.py` — deterministic vol-tercile × trend regime classifier + `regime_eligible` live-gate (a strategy goes live only in a proven regime; empty passport fails safe). Wired: `evolution/loop.py` orders gate-survivors by survival score + records the score + proven-regime passport on `track_opened`; `master/live_eligibility.py` gates the live-eligible set. `GET /research/brain` surfaces it; web `/research` renders the brain (funnel, survivors+score, graveyard reasons, regime, sources incl. OSINT, validation ranking with trained/cold-start). **194 engine tests green.**
- **Next:** **pgvector graveyard RAG** (long-term memory so the brain stops re-walking dead ends — Phase 3 memory) · **live-polish** (true mark-to-market in `/live/positions` + `adapter.fills()` reconciliation + persist toggle state to the orchestrator envelope). Agent-written ML in Modal/E2B (no secrets/venue), artifacts judged by the same out-of-reach scorer, stays gate-gated.

### Great V1 — Strategy Finder + closed loop + user-oriented IA, audited on REAL data (BUILT)
- **Strategy Finder** (`lab/finder.py`): grid-search a spec's param space → screen on real bars → rank by **profit factor + the Gate** → WFO/holdout before promotion → persist winners to the config library (`origin='finder'` Versions + Tracks). Composable, fittable spec modules: `multi_tp`, `break_even`+runner, `ma_trend_filter`, `orb` (upside-only), `fvg_retest`/`fvg_multiple`; **ORB+FVG-multiple** is the seed (`seed_orb_fvg_spec`). `python3 -m cosmu.lab.finder --seed-real` bootstraps real strategies.
- **Closed loop** (`orchestrator/loop.py` `fund_tracks_from_survivors`): each gate-passed survivor → opens its **own standalone SIM track** (fixed per-strategy capital, no pooled wallet) → `master/portfolio` opens real sim positions + marks-to-market. Fixed a boundary bug: qty now rounds **down** so notional can't round a hair over the per-strategy cap (was rejecting every fill).
- **ML-by-NL** (`POST /lab/ml` + Steer page): plain-language asks ("rank survivors by edge-persistence", "retrain") → the survival model (orders, never vetoes). On real data the model **trained** (xgboost, 40 labels).
- **User-oriented IA**: Overview · Lab · Strategies · Paper · Live · Steer · Settings — one job per route; `research/farm/console` are redirect shims. **No "farming" jargon**, **no demo data** (honest connect/empty states; demo removed). `create-strategy` skill + `strategies/inbox` + `docs/GLOSSARY.md` standardize authoring.
- **Audited live on Supabase (2026-06-01):** `seed_real` persisted 24 finder Versions (4 Tracks, 4 gate-passers); 3 standalone SIM tracks were funded; the web (engine on Supabase) renders 20 real ranked Versions, the funded tracks, the trained survival ranking, and a real audit stream — **214 engine tests pass · web typecheck+build green · zero console errors · no demo · no farming**. Minor polish noted: kill-rate shown with a "+" prefix.

### Self-improvement flywheel + operator surfaces (BUILT, live on Supabase)
- **Graveyard RAG memory** (`knowledge/memory.py`): deterministic keyless offline embedding (FNV-1a feature-hashing → 1536-d, L2-normalized; pgvector cosine on Supabase, pure-Python cosine on sqlite). `remember(spec, outcome)` records every death (with kill_reason) + win (winning structure); `recall(thesis, k)` surfaces prior dead-ends + winners. Indexes STRUCTURE only (never fitted thresholds); point-in-time (`as_of` hides future notes).
- **Authoring consults memory** (`lab/author`/`research`): drops features in recalled dead-ends, leans toward winner patterns + high-grade skills, falls back to neutral rather than re-walking a dead structure. LLM still only proposes.
- **Curator + skills** (`lab/curator.py`): `distill_skill(survivor)` → a reusable parameterized recipe in the `skills` table (idempotent, reinforces success_count); `grade_skills()` grades by downstream OOS pass-rate of derived Versions and prunes low-grade. Distill requires gate-pass.
- **Surfaces** (web): a `/costs` ROI view (opex vs alpha, per-strategy attribution), an **Activity timeline** (the events ledger as a readable "what the machine did" feed) on `/lab`, a **"What the machine has learned"** section (distilled skills + dead-end/winner insights), and a deeper **Strategy detail** (spec + code + blotter + OOS/holdout + post-mortem). New types reconciled to generated `contracts-ts` (no drift).
- **Live-populated + verified (2026-06-01):** added `embedding` columns + HNSW indexes to Supabase (additive ALTER); ran a research pass through the flywheel → **4 graded skills distilled, 10 memory insights** (dead-ends: OSINT proxy / buy-fear / funding-carry; winners: volatility-breakout / trend-momentum-ADX). `/skills` `/memory/insights` `/costs` all 200 on Supabase; `/lab` renders the flywheel + 16 data sources + the trained validation ranking with real data, zero console errors, no demo. **226 engine tests + web build green.**

### Real LLM author + autonomous master tick + command-center flow (BUILT, live on Supabase)
- **Real LLM author** (`lab/llm.py` + `lab/router.py`): the tier router now actually calls **OpenRouter** (stdlib urllib, key from settings) for a **schema-validated** `LlmProposal` (Pydantic `extra="forbid"` → any magic number rejected; retries). The model proposes **structure only** (base_template + named registry features + horizon); the deterministic spec builder fills `param_space` — so **no magic number can reach a spec regardless of model output**. Key-optional: no key → unchanged deterministic template; HTTP is mockable → CI fully offline. The Gate still disposes.
- **Autonomous master tick** (`master/scheduler.py` `run_tick`): one bounded, idempotent, audited cycle — ingest free data → author N (LLM if key, consulting memory + skills) → deterministic FarmLoop gate + flywheel → open a standalone SIM track per survivor → emit human recommendations. Cron-able (one tick/call, no daemon), **sim-only** (never arms live), pause = true no-op.
- **Human-overview API**: `GET /autonomy/status` (running/paused/live/cycles/last+next action/last_summary), `POST /autonomy/{pause,resume,tick}`, `POST /recommendations/{id}/{approve,dismiss}` (approve applies non-money-adjacent actions via audited policy; money-adjacent stays gated).
- **Command-center Overview** (web): three questions top-to-bottom — *are we making money* (headline net %, PAPER/LIVE), *what needs me* (Approve/Dismiss inbox + the gated 2-click Go-Live), *what's the machine doing* ("Running · last did … · next … · Pause / Run a cycle now"), + a live activity stream.
- **Verified live (2026-06-01):** a real `POST /autonomy/tick` against Supabase → **authored 6, 8 cleared the gate, funded 3 SIM tracks, 10 recommendations**; the recs correctly flag the 0-return sources (putcall/liquidations/risk_on/macro_regime — i.e. what needs the operator's FRED key + Polymarket token). **243 engine tests + web build green**, zero console errors. Follow-up: web `autonomy-contracts.ts` still local (the one un-reconciled contract; generated equivalents exist).

### UX: mobile dock + lifecycle clarity (BUILT) + independent critique (2026-06-01)
- Mobile dock rebuilt to best practice: **5 tabs** (Overview · Lab · Strategies · Paper · More-sheet); Live surfaces in the dock only when armed; 56px targets, safe-area, reduced-motion. `/strategies` segments Versions by lifecycle stage (Discovering · Validating · Paper · Live · Graveyard) with counts + filters + explainers, ranked by deflated Sharpe, + a Lab→Strategies→Paper→Live funnel + "how a strategy is born" (autonomous Lab AND Claude-Code inbox → one Gate). Web typecheck + build green (15 routes).
- **Independent best-practices critique (sourced research).** Validated as genuinely best-in-class: the scorer-out-of-reach partition (rare), DSR + CPCV + cumulative trial ledger, one-shot holdout + multi-regime folds. **Ranked next steps (Pareto):** (1) **prove the edge on REAL data or document a FAIL** — the cross-asset gate only PASSES on synthetic; the build has run ahead of the team's own gate-first rule (needs FRED key + real Polymarket token + OpenRouter key — operator). (2) Wire ONE real engine tier (vectorbt screen → Nautilus validate) before trusting any %. (3) **Authoring-time novelty/complexity control** (AlphaAgent: AST/feature-distance penalty) — diversity is enforced only at allocation today → monoculture risk. (4) **Alpha-decay as a first-class primitive** — edge half-life + live-vs-backtest drift monitor that auto-defunds BEFORE P&L turns (~~currently only reactive defund~~ **BUILT ✓, see below**). (5) Polymarket *execution* **BUILT ✓** — CLOB live on Polygon/USDC via py-clob-client EIP-712 signing, behind the same 5 interlocks (toggle/keys/mode/caps/gate), testnet-default, mainnet-only-on-real-mode, limit-only orders priced 0–1, `reconcile_fills` out-of-band; venue-agnostic ignition (`adapters/exec/registry.py`). Remaining last-mile for AUTONOMOUS prediction trading: per-market odds ingest + a PricingRouter prediction leg + a gate-passed prediction strategy. (6) Guard the memory/curator loop against luck-laundering (only holdout-survivors bias authoring; decay old winners). Genuine gaps remaining: **authoring-novelty** (the drift monitor is now built).

### Alpha-decay primitive — edge half-life + anticipatory drift defund (BUILT, gap #4 closed)
*Closes the higher-priority of the two flagged genuine gaps. Deterministic, offline, OUT of any LLM path (it lives in `master/`).*
- **`master/drift.py`** — the missing primitive. Pure analytics: `fit_edge_decay` (OLS on a rolling-mean edge trajectory → **edge half-life** + periods-to-zero; flat/rising ⇒ no finite half-life), `drift_score` (standardized shortfall `z` + a **one-sided lower CUSUM change-point** detector that accumulates only while realized stays below the funded reference and resets on recovery — flags a *sustained* downward shift fast), and `assess_drift` combining them into a `DriftVerdict(defund, reason, …)`. **Anticipatory:** defunds while the realized edge is still *positive* but decaying / materially below what the track was funded on — before cumulative P&L turns. Reference = the track's funded baseline by default (honest about units), or an explicit per-period backtest edge when one in matching units is supplied. Thresholds are policy constants (like rotation's `min_dsr`), not strategy params — the no-magic-numbers rule is untouched.
- **Real per-track series, no schema change**: `master/portfolio.py` `mark_to_market` now also writes a per-track marked-value snapshot (`scope='track', ref_id=version_id`, reusing existing columns) so the monitor has a genuine per-track trajectory; the aggregate reads (`equity`/`drawdown`/`daily_loss`/high-water + `/overview` curve) were scoped to `scope='aggregate'` so track rows never leak in. Store readers `aggregate_return_series`/`track_return_series`/`funded_track_ids` derive returns from the snapshot equity series.
- **Auto-defund wiring**: `portfolio/rotation.py` `is_decayed` is now anticipatory (`Track` gained `drift_defund` + `edge_half_life`; trips on either, backward-compatible defaults). `orchestrator/loop.py` runs `monitor_drift` over funded tracks *before* `select_tracks`, so a decaying/drifting track is defunded (capital pulled, its track closed) and the decision is audited (`drift_assessed` + `track_defunded` events). On first funding there's no history ⇒ no defund (insufficient history); the signal accrues across cron ticks.
- **API**: `GET /research/drift` (read-only, deterministic, no events) → `DriftResponse` per funded track; Pydantic → OpenAPI → regenerated `@cosmu/contracts-ts` (no hand-typing). Web consumption deferred (gate-first + lean-UI; funded history only exists once SIM/live runs).
- **Verified:** 13 new `tests/test_drift.py` cases (analytics, store readers, audited monitor, rotation + portfolio wiring, endpoint) + the touched suites (order-path/portfolio, close-loop, orchestrator, execute-stage, autonomy, live-api, research-brain, flywheel-api, gate-hardening, spine, finder) all green; contracts-ts build + web typecheck green.

### Cost + deploy hardening (config/ops, 2026-06-02)
- **OpenRouter free-tier by default:** `lab/router.py` `TIER_MODELS` now points all three tiers at OpenRouter `:free` models (Llama-3.3-70B / DeepSeek-V3 / DeepSeek-R1) → $0 spend on the 24/7 loop. A stale `:free` id 404s → graceful degrade to the deterministic template author (no crash/spend). Owner's ≥$10 top-up unlocks 1000 free req/day + 20/min; the daily USD cap + the OpenRouter key spend limit bound any future paid tier. Offline `test_llm_author` stays green (mock seam; no live calls).
- **Engine deploy-readiness (now actually deployable):** `pyproject.toml` gained a `[build-system]` (setuptools) + `[tool.setuptools.packages.find]` so `pip install .` packages the `cosmu` engine (verified: 22 subpackages, tests excluded) — nixpacks can build it. `api/app.py` `__main__` binds `0.0.0.0` on `$PORT` (reload only when `APP_ENV` dev/local). **`apps/engine/{Procfile,railway.toml}`** carry the uvicorn start + `/health` + the 15-min `research.loop --ingest` cron (and the other 6 crons), so a Railway service with **Root Directory = `apps/engine`** runs the engine with no manual command. **Topology corrected:** Railway = ENGINE (the existing service was running the web — switch its Root Directory); Vercel = web. **Env var fix:** the web reads `API_BASE_URL` (server, app/data.ts) + `NEXT_PUBLIC_API_BASE_URL` (client panels) — both point at the engine URL; the old `ENGINE_API_URL`/`NEXT_PUBLIC_ENGINE_API_URL` were UNUSED and removed from the env templates. Engine needs `CORS_EXTRA_ORIGINS` = the Vercel domain for client calls. Testnet de-emphasized: SIM marks on REAL prices, so no Binance keys → adapter `disabled` → sim-fills is the realistic harness. Remaining (task DEPLOY): verify the Railway build + /health end-to-end; optionally delete the legacy repo-root `railway.toml` web build.
- **Owner handoff:** `docs/OWNER_SETUP.md` is the single owner-facing doc (keys, deploy/start commands per platform, cost, naming directive, and the current new-chat prompt + STANDARDS). FRED + OpenRouter keys set; Polymarket optional (task 1b auto-discovers markets).

## Decisions

- **Hosting = Railway, DB = Supabase (Postgres + pgvector).** Railway over Render (Render's free tier sleeps — unfit for a 24/7 data worker; multi-service always-on is cheaper on Railway's usage billing). Hetzner is the Tier-2/3 cost option. Supabase gives managed Postgres + pgvector for the central indexed store / graveyard RAG.
- **Free data first ($0).** The first real gate runs on funding/OI + Fear&Greed + free news; LunarCrush/social is optional and only added if the free aggregation gate shows legs. A $0 real gate beats a paid one.
- **Pine import = paste / file upload / bulk, not TV link.** TradingView doesn't expose script source over a public URL (closed-source scripts; scraping violates ToS). Paste + `.pine`/`.txt` upload + the sample library is the robust path. A CSV/bulk-paste of `{name, source}` is the multi-import seam.
- **LLM-optional by default.** Authoring + generation run deterministically without any model key, so the machine is fully functional offline; the model router is an enhancement at a single seam, never a hard dependency. Keeps the scorer/money partition intact regardless.
- **Cohort screen is a deterministic surrogate** standing in for the vectorbt/Nautilus two-tier backtest (those are BUY/BORROW vendors). The architecture (cheap screen → full validate) mirrors the plan so wiring the real vendors is a swap, not a rewrite. The scorer/gates are already the real, authoritative deterministic layer.
- **External coding agents (Claude Code / Cursor) author by writing typed specs**, not by a bespoke bridge: a spec is JSON validated by `static_check` + `instructor`/Pydantic. The in-product path is the Console; both funnel into the same farm under the same guardrails.

## Not yet wired (vendor swaps, same seams)
NautilusTrader event-driven validation · vectorbt fast screen · Optuna param fitting · OpenRouter model router + `instructor` · Databento/equity data ingestion · Supabase Postgres/pgvector in prod.

---

# Product architecture (decided 2026-06-01)

This is the canonical product shape. It refines `docs/archive/BUILD_PLAN.md §10/§15` (historical) — when they disagree, this wins until promoted into the contract.

## Three engines (the funnel)

Each stage answers a different question. A strategy must clear each to reach the next.

| Engine | Capital | Question it answers | Notes |
|---|---|---|---|
| **Lab** | None — fixed notional per strategy, scored as **net-of-fee %** | "Does this edge exist on its own?" | Cheap, wide, no portfolio effects. Must still charge real per-venue fees or the % is fake. This is the evolution loop. |
| **Simulation** | Its **own** standalone SIM track (default $1,000, `sim_track_capital`; no pooled wallet) | "Does this edge hold up on real prices, net of costs, over time?" | Each survivor proves itself on its own track — no shared capital, no cross-strategy competition. Held + marked-to-market across bars. Runs 24/7. |
| **Live** | Real money, small caps | "Does the SIM edge survive real fills / latency / slippage?" | Same strategy code path, launched manually with dedicated capital. Auto-defund on edge decay. Starts at smallest caps, top survivors only. |

**Live activation = 2 clicks.** (1) "Go live" opens a modal showing exactly what will trade: strategies, per-strategy cap, global cap, max daily loss. (2) "Confirm" arms it. Auto-disarms if the daily-loss cap is hit. The modal is the second factor.

## Surfaces & navigation (unique pages, never anchors)

Every sidebar item is its own route. No `/#section` jumps to a shared page.

Canonical source of truth: `apps/web/components/nav/app-nav.tsx`. Nine primary surfaces + three under "More" (as of 2026-06-07).

| Route | Purpose |
|---|---|
| `/` Overview | Are we making money, what's running, what needs me. Aggregate read-out (Σ of standalone tracks — NOT a pooled wallet), KPI row, equity chart, "needs you" list, recent activity. |
| `/console` | Decide · steer · arm (the control surface). |
| `/lab` | Idea → spec → verdict: auto-running cohorts, funnel, survivors, graveyard, Pine inbox. |
| `/strategies` | Backtest · ranked & faceted: search/browse any version, detail (`/strategies/{id}`), lineage, why it died. |
| `/paper` Simulation | Live data, no money — per-strategy SIM tracks, forward-return vs backtest. |
| `/verdicts` Theories | Every theory tested + its honest Gate verdict (served by `GET /research/experiments`). |
| `/explorer` | Pick · chart · compare data sources / strategies. |
| `/mind` | What the agent knows, thinks, and has learned (the 24/7 committee). |
| `/costs` | What is it costing? Infra/LLM/data opex vs alpha. |
| `/live` (More, gated) | Activation modal, caps, real positions, defund controls. Dimmed until armed. |
| `/settings` (More) | Keys, universe, data sources, model on/off — written through the app (audited), never raw SQL. |
| `/commands` (More) | Run procedures from Claude Code. |

There is **no `/paper` "wallet" route** — the Overview is a read-out, not a pooled wallet. Costs is its own
surface (`/costs`), not folded into a wallet page.

## Sidebar component (shadcn)

Use shadcn `Sidebar` with `collapsible="icon"`: a thin icon rail by default, expands to labels on click and on hover, tooltips on the icons when collapsed, collapsed/expanded state persisted (cookie/localStorage). Behaviour like Supabase / Chrome side tabs. Icons always visible and clickable.

## Language & UX rules

- **Plain language, no analogies or metaphors.** Literal labels: "Net return after fees", "Strategies on paper", "Why it was rejected" — not "money valve", "decorrelated handful", "refuses to fool itself".
- **Explanations go in hover tooltips** (small "i" icon), so beginners get help without the UI shouting jargon.
- **Mobile-first.** Sidebar becomes a bottom bar or drawer on small screens; single-column cards; charts shrink gracefully; large tap targets.
- **Progressive disclosure.** Summary by default, detail on hover/expand. One primary action per screen.
- **Charts: buy a library** (Tremor for dashboard KPI+charts, Recharts/visx for custom curves). Real tooltips with numbers, selectable time ranges, drawdown shading, equity-vs-benchmark, per-strategy curves. Replace the hand-rolled SVG.

## Pine inbox (GitOps import)

A repo folder `strategies/inbox/*.txt|*.md` is scanned on boot/deploy. Each new file → `translate_pine` → enters the Lab. `.md` may carry a note block (intent, source URL) above a Pine code fence; filename or a front-matter line becomes the name. The paste/upload UI stays for ad-hoc imports; the folder is for "drop 20 scripts, push, done."

## Compute & cost (decided: pay API + serverless bursts, no self-host)

The core feature is the LLM using ML tools to test strategies fast — but the heavy work is **cheap CPU**, not GPU:
- **Backtests** (vectorbt, Numba/CPU) screen thousands per second. No GPU.
- **ML survival model + regime classifier** (XGBoost/LightGBM, small tabular) train in seconds on CPU. No GPU.
- **LLM** is the orchestrator/author → **OpenRouter API**, cheap tier for breadth, frontier only for novel hypotheses. The token spend is the real cost lever and is **capped by the spend governor**.
- **GPU** only for rare agent-written deep models → **Modal pay-per-use bursts**, sandboxed. No GPU box.

**Do not self-host LLMs or GPUs.** It saves nothing until inference spend is steadily in the hundreds/month. Estimated run cost to start serious: **~$50–150/month, fully capped** (hosting ~$25, LLM ~$30–100 capped, equities data ~$30–50 later, Modal ~$0–50; crypto data free via ccxt).

## Agentic-first stack (lean)

- **Truth = structured Postgres rows.** Markdown + an INDEX are cheap views. Read the INDEX, then one record (token-frugal).
- **RAG = pgvector** in the same Postgres (Supabase). Embeddings via API. Index research notes, feature docs, and the **graveyard** (what didn't work = long-term memory).
- **Tools = a read/research/propose-only bus** (`lab/tools/`). Web search (Exa/Tavily), news, RAG read. **Execution is never on the bus.**
- **ML = libraries the agent uses as tools**, results judged by the deterministic scorer. ML never defines success or moves money.
- **LLM-optional everywhere.** The machine runs fully without a model key; the router is an enhancement at one seam.

## Operator role (what the human does)

- **Settings page** for keys, caps, spend limits, model on/off — written through the app so every change logs an event. **No routine raw SQL** (it breaks the audit ledger; reserve for migrations/emergencies). A read-only DB view is fine for visibility.
- **Steer in chat**: author/suggest strategies, review survivors, flip Live.
- **Deploy = `git push`** → Railway/Vercel auto-deploy. Pine files ride the same push via `strategies/inbox/`.

## Priority order (next)

**Gate-first (decided 2026-06-01): prove the differentiator on free data before building any more product.** Phase 1.5 (single-asset aggregation ablation) and **Phase 1.6 (cross-asset extension) are both built and green on the fixture** — the four-arm gate **PASSES** on the seeded synthetic, with the cross-asset transfer features as the genuine payers. Product/UI work stays **deferred until the gate passes on REAL free data** (don't gold-plate a surface for an unproven edge).

1. **Phase 1.6 — the cross-asset extension (BUILT ✓, see above).** Next: **run the four-arm gate on real free multi-asset data** (live Stooq daily bars + FRED macro + Polymarket odds through the same providers) — the fixture PASS proves the harness; a real PASS proves the thesis. Only on a real PASS does anything below get built.
2. *(after real PASS)* **Split into the three engines + the six real routes**, collapsible icon sidebar, 2-click Live modal.
3. *(after PASS)* **Pine inbox folder.**
4. *(after PASS)* **Dashboard redesign**: real charts (Tremor/Recharts), plain language, mobile pass.
5. *(after PASS)* **Settings page** for the operator knobs.
6. *(after PASS)* agentic research tools + ML survival model + pgvector RAG.
