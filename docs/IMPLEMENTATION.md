# Cosmu v2 — Implementation Log

> Tracks what is actually built and the decisions taken, so `VISION.md` (contract) and `BUILD_PLAN.md` (how) stay honest. When code and the big docs diverge, reconcile here on purpose.

## Built

### Spine & control plane
- `spine/engine.py` — deterministic facade (`run_backtest`/`run_sandbox`/`run_live`), `VenueCatalog`, fill-log, seeded determinism. Live blocked unless the global toggle is on.
- `knowledge/store.py` — SQLite/Postgres-ready store. **Batched writes:** `Store.batch()` yields one connection + one transaction for a whole cohort (400 candidates persist in ~0.15s vs thousands of connections before). WAL + `synchronous=NORMAL`.
- `master/scorer.py` + `master/risk.py` — deterministic scorer (deflated Sharpe, PBO, gates) and risk gauntlet. **Out of the agent's reach.**

### Autonomous evolution loop (`evolution/`) — the differentiator
- `loop.py` `FarmLoop.run_cohort(...)` — generates a wide population (seeds + chat briefs + Pine imports → exploit mutations + explore wildcards), compiles + static-checks each, runs a cheap deterministic real-bar Binance spot screen, scores through the out-of-reach scorer, keeps gate-passers as `$100k` paper sleeves, sends the rest to the graveyard **with kill reasons**. Seeded/reproducible for a fixed bar cache/provider.
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
- **Promotion/portfolio/execution/orchestration scaffolding** (Phase-2-facing, built + green): `master/cohort.py` (cohort promotion gate — register every candidate as a trial, promote only on per-candidate significance AND Benjamini-Hochberg FDR across the cohort, rank by net-of-cost profit), `master/fdr.py` (BH-FDR), `master/cv.py` (purged+embargoed CPCV), `portfolio/rotation.py` (capped-Kelly, decayed-sleeve defunding), `execution/costopt.py` (maker/taker net-of-cost choice + fee tiers), `orchestrator/{agent,efficiency}.py` (a pluggable stage pipeline inside a live/kill/pause safety envelope + capability-per-dollar meter). All deterministic, out of any LLM path.

### Functional next version — free sources, env profiles, UI restructure (BUILT)
*Owner decision (2026-06-01): make the app functional + usable now and add several free data sources, rather than keeping all UI/data work deferred to a real-data gate PASS. The gate-first discipline still holds for paid vendors, live execution, and the Phase-2 factory.*
- **Six free data providers** behind the existing seams: `KrakenSpotOHLCVProvider`, `BybitSpotOHLCVProvider`, `YahooDailyBarsProvider` (`survivorship_complete=False`, declared) in `data/market.py`; `CoinglassLiquidationProvider` (metric `liquidations`), `CboePutCallProvider` (market-wide `putcall_ratio`), `GdeltNewsProvider` (real headlines → existing LLM-standardize path) in `data/altdata.py`. All stdlib-HTTP + certifi SSL, disk-cached, separable parse fns, point-in-time `available_at`, offline-tested via canned payloads.
- **Feature**: `liquidation_cascade` (tier0 crypto, prior + pinned transform); `putcall_ratio` given a transform_version for consistency.
- **Ingest**: `ingest_extra_free_sources` (Coinglass + CBOE + GDELT news) added to `ingest/pipeline.py`, append-only/idempotent-in-view, offline-safe.
- **Env profiles**: `APP_ENV` (dev|test|qa|production) selects the env file — dev→`.env.local`, test→`.env.test.local`, qa→`.env.qa.local`, production→process env only. Committed `.env.test.local` (sqlite, no keys) + `.env.qa.local` (supabase placeholder) templates; `.env.example` documents it. The free cross-asset gate needs **zero** keys.
- **API**: `POST /research/cross-asset-gate` runs `evaluate_cross_asset_ablation` — `StoreBackedAltProvider` (`data_source="live"`) when the store has the ingested transfer series, else synthetic fallback; persists `gate_verdicts` + emits a `cross_asset_gate_run` event. Pydantic `CrossAssetVerdict` → OpenAPI → regenerated `contracts-ts` (the web consumes the generated type, not a hand-typed one).
- **Self-sustained loop (Karpathy "arrange once, hit go", cron-able — NOT a daemon):** `cosmu/ingest/run.py` `run_once()` — one append-only point-in-time pass over the free sources into the store (backend auto-picked by `database_url` like the API; per-source failure logged as a 0 count, never aborts); `python3 -m cosmu.ingest.run`. `cosmu/research/loop.py` `auto_research_pass()` — ingest → run `evaluate_cross_asset_ablation` (live store-backed when `risk_on`+`macro_regime` present, else synthetic) → persist `gate_verdicts` + emit event → return verdict; `python3 -m cosmu.research.loop --passes N [--ingest]`, bounded, deterministic, zero LLM in the gate path. **Live smoke (real APIs, zero keys):** funding (400 pts) + Fear&Greed (1000 pts) flowed; FRED/Polymarket/Coinglass/CBOE/GDELT degraded gracefully (need a free FRED key, a real Polymarket token id, or hit rate-limits) → those report 0 and the loop falls back to the synthetic gate. To run the gate on real cross-asset data: deploy as a Railway cron against Postgres + supply a FRED key + the real Polymarket market token.
- **Web — Overview-led, 4 routes** (`apps/web`): Overview (`/`, lean summary: headline net %, KPI row, one equity chart, "needs you", recent activity, compact gate status), Research (`/research`, merges Farm + a searchable Strategies table + the Edge gate + the new Cross-asset gate "Run" button + graveyard; `/farm` redirects here), Console (`/console`, its own page now — chat author + recommendations + audit stream), Settings (`/settings`). **Clutter removed**: "v2" subtitle dropped from the wordmark; strategy-detail back-arrow + competing header badge removed (single title block). Offline-demo fallback preserved. `pnpm --filter @cosmu/web typecheck` + `build` green.

### Trade-capable V1 — execution + live path (BUILT, dormant & safe)
*Owner decision (2026-06-01): build a complete, holistic V1 that is **ready to trade once keys are set** — capability, not proven edge. Live stays OFF; real money still requires the cross-asset gate to PASS on real data + explicit arming.*
- **Execution adapter** (`adapters/exec/binance.py`): `BinanceSpotExecutionAdapter` (ccxt) — submit/cancel/positions/fills, **idempotent on `client_order_id`**. `resolve_mode()` is the real-money interlock: TESTNET keys → testnet (default, fake money); real Binance ONLY with `BINANCE_API_KEY/SECRET` **and** `live.mode=="real"`; no keys → disabled/paper, no network. Secrets never stored/logged/returned. Pure parse layer unit-tested against a mock ccxt client.
- **Single order path** (`master/execution.py`): every intent clears `master/risk.py` `validate_order_full` (SL/TP required, per-strategy + global caps, min cash reserve, lot/min-notional, drawdown kill-switch, daily-loss auto-disarm, **martingale/averaging-down banned**, memoryless sizing) → submits live only when toggle ON + adapter active + gate-passed + caps free + not killed, else deterministic paper-fill. Persists `executions` + events + `positions`. Wired as the orchestrator's `execute_stage` (replaced the "plans not sent" stub).
- **Paper portfolio** (`master/portfolio.py`): holds positions (new `positions` table), marks-to-market, writes `portfolio_snapshots`, net-of-cost P&L + drawdown, daily-loss tracker. `GET /portfolio` now reflects real state (no fabricated numbers).
- **Live API**: `POST /toggle/live` hardened (requires `confirm`), `POST /live/activate` (confirm-gated, caps + eligible), `POST /live/defund`, `GET /live/positions` — all audited; Pydantic → regenerated `contracts-ts`.
- **Web `/live`** (gated, 5th route, dimmed until armed): 2-click activation modal (shows exactly what will trade + caps + a quiet gate note), real positions table, defund controls, daily-loss-vs-cap, mode badge. The web never decides whether an order is real — it surfaces the engine's verdict. Honest empty states replace the old fabricated equity/allocation fallback (demo only when the engine is unreachable).
- **Ops**: `railway.toml` keeps the API as the only persistent process + a bounded 6h `[[cron]]` running `research.loop --ingest`. The new `positions` table was applied to the **live Supabase** (additive). **Verified:** 162 engine tests pass · web typecheck + `next build` green (all routes incl. `/live`) · live live-types reconciled to the generated contract.

### Research brain — autonomous strategy authoring + pluggable sources (BUILT)
*Phase 3 (LLM factory), built gate-respecting: LLM **proposes**, the deterministic scorer **disposes**. Fully offline/LLM-optional.*
- **Pluggable data-source registry** (`data/sources/registry.py` — pre-existing seam, now populated): a typed `DataSource` protocol + registry so any agent discovers/queries a source by name; wraps the existing providers (thin adapter, no rewrite). The seam to upgrade data sources later.
- **OSINT example** (`data/sources/osint_adsb.py`): `AdsbDataSource` over the free OpenSky API → aircraft-activity as a point-in-time, availability-stamped, **low-confidence** numeric feature (declared prior, `transform_version`, offline fixture, degrades to fixture on network failure). Registered as `osint_air_activity` in the feature vocabulary — must earn its place via OOS like any source.
- **Propose-only research tool bus** (`lab/tools/research_tools.py` on the existing `ToolBus`): `web_search` (Tavily-opt), `news_read` (GDELT-opt), `social` (LunarCrush-opt), `pine_fetch`, `rag_read` — all read-only, LLM-optional with offline fixtures, keys bound server-side. **Execution is never on the bus** (the bus rejects non-readonly/execute/order-named tools).
- **Autonomous research pass** (`lab/research.py`): gather context off the bus → author N specs (`lab/author`, LLM-optional, referencing named features incl. OSINT) → compile + static-check → run the deterministic evolution screen + out-of-reach scorer → record survivors + graveyard with reasons. CLI `python3 -m cosmu.lab.research [--n N]`, bounded + reproducible. A poisoned router proves no LLM is reachable from the scoring path.

### Money clarity + mobile/desktop polish (BUILT)
- Every $/% now carries an explicit **PAPER (simulated) / DEMO (engine offline) / LIVE (armed)** badge + tooltip — resolves "what is this money?": paper = simulated on live-shadow prices, no real funds; live = real, off until armed. Sleeve-% (per strategy) vs pooled-wallet made unambiguous via a shared tooltip; a "Working strategies" section ranks funded sleeves by net-of-fee %.
- Lean Overview answers at a glance: are we making money (headline net % + state label) · which strategies work · what the bot did · total profit — honest empty states, no fabricated numbers.
- Mobile + desktop pass: sticky-first-column scroll-x tables (no page overflow), single-column mobile cards, fluid headline, shrinking charts, smoother transitions, reduced-motion respected. `typecheck` + `next build` green (10 routes).

## Infra (settled) & next phase
- **Where it runs:** **Railway** = the always-on machine (engine API + farm/paper worker + bounded crons, e.g. `research.loop --ingest` 6h) · **Supabase** = Postgres + pgvector (truth) · **Vercel** = web · **Claude Code / local `.md`** (AGENTS.md, `# intent:` headers, skills) = how the coding agent builds/maintains it (non-24/7) · **Modal/E2B** = untrusted agent-written ML, later. Not either/or — the money-machine is hosted; the build/maintain loop is agentic.
- **ML-by-LLM (BUILT):** `ml/survival.py` — tabular survival model (XGBoost/LightGBM if importable, else a pure-Python logistic fallback so CI is dependency-free) trained on labeled store outcomes once ≥30 exist (chronological 75/25 OOS split + AUROC), **orders the validation queue, never vetoes** (rank = permutation only), cold-start = cheap heuristic until trained. `ml/regime.py` — deterministic vol-tercile × trend regime classifier + `regime_eligible` live-gate (a strategy goes live only in a proven regime; empty passport fails safe). Wired: `evolution/loop.py` orders gate-survivors by survival score + records the score + proven-regime passport on `sleeve_opened`; `master/live_eligibility.py` gates the live-eligible set. `GET /research/brain` surfaces it; web `/research` renders the brain (funnel, survivors+score, graveyard reasons, regime, sources incl. OSINT, validation ranking with trained/cold-start). **194 engine tests green.**
- **Next:** **pgvector graveyard RAG** (long-term memory so the brain stops re-walking dead ends — Phase 3 memory) · **live-polish** (true mark-to-market in `/live/positions` + `adapter.fills()` reconciliation + persist toggle state to the orchestrator envelope). Agent-written ML in Modal/E2B (no secrets/venue), artifacts judged by the same out-of-reach scorer, stays gate-gated.

### Great V1 — Strategy Finder + closed loop + user-oriented IA, audited on REAL data (BUILT)
- **Strategy Finder** (`lab/finder.py`): grid-search a spec's param space → screen on real bars → rank by **profit factor + the Gate** → WFO/holdout before promotion → persist winners to the config library (`origin='finder'` Versions + Sleeves). Composable, fittable spec modules: `multi_tp`, `break_even`+runner, `ma_trend_filter`, `orb` (upside-only), `fvg_retest`/`fvg_multiple`; **ORB+FVG-multiple** is the seed (`seed_orb_fvg_spec`). `python3 -m cosmu.lab.finder --seed-real` bootstraps real strategies.
- **Closed loop** (`orchestrator/loop.py` `fund_wallet_from_survivors`): gate-passed survivors → capped-Kelly allocator funds the pooled **Wallet** → `master/portfolio` opens real paper positions + marks-to-market. Fixed a boundary bug: qty now rounds **down** so notional can't round a hair over the per-strategy cap (was rejecting every fill).
- **ML-by-NL** (`POST /lab/ml` + Steer page): plain-language asks ("rank survivors by edge-persistence", "retrain") → the survival model (orders, never vetoes). On real data the model **trained** (xgboost, 40 labels).
- **User-oriented IA**: Overview · Lab · Strategies · Paper · Live · Steer · Settings — one job per route; `research/farm/console` are redirect shims. **No "farming" jargon**, **no demo data** (honest connect/empty states; demo removed). `create-strategy` skill + `strategies/inbox` + `docs/GLOSSARY.md` standardize authoring.
- **Audited live on Supabase (2026-06-01):** `seed_real` persisted 24 finder Versions (4 Sleeves, 4 gate-passers); the Wallet funded 3 capped-Kelly positions; the web (engine on Supabase) renders 20 real ranked Versions, the funded Wallet, the trained survival ranking, and a real audit stream — **214 engine tests pass · web typecheck+build green · zero console errors · no demo · no farming**. Minor polish noted: kill-rate shown with a "+" prefix.

### Self-improvement flywheel + operator surfaces (BUILT, live on Supabase)
- **Graveyard RAG memory** (`knowledge/memory.py`): deterministic keyless offline embedding (FNV-1a feature-hashing → 1536-d, L2-normalized; pgvector cosine on Supabase, pure-Python cosine on sqlite). `remember(spec, outcome)` records every death (with kill_reason) + win (winning structure); `recall(thesis, k)` surfaces prior dead-ends + winners. Indexes STRUCTURE only (never fitted thresholds); point-in-time (`as_of` hides future notes).
- **Authoring consults memory** (`lab/author`/`research`): drops features in recalled dead-ends, leans toward winner patterns + high-grade skills, falls back to neutral rather than re-walking a dead structure. LLM still only proposes.
- **Curator + skills** (`lab/curator.py`): `distill_skill(survivor)` → a reusable parameterized recipe in the `skills` table (idempotent, reinforces success_count); `grade_skills()` grades by downstream OOS pass-rate of derived Versions and prunes low-grade. Distill requires gate-pass.
- **Surfaces** (web): a `/costs` ROI view (opex vs alpha, per-strategy attribution), an **Activity timeline** (the events ledger as a readable "what the machine did" feed) on `/lab`, a **"What the machine has learned"** section (distilled skills + dead-end/winner insights), and a deeper **Strategy detail** (spec + code + blotter + OOS/holdout + post-mortem). New types reconciled to generated `contracts-ts` (no drift).
- **Live-populated + verified (2026-06-01):** added `embedding` columns + HNSW indexes to Supabase (additive ALTER); ran a research pass through the flywheel → **4 graded skills distilled, 10 memory insights** (dead-ends: OSINT proxy / buy-fear / funding-carry; winners: volatility-breakout / trend-momentum-ADX). `/skills` `/memory/insights` `/costs` all 200 on Supabase; `/lab` renders the flywheel + 16 data sources + the trained validation ranking with real data, zero console errors, no demo. **226 engine tests + web build green.**

### Real LLM author + autonomous master tick + command-center flow (BUILT, live on Supabase)
- **Real LLM author** (`lab/llm.py` + `lab/router.py`): the tier router now actually calls **OpenRouter** (stdlib urllib, key from settings) for a **schema-validated** `LlmProposal` (Pydantic `extra="forbid"` → any magic number rejected; retries). The model proposes **structure only** (base_template + named registry features + horizon); the deterministic spec builder fills `param_space` — so **no magic number can reach a spec regardless of model output**. Key-optional: no key → unchanged deterministic template; HTTP is mockable → CI fully offline. The Gate still disposes.
- **Autonomous master tick** (`master/scheduler.py` `run_tick`): one bounded, idempotent, audited cycle — ingest free data → author N (LLM if key, consulting memory + skills) → deterministic FarmLoop gate + flywheel → fund the paper Wallet → emit human recommendations. Cron-able (one tick/call, no daemon), **paper-only** (never arms live), pause = true no-op.
- **Human-overview API**: `GET /autonomy/status` (running/paused/live/cycles/last+next action/last_summary), `POST /autonomy/{pause,resume,tick}`, `POST /recommendations/{id}/{approve,dismiss}` (approve applies non-money-adjacent actions via audited policy; money-adjacent stays gated).
- **Command-center Overview** (web): three questions top-to-bottom — *are we making money* (headline net %, PAPER/LIVE), *what needs me* (Approve/Dismiss inbox + the gated 2-click Go-Live), *what's the machine doing* ("Running · last did … · next … · Pause / Run a cycle now"), + a live activity stream.
- **Verified live (2026-06-01):** a real `POST /autonomy/tick` against Supabase → **authored 6, 8 cleared the gate, funded 3 paper sleeves, 10 recommendations**; the recs correctly flag the 0-return sources (putcall/liquidations/risk_on/macro_regime — i.e. what needs the operator's FRED key + Polymarket token). **243 engine tests + web build green**, zero console errors. Follow-up: web `autonomy-contracts.ts` still local (the one un-reconciled contract; generated equivalents exist).

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

This is the canonical product shape. It refines `BUILD_PLAN.md §10/§15` — when they disagree, this wins until promoted into the contract.

## Three engines (the funnel)

Each stage answers a different question. A strategy must clear each to reach the next.

| Engine | Wallet | Question it answers | Notes |
|---|---|---|---|
| **Lab** | None — fixed notional per strategy, scored as **net-of-fee %** | "Does this edge exist on its own?" | Cheap, wide, no portfolio effects. Must still charge real per-venue fees or the % is fake. This is the evolution loop. |
| **Paper** | One shared wallet | "Do the survivors make money **together**, at fillable size, after costs?" | Correlation, capacity, shared capital, simultaneous positions appear here. Correlation-aware capped-Kelly allocator. Runs 24/7. |
| **Live** | Real money, small caps | "Does the paper edge survive real fills / latency / slippage?" | Same strategy code path. Auto-defund on edge decay. Starts at smallest caps, top survivors only. |

**Live activation = 2 clicks.** (1) "Go live" opens a modal showing exactly what will trade: strategies, per-strategy cap, global cap, max daily loss. (2) "Confirm" arms it. Auto-disarms if the daily-loss cap is hit. The modal is the second factor.

## Surfaces & navigation (unique pages, never anchors)

Every sidebar item is its own route. No `/#section` jumps to a shared page.

| Route | Purpose |
|---|---|
| `/` Dashboard | Are we making money, what's running, what needs me. One headline number, KPI row, one interactive equity chart, "needs you" list, recent activity. |
| `/lab` | The research farm: auto-running cohorts, funnel, survivors, graveyard, Pine inbox. |
| `/paper` | The wallet: equity curve, open positions, allocations, costs, P&L. |
| `/live` | Gated. Activation modal, caps, real positions, defund controls. Dimmed until armed. |
| `/strategies` | Search/browse any version, detail, lineage, why it died. (Replaces the old "Leaderboard" anchor.) |
| `/settings` | Keys, caps, spend limits, data sources, model on/off — written through the app (audited), never raw SQL. |

The current `/` dashboard sections (leaderboard, strategy spotlight, console) must be split into their real routes.

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
