# COSMU — Codebase Architecture Map

> **Read this to understand the whole app without chatting with an agent or staring at the UI.**
> Plain-language map of what COSMU is, how a strategy flows from idea to (human-armed) live money,
> and where every subsystem lives in the code. The module-tree section at the bottom is
> **auto-generated from the code** (`python3 -m cosmu.docs.codebase_map`) so it can't silently drift.
>
> Companion docs: vocabulary → [GLOSSARY.md](GLOSSARY.md) · where data lives → [DATA_INDEX.md](DATA_INDEX.md) ·
> how to author a strategy → [AUTHORING.md](AUTHORING.md) · the product surfaces → [PRODUCT.md](PRODUCT.md) ·
> the strategic contract → [VISION.md](VISION.md) · the full doc index → [INDEX.md](INDEX.md).

---

## What COSMU does

COSMU is an **autonomous, honest, fee-net crypto/multi-venue trading machine**. LLMs (and the operator)
**propose** trading strategies; a **deterministic Gate** — not a model, not the UI — decides which ones earn
money. Each survivor proves itself on its **own standalone paper track** on live data (no pooled wallet), and
real money flows only when a human explicitly arms it behind **five hard interlocks**. Everything is judged
**net of every real cost** (fees, slippage, funding), every decision is audited, and empty surfaces say so
honestly rather than fabricating a track record. The one number that matters is realized risk-adjusted profit,
net of all costs. The codebase splits cleanly in two: **`apps/engine`** (Python — the deterministic money
machine, the Gate, the data, the autonomous loop) and **`apps/web`** (Next.js — a read-only/steering cockpit
that never moves money).

---

## The end-to-end pipeline

A strategy is a typed **`StrategySpec`** (a falsifiable hypothesis: "signal X predicts return Y", with
named features, a universe, entry/exit *structure*, and a disconfirmer). It flows left-to-right; it must clear
each stage to reach the next. **Every (strategy × symbol × venue) combination is judged BRUT on its own data**
— no pooling across symbols, no sibling comparison.

```
                  ┌─────────────────────────────────────────────────────────────────────┐
                  │                       apps/engine/cosmu                              │
                  │                                                                       │
  free + paid     │   ingest/  ──►  data/  ──►  strategy/ + lab/  ──►  master/ + research/│
  data sources    │   (point-in-     (bars +     (author a typed       (the deterministic │
  (funding, news, │    time alt-      backtest    StrategySpec from     GATE: scorer +     │
  social, macro,  │    data, LLM-     engine)     a brief / Pine /      cohort FDR +       │
  on-chain, OSINT)│    standardize)               inbox / LLM)          holdout + ablation)│
                  │        │                            │                      │           │
                  │        ▼                            ▼                      ▼           │
                  │   knowledge/ (Store: Postgres/Supabase + R2 lake, the audit ledger,    │
                  │   the trials ledger, pgvector graveyard memory)                        │
                  │                                                                       │
                  │   orchestrator/ + portfolio/  ◄── funds ONLY gate survivors           │
                  │   (paper clock executes each track's own spec on live bars,           │
                  │    marks-to-market; portfolio plane keeps survivors funded /           │
                  │    defunds decayed ones — NO pooled wallet)                           │
                  │                            │                                          │
                  │   adapters/exec/ + master/execution.py  ◄── the MONEY PATH            │
                  │   (one order path; real submit ONLY behind the 5 interlocks)          │
                  └────────────────────────────────┬──────────────────────────────────────┘
                                                   │ same API (OpenAPI → @cosmu/contracts-ts)
                                                   ▼
                                          apps/web  (Next.js cockpit — reports + steers, never funds)
```

**Mapped to the locked lifecycle** (see [GLOSSARY.md](GLOSSARY.md) — **Backtest → Paper → Live**):

| Pipeline stage | Lifecycle status | What happens | Money? |
|---|---|---|---|
| **Data ingest** | — | Point-in-time alt-data + market bars land in the Store (`ingest/`, `data/`). | none |
| **Strategy authoring** | `discovering` | A brief / Pine / inbox file / LLM proposal becomes a typed `StrategySpec` (`strategy/`, `lab/`). No magic numbers — thresholds are a fitted `param_space`. | none |
| **Per-combo backtest** | `validating` | Each (strategy × symbol × venue) combo is backtested BRUT on its own data, real per-venue fees charged (`data/backtest.py`, `lab/finder.py`). | none |
| **The Gate** | `validating` → pass/kill | Deterministic, pre-registered bar: deflated-Sharpe (DSR) ≥ 0.95 · CSCV-PBO < 0.5 · ≥ 30 trades · ≥ 2 regime folds · maxDD < 0.25 · **beat buy-and-hold** · cohort **Benjamini-Hochberg FDR** across the whole cohort (`research/gate.py`, `master/scorer.py`, `master/cohort.py`, `master/fdr.py`, `master/holdout.py`). | none |
| **Paper / forward** | `paper` | Each survivor opens its **own standalone SIM track** (default $1,000) on **live** bars; the daily clock executes the track's own spec (stop/take/signal-exit/re-entry) and marks to market. This is the **scan-immune** forward proof — ≥ 30 net-positive paper-days is the advisory live-readiness signal (`orchestrator/paper_step.py`, `master/paper_maturity.py`). | simulated |
| **Live** | `live` | Real money — **only** when a human arms it and all five interlocks hold. Same code path as paper (`master/execution.py`, `adapters/exec/`). | real |

The honest fact today: the **novel-mined-edge lane has 0 survivors** (every data-mined crypto/factor theory has
been killed by the Gate — that is the machine working, not a bug; see [STRATEGIES.md](STRATEGIES.md)). The
**deploy lane** (externally-documented TAA strategies) has honest survivors. See [START_HERE.md](START_HERE.md).

---

## Subsystem table

Each major package under `apps/engine/cosmu/`, in plain language, with its key entrypoints. (The
auto-generated module tree at the bottom lists every module; this table is the curated "what matters" view.)

| Package | What it does | Key files / entrypoints |
|---|---|---|
| **`core/`** | The asset-agnostic contracts every venue and asset class implements — one shape (`Instrument`/`Bar`/`Feature`/`Signal`/`Order`/`Fill` + `DataAdapter`/`ExecutionAdapter` Protocols) for crypto/equity/fx/prediction. Pure types, point-in-time stamps mandatory. | `core/interfaces.py` |
| **`data/`** | Market-data providers (Binance/Kraken/Bybit spot, Stooq/Yahoo equities, Polymarket odds) + the deterministic long-only **backtest engine** that produces the fee-net metrics the scorer reads. No LLM can change fills/fees/scoring. | `data/market.py`, `data/backtest.py`, `data/altdata.py`, `data/universe_calendar.py` |
| **`ingest/`** | Turns raw/unstructured sources into validated, point-in-time numeric features (the append-only `alt_data` write path). LLM standardization happens **here at ingest only**, content-hash cached, never in any scoring path. | `ingest/pipeline.py`, `ingest/run.py`, `ingest/standardize.py`, `ingest/profile_source.py` |
| **`strategy/`** | The `StrategySpec` schema, the static-check **Creation Contract** (no magic numbers · features from the registry · non-empty rationale), the Pine→spec translator, and the derived taxonomy facets. | `strategy/spec.py`, `strategy/static_check.py`, `strategy/pine.py`, `strategy/taxonomy.py` |
| **`lab/`** | The **authoring + discovery** brain: draft a spec from a plain-language brief, the Strategy **Finder** (grid-search a param space → screen on real bars → rank by Gate), the autonomous research pass, and the read/propose-only research tool bus (execution is never on the bus). | `lab/author.py`, `lab/finder.py`, `lab/research.py`, `lab/curator.py`, `lab/tools/` |
| **`master/`** | **The deterministic master — out of any LLM's reach.** Owns the Gate's scoring/FDR/holdout, the single order path + risk gauntlet, position sizing (backtest=paper=live parity), the portfolio of record, live-eligibility, alpha-decay drift, and the autonomous tick. This is the money/scorer partition. | `master/scorer.py`, `master/cohort.py`, `master/fdr.py`, `master/holdout.py`, `master/execution.py`, `master/risk.py`, `master/sizing.py`, `master/portfolio.py`, `master/live_eligibility.py`, `master/scheduler.py`, `master/drift.py` |
| **`research/`** | The research **harnesses** that run signals through the deterministic wall: the edge **Gate** (single-signal + cross-asset ablation, four-arm), the event-study machine, and the documented-TAA cohort. Verdicts, never a funding path. | `research/gate.py`, `research/event_study.py`, `research/loop.py`, `research/equity_taa_cohort.py` |
| **`evolution/`** | The autonomous **evolution loop** (the differentiator): generate a wide population (seeds + briefs + Pine + mutations + wildcards) → compile/static-check → cheap real-bar screen → out-of-reach scorer → keep gate-passers as standalone tracks, graveyard the rest with kill reasons. | `evolution/loop.py`, `evolution/mutator.py`, `evolution/seeder.py` |
| **`orchestrator/`** | The **live autonomous loop**: the daily/intraday paper clock that executes each funded track's own spec on the latest real bars, funds gate survivors as standalone tracks, and marks-to-market. The deterministic gate is the sole promote authority. | `orchestrator/paper_step.py`, `orchestrator/loop.py` |
| **`portfolio/`** | The portfolio plane — keeps proven standalone tracks funded and **defunds decayed ones fast**. NO pooled wallet, NO cross-track capital competition; it decides only *which* tracks stay funded (the gate decides *what* may trade). | `portfolio/rotation.py` |
| **`adapters/`** | Concrete per-venue adapters implementing the `core` Protocols — data adapters and the **execution adapters** that actually place orders (Binance, Kraken, Alpaca, Polymarket) behind the interlocks. | `adapters/exec/registry.py`, `adapters/exec/binance.py`, `adapters/exec/kraken.py`, `adapters/exec/alpaca.py`, `adapters/exec/polymarket.py`, `adapters/data/` |
| **`spine/`** | The control plane: the deterministic engine facade (`run_backtest`/`run_sandbox`/`run_live`), the venue catalog with **real per-venue fee schedules + jurisdiction**, the fee router, and the global "what may we trade" universe gate. | `spine/engine.py`, `spine/venue.py`, `spine/fee_router.py`, `spine/asset_fees.py`, `spine/universe.py` |
| **`ml/`** | The ML phase: a deterministic **regime classifier** (vol-tercile × trend) and a tabular **survival model** that only **orders** the validation queue (prioritizes compute) and **never vetoes** an idea. Offline by default (XGBoost/LightGBM optional, pure-Python fallback). | `ml/regime.py`, `ml/survival.py` |
| **`mind/`** | **The Mind** — the agent's standardized self-knowledge surface: what it KNOWS (sources + freshness), how it THINKS (a multi-perspective analyst panel that debates a market read), what it has LEARNED (memory, ML state, regime coverage, gate efficiency). **Reasons only — never funds or fires.** | `mind/snapshot.py`, `mind/analysts.py`, `mind/debate.py`, `mind/rubric.py` |
| **`knowledge/`** | Persistence + memory: the dual-backend **Store** (SQLite local / Postgres-Supabase prod, one code path), the schemas, the migrations, and the **pgvector graveyard RAG memory** (record every death + win; recall dead-ends/winners; the novelty gate). | `knowledge/store.py`, `knowledge/memory.py`, `knowledge/schema_postgres.sql`, `knowledge/migrations/` |
| **`indexes/`** | The **INDEX** subsystem — operator-defined, deterministically-scored, point-in-time composite signal series that strategies later key off (a topic / prompt rubric / bucket of social accounts → a frozen-transform numeric series). Data plumbing, never a funder. | `indexes/registry.py`, `indexes/compute.py`, `indexes/spec.py` |
| **`experiments/`** | The runs/experiments **ledger** — every finder/gate run logs its exact config + seed + data-version + metrics (comparable across runs, exactly regenerable) plus a continuous forward-P&L soft-label that gives the ML ranker a gradient. | `experiments/registry.py`, `experiments/data_version.py`, `experiments/soft_labels.py` |
| **`costs/`** | Cost-transparency writers — record LLM calls into `llm_calls` and infra lines into `costs`, readable by `GET /costs`. Best-effort, offline-safe, never blocks the main path. | `costs/` (see module tree) |
| **`config/`** | Configuration: the **feature registry** (the named point-in-time signal vocabulary specs reference), settings/env loading, and the pre-registered **voices** panel (credibility). | `config/feature_registry.py`, `config/settings.py`, `config/voices.py` |
| **`ops/`** | Operational supervisors that run on crons: the **capital-protection** supervisor (reduce-only floor + profit-lock), the exec heartbeat / dead-man's switch, and backup tooling. | `ops/capital_guard.py`, `ops/heartbeat.py` |
| **`realtime/`** | The realtime lane (OFF by default) — an in-process recording worker: Binance WS closed candles → `bars_intraday`, budget-guarded poll collectors → `market_events`, a 60s heartbeat. It **records, never executes**; crons are the fallback. | `realtime/` (see module tree) |
| **`snipe/`** | An independent, lean **prediction-market** conviction-betting lane (Polymarket-direct), deliberately separate from the statistical-gate lane: the agent proposes, a deterministic ConvictionGate disposes within hard operator caps. Real money OFF until wallet keys + caps + opt-in. | `snipe/proposal.py`, `snipe/gate.py` |
| **`notify/`** | A lean best-effort Slack notifier (gate verdicts, health changes, tick errors) — never blocks the caller, no-op when unset. | `notify/slack.py` |
| **`api/`** | The FastAPI app — the single HTTP surface the web and Claude Code call. Pydantic models → OpenAPI → generated `@cosmu/contracts-ts` (never hand-typed). | `api/app.py`, `api/intelligence.py`, `api/_lifespan.py` |

---

## The money path (where real orders flow)

Real (or simulated) orders flow through **one path**, so paper and live share the exact same physics:

1. **The clock proposes.** `orchestrator/paper_step.py::step_tracks` (the daily/intraday paper clock)
   re-evaluates each funded track's own spec on the latest real bars — its stop / take / time-stop /
   signal-exit closes the position, its entry signal re-enters. Funding of new survivors and marking happen in
   `orchestrator/loop.py` (`fund_tracks_from_survivors`, `mark_tracks`); the autonomous cycle that drives it is
   `master/scheduler.py::run_tick`.
2. **The single order path.** Every intended order goes through `master/execution.py::execute_orders`, which
   **first** runs the risk gauntlet (`master/risk.py::validate_order_full`) and **then** routes to a real venue
   **only if** `live_enabled AND adapter.active AND gate_passed AND caps available AND not kill-switch` — else it
   produces a deterministic sim-fill (same 5 bps half-spread the Gate charges, so paper P&L is never flattered).
3. **The adapters.** `adapters/exec/registry.py::adapter_for` resolves the live adapter for a venue; the real
   adapters are `binance.py` (spot, ccxt, testnet-default), `kraken.py` (spot, no public sandbox → disabled or
   live), `alpaca.py` (equities, paper-default), `polymarket.py` (prediction CLOB on Polygon, limit-only). Each
   adapter's `resolve_mode()` is itself an interlock: it only reaches real money with that venue's real keys
   **and** `live.mode == "real"`.
4. **The book of record.** `master/portfolio.py::Portfolio` holds positions, marks-to-market, and tracks
   net-of-cost P&L, drawdown, and the daily-loss counter (which trips the kill-switch).

Position size is **identical** in backtest, paper, and live — `master/sizing.py::size_fraction` is the one
shared leaf (static cap × conviction, plus a vol-target envelope), so `tracks.return_pct` (what live-eligibility
reads) is never misleading.

### Safety interlocks

The machine is built so that **money cannot be lost by accident**. Live is OFF by default; the moves that can
lose money are guarded in layers:

- **The locked Gate** (`research/gate.py`, `master/scorer.py`, `master/cohort.py`, `master/fdr.py`,
  `master/holdout.py`) is the **only** thing that funds. Its bar is pre-registered (fixed before looking),
  deflated against the cumulative trial count, FDR-controlled across the cohort, and the holdout is **one-shot**
  (a second request returns the stored verdict, never a recompute). It is calibrated strict and **never loosened**.
- **The five arming interlocks** — a real submit needs **all five**: (1) the global live toggle ON,
  (2) the target venue's adapter `active` (real keys + `live.mode == "real"`, via `resolve_mode()`),
  (3) `gate_passed` on the order, (4) caps available (per-venue, per-strategy, global), (5) no kill-switch
  (drawdown / daily-loss / per-combo equity not breached). Enforced in `master/execution.py::execute_orders`
  with `master/live_eligibility.py` gating which cells are even armable.
- **Live-eligibility, fail-closed** (`master/live_eligibility.py`, `ml/regime.py`) — a cell can be armed only
  with ≥ `PAPER_MIN_DAYS` of net-positive forward evidence **and** when the current market regime is one the
  strategy proved positive P&L in. **An empty regime passport fails safe** (never eligible). The human still
  clicks the final launch button.
- **The sandbox per-combo wallet** (`master/portfolio.py::TrackRiskView`, `master/risk.py` per-combo checks) —
  each (strategy × symbol × venue) combo has its own `starting_capital` and can never lose more than that;
  breaching its kill-floor liquidates **only** that combo (neutral sizing defaults). Layered *with* the aggregate
  backstops, never replacing them.
- **The capital-protection supervisor** (`ops/capital_guard.py::run_capital_guard`) — a cron that issues
  **reduce-only** protective fills per track: liquidate on a floor breach (hard loss backstop) and trim to lock
  realized gains (profit-lock). It only ever *reduces*, and routes live only when the venue is armed — safe while
  live is off.
- **The risk gauntlet** (`master/risk.py::validate_order_full`) — every order must carry SL/TP (except
  reduce-only exits), respect per-strategy/global/per-venue caps + min cash reserve, and is rejected by the
  drawdown kill-switch / daily-loss auto-disarm / **martingale & averaging-down ban**.
- **Keyless bars venue flag** (`data/market.py`, env `COSMU_BARS_VENUE`) — the price series every backtest and
  paper clock reads (regime, vol, freshness checks) can be switched from Binance to Kraken with one env var when
  Binance is geo-blocked, no Kraken account needed. See [runbooks/kraken-activation.md](runbooks/kraken-activation.md).

---

## Product surface (apps/web)

The web app is a lean **monitoring + steering cockpit** — it reports the engine's verdicts and lets the operator
steer/arm, but **never decides whether an order is real**. Source of truth for nav is `apps/web/app/`. Seven
primary surfaces; the landing page redirects to **Strategies**. (Older routes — Overview, Lab, Mind, Console,
Theories — keep accruing backend data but redirect here.)

| Route | What it shows |
|---|---|
| `/strategies` | **Default landing.** The one granular leaderboard: every (algo × asset × venue) triplet, outlier-ranked, with its Gate verdict, lifecycle stage, and edge facets. Detail at `/strategies/{id}`. |
| `/paper` | The Paper (forward-test) dashboard — gate-passed strategies running on real bars with no real money: equity hero, KPI grid, open positions vs track record. |
| `/live` | The gated money screen (dimmed until armed): real positions, the live-vs-sim money split, the editable hard-limit **Rules**, the ARM toggle, and the kill-switch (Stop). |
| `/indexes` | The operator-defined, deterministically-scored signal **indexes** (point-in-time numeric series strategies key off). |
| `/costs` | Is the alpha worth what it costs to run? — trading fees + infra + LLM spend vs per-strategy ROI. |
| `/keys` | A read-only ledger of every provider/service key (present/absent status only — keys are server-side). |
| `/commands` | A static reference of the Claude Code procedures (the *doing* — authoring, ingest, gate runs, deploy — happens in Claude Code + skills, not as app pages). |

Cross-cutting: every figure carries a **SIM / LIVE** money-state badge; empty surfaces show an honest
offline/no-data state; **synthetic numbers never ship**. Fields are consumed from the generated
`@cosmu/contracts-ts`, never hand-typed. See [PRODUCT.md](PRODUCT.md) for the full product rationale.

---

## Where to go next

- **Vocabulary** (Strategy/Version/Track/Gate/the Mind, the locked lifecycle): [GLOSSARY.md](GLOSSARY.md)
- **Where data lives** (Supabase tables + R2 lake, connection footguns): [DATA_INDEX.md](DATA_INDEX.md)
- **How to author a strategy** (the never-drifting feature/spec reference): [AUTHORING.md](AUTHORING.md)
- **The product contract** (surfaces + epics): [PRODUCT.md](PRODUCT.md) · the strategic anchor: [VISION.md](VISION.md)
- **What's actually built + decisions taken**: [IMPLEMENTATION.md](IMPLEMENTATION.md) · [DECISIONS.md](DECISIONS.md) · [LESSONS.md](LESSONS.md)
- **Activate Kraken as the bars/exec venue**: [runbooks/kraken-activation.md](runbooks/kraken-activation.md)
- **The next edge lane** (social/LLM/niche plan): [plans/social-llm-edge-lane.md](plans/social-llm-edge-lane.md)
- **The full curated doc index**: [INDEX.md](INDEX.md)
- **The canonical agent entry point** (invariants + skills): [../AGENTS.md](../AGENTS.md)

---

## Module tree (auto-generated)

> **Do not edit by hand below this line.** Regenerate from the code with
> `cd apps/engine && python3 -m cosmu.docs.codebase_map` (and `--check` in CI to guard against drift).

<!-- BEGIN GENERATED: module-tree -->

_Walked live from `apps/engine/cosmu/` by `python3 -m cosmu.docs.codebase_map`. Each package's one-liner is its `__init__.py` summary; each module's is its docstring or `# intent:` header. Re-run after adding/removing a module — `--check` fails CI on drift._

**25 top-level packages** under `cosmu/`:

### `cosmu/adapters/` — concrete adapters that implement the core asset-agnostic Protocols per venue/class

_14 module(s); no top-level modules (see sub-packages)._

### `cosmu/api/` — FastAPI package.

_59 module(s) total. Top-level modules:_

| module | summary |
|--------|---------|
| `_lifespan.py` | app startup/shutdown — health ping + best-effort boot tasks |
| `_shared.py` | shared state + helpers for the api routers (store, settings, coercers) |
| `app.py` | expose the engine's typed control-plane API |
| `intelligence.py` | compute system-level intelligence metrics — the machine's self-awareness snapshot. Answers "is the machine getting smarter?" not… |

### `cosmu/config/` — Configuration package.

_3 module(s) total. Top-level modules:_

| module | summary |
|--------|---------|
| `feature_registry.py` | define the named feature vocabulary the lab agent may reference |
| `settings.py` | load typed engine settings from server env/.env.local |
| `voices.py` | the PRE-REGISTERED VOICE PANEL — the single, operator-edited list of voices (X handles, subreddits, RSS/newsletter feeds) the cre… |

### `cosmu/core/` — the asset-agnostic core — the typed contracts every asset class, engine, and adapter implements

_2 module(s) total. Top-level modules:_

| module | summary |
|--------|---------|
| `calendars.py` | per-asset-class trading calendars so the four classes resample to one daily baseline correctly |
| `interfaces.py` | the asset-agnostic domain contracts (Deliverable 3) every class/engine/adapter implements |

### `cosmu/costs/` — cost-transparency writers — record LLM calls into llm_calls and infra lines into costs

_7 module(s) total. Top-level modules:_

| module | summary |
|--------|---------|
| `accounts.py` | the model_accounts REGISTRY — one row per metered model account (e.g. an OpenRouter key with ~$30 free credit). The failover rout… |
| `alerts.py` | budget threshold checks + Slack emit + recommendation rows |
| `failover.py` | the FAILOVER ROUTER wrapping the chat() seam (lab/llm.py). Pre-checks credits/ledger, ISSUES the call on the active account, and… |
| `fetchers.py` | live vendor spend fetchers |
| `operating_costs.py` | SINGLE SOURCE OF TRUTH for Cosmu's OPERATING costs — the monthly cost of running the machine, net of which the only metric is pro… |
| `refresh.py` | 6h vendor spend refresh job — fetch all vendor costs, check budget, emit alerts |
| `writer.py` | cost-transparency writers |

### `cosmu/data/` — market-data and deterministic backtest helpers

_62 module(s) total. Top-level modules:_

| module | summary |
|--------|---------|
| `_iso.py` | ONE canonical ISO-8601 form for every point-in-time timestamp written to the alt-data store (Postgres hot tier, Parquet/DuckLake… |
| `age_out.py` | the ONE steady-state writer of the cold lake. Incrementally mirrors the Postgres alt_data table into the DuckLake lake via a sing… |
| `alt_join.py` | ONE point-in-time alt-data join used by every screen path (the FarmLoop cohort screen AND the Strategy Finder sweep) so a funding… |
| `altdata.py` | a point-in-time-safe seam for social/alt data (LunarCrush etc.) feeding the gate and, later, the LLM feature factory |
| `backtest.py` | run an honest deterministic bar backtest for StrategySpec screens |
| `binance_vision_backfill.py` | the OPERATOR-DRIVEN bulk OHLCV backbone — one CLI that bulk-downloads YEARS of klines from the FREE Binance Vision public archive… |
| `event_backtest.py` | backtest the first-class EVENT strategy type through the SAME engine indicator strategies use, so the gate sees an identical Back… |
| `events_store.py` | the POINT-IN-TIME UNSTRUCTURED-EVENT store (realtime-data-lane epic §5) — typed MarketEvent records (news headline / tweet / Poly… |
| `export_alt_parquet.py` | ONE-SHOT migration of the hot alt_data table (Postgres or SQLite) into the COLD Parquet lake (local dir or Cloudflare R2). DuckDB… |
| `intraday_binance_vision.py` | point-in-time-honest 1m kline fetcher+cacher for Binance Vision (data.binance.vision) — the intraday/microstructure plumbing for… |
| `market.py` | fetch and cache Binance spot OHLCV bars |
| `pg_backup.py` | the SELF-MANAGED money-truth backup — Supabase's managed daily backups are GONE on the Free plan, so this is the safety net. `pg_… |
| `price_cells.py` | STAGE 1 of the UNIVERSAL PRICE LAYER — turn the venue-tagged `universe_pairs` rows into the (pair × venue) CELLS the crypto scree… |
| `reference.py` | the UNIVERSAL PRICE LAYER reference resolver — de-collapse the venue axis by computing a pair's price ONCE (a single canonical RE… |
| `retention.py` | the GATED Postgres retention prune for alt_data — the step that actually keeps the hot DB lean after the history has been mirrore… |
| `slippage.py` | model per-fill execution slippage as a distribution (mean + variance), not a flat bps |
| `universe.py` | the SINGLE source of truth for the liquid perp universe the data layer + carry/xsec research screen — one deduped, ordered list s… |
| `universe_build.py` | the OPERATOR-DRIVEN builder that turns the live venue universe into a PERSISTED, survivorship-honest, liquidity-ranked source — f… |
| `universe_calendar.py` | point-in-time tradable-universe membership so backtests never see survivorship bias |
| `venue_universe.py` | the ONE venue-tagged, liquidity-ranked SOURCE of every tradable pair across our venues — fetch the live instrument list + 24h liq… |

### `cosmu/docs/` — package marker for the in-code documentation generators (the authoring fiche).

_2 module(s) total. Top-level modules:_

| module | summary |
|--------|---------|
| `authoring_fiche.py` | Authoring fiche generator. |
| `codebase_map.py` | Codebase-map generator. |

### `cosmu/evolution/` — Evolution loop package.

_4 module(s) total. Top-level modules:_

| module | summary |
|--------|---------|
| `evolve.py` | the self-reinforcing core — isolate a GATE-PASSED strategy's winning SIGNAL logic (its entry conditions + entry-setup modules + t… |
| `loop.py` | the autonomous farming loop — generate a wide population (seeds + mutations + wildcards + pine imports), compile + static-check,… |
| `mutator.py` | catalog of deterministic mutation + wildcard operators that turn a parent StrategySpec into a child |
| `seeder.py` | seed typed strategy hypotheses from templates before LLM autonomy is enabled |

### `cosmu/experiments/` — the experiments registry package — a runs/experiments ledger so every finder/gate run logs its exact config + seed + data_version…

_3 module(s) total. Top-level modules:_

| module | summary |
|--------|---------|
| `data_version.py` | the DATA-VERSION fingerprint — turn the exact bars a finder/gate run consumed into a short, deterministic hash so two runs are CO… |
| `registry.py` | the EXPERIMENTS REGISTRY — the thin, append-only ledger every finder/gate run logs to so each result carries its exact config + s… |
| `soft_labels.py` | SOFT-LABELS — turn the experiments registry's continuous forward-P&L into a training signal the ML survival ranker can learn from… |

### `cosmu/indexes/` — the INDEX subsystem — operator-defined, deterministically-scored, point-in-time composite series that strategies later key off. P…

_6 module(s) total. Top-level modules:_

| module | summary |
|--------|---------|
| `compute.py` | turn an IndexSpec into ONE point-in-time value per symbol per pass, reusing the CANONICAL scorers — never reimplementing them: te… |
| `monitor.py` | the deterministic health/reliability readout for an index — freshness, coverage, and ranking STABILITY — so the operator can trus… |
| `registry.py` | persistence for the INDEX definition registry — create / list / get the operator's indexes |
| `routing.py` | the seam that makes an INDEX a first-class, key-off-able strategy FEATURE — so "strategies built on top of indexes" is a config m… |
| `run.py` | the cron/Modal entrypoint that REFRESHES every active index — appends ONE point-in-time value per symbol per pass, reusing the ca… |
| `spec.py` | the typed definition of an INDEX — a named, point-in-time, deterministically-scored composite series the operator creates and (la… |

### `cosmu/ingest/` — ingest-time adapters that turn raw/unstructured sources into validated numeric features.

_17 module(s) total. Top-level modules:_

| module | summary |
|--------|---------|
| `alt_summary.py` | keep a tiny per-(provider, metric) rollup of the append-only alt_data store fresh, so the UI's "how fresh / how much" reads don't… |
| `bars.py` | the MANAGED bar layer — paginated multi-venue OHLCV history (Binance + Kraken via ccxt) plus a dedup-merge bar cache, the bar ana… |
| `catalog.py` | the single declarative catalog of MANAGED data sources — the discovery + dispatch surface behind `manage-data fetch/backfill/veri… |
| `coverage.py` | the data-quality / VERIFY engine — turn the append-only point-in-time stores (alt_data + the bar cache) into a clear "what we hav… |
| `document_handler.py` | the NL→strategy pipeline's FRONT DOOR — turn an unstructured document (a vibe note, an abstract, a page from an old trading book,… |
| `health.py` | the stale-source alarm — after a scheduled ingest pass, detect SILENT data-lane degradation (every source returned 0 this pass, o… |
| `llm_formatter.py` | the GENERIC LLM data-formatter — turn ANY raw text (news headline, social post, scraped snippet) into ONE validated, typed featur… |
| `manage.py` | the ONE managed-data control surface — `fetch` / `backfill` / `verify` / `update` over BOTH the alt-data store and the multi-venu… |
| `ml_panel.py` | the ML-READY STANDARDIZED POINT-IN-TIME panel — join the bar cache + the append-only alt store into a dense per-(symbol, timefram… |
| `pipeline.py` | scheduled free-data ingestion → the append-only, point-in-time alt-data store |
| `polymarket_odds.py` | per-MARKET Polymarket YES-odds ingest → the append-only, point-in-time alt-data store, keyed by conditionId — the data foundation… |
| `profile_source.py` | DATA-TRUST AUDIT for a NEW alt-data source — auto-profile its full point-in-time history (coverage · gaps · staleness · look-ahea… |
| `run.py` | the one-pass, cron-able free-data ingest CLI — arrange the free sources once, hit go, fill the append-only point-in-time alt-data… |
| `standardize.py` | the LLM universal adapter — turn unstructured headlines into a validated numeric feature, ONCE, at ingest time |
| `venue_fees_refresh.py` | the DAILY fee-routing process. Snapshot each crypto venue's current per-instrument fee into the point-in-time venue_fees store, t… |
| `venue_metadata_refresh.py` | the per-venue MARKET-METADATA snapshot — last price + 24h (quote) volume per (venue, symbol), stored point-in-time so the app can… |
| `voices_pass.py` | the CREDIBILITY PASS (realtime-data-lane epic P2) — one bounded cron tick that runs the dormant "PageRank for credibility" pipeli… |

### `cosmu/knowledge/` — Knowledge and persistence package.

_4 module(s) total. Top-level modules:_

| module | summary |
|--------|---------|
| `block_registry.py` | persistence + queries for the strategy BUILDING-BLOCK registry (lineage, dedup, observational block-level stats) |
| `lifecycle_status.py` | Single source of truth for ``strategy_versions.status`` — the lifecycle vocabulary. |
| `memory.py` | the SELF-IMPROVEMENT FLYWHEEL's long-term memory — a graveyard/research RAG. It persists a research note + a point-in-time, DETER… |
| `store.py` | persist control-plane truth and audit events |

### `cosmu/lab/` — Autonomous lab package.

_14 module(s) total. Top-level modules:_

| module | summary |
|--------|---------|
| `author.py` | turn a plain-language brief into a typed, validated StrategySpec draft so a human can author/suggest strategies in chat (LLM-opti… |
| `batch.py` | one-command batch pipeline — author N theme-varied StrategySpecs, validate each against the real compiler (static_check + compile… |
| `curator.py` | the CURATOR of the self-improvement flywheel — turn a gate-passing Version into a reusable, parameterized SKILL recipe (a spec TE… |
| `finder.py` | the Strategy Finder — grid-search a spec's fittable param space into many Versions, run each through the DETERMINISTIC screen (da… |
| `inbox.py` | the strategies/inbox scanner — on engine startup AND via `python3 -m cosmu.lab.inbox`, scan strategies/inbox/*.{md,pine,json}, tr… |
| `indexes.py` | the LLM qualitative→quantitative INDEX scorer — an LLM-AS-JUDGE that reads a typed set of source snippets for an `as_of` date and… |
| `llm.py` | the REAL LLM seam — call OpenRouter over stdlib HTTP for a STRUCTURED, schema-validated proposal (instructor-style: prompt for th… |
| `ml.py` | the ML-through-natural-language seam — turn a plain-language ML request ("rank survivors by edge-persistence", "which features ma… |
| `nlp_intake.py` | the NL→STRATEGY PIPELINE orchestrator — chain the four scaffold agents so a natural-language idea (a vibe, an abstract, a passage… |
| `research.py` | the autonomous RESEARCH BRAIN pass — LLM PROPOSES, deterministic DISPOSES. It (1) gathers context via the propose-only lab tool b… |
| `router.py` | route model work through configured tiers and spend caps AND wire the actual model call |
| `strategize.py` | the ONE front-door router for strategy intake — classify a free-form operator input (a vibe, a URL, a pasted Pine script, "find m… |

### `cosmu/master/` — Deterministic master package.

_31 module(s) total. Top-level modules:_

| module | summary |
|--------|---------|
| `cohort.py` | the cohort promotion gate — the single place many DISTINCT candidates (RD-Agent/Qlib/AutoML/RL/the evolution loop) are judged tog… |
| `correlation_ledger.py` | persist EVERY correlation_scan finding to `correlation_findings` so the machine's correlation memory is TRACKED over time, not ju… |
| `cpcv.py` | implement Combinatorial Purged Cross-Validation (CPCV) with embargo as a stronger OOS validator than the single-path purged holdo… |
| `crowding.py` | PORTFOLIO-RISK overlay — turn the (already-built, propose-only) cross-cell crowding detector (master/strategy_correlation.pairwis… |
| `cv.py` | purged + embargoed combinatorial cross-validation (CPCV, López de Prado) so fold splits don't leak |
| `divergence.py` | the SIM-vs-BACKTEST divergence signal per paper track — an EARLY WARNING that a funded track's REAL marked forward return has sto… |
| `drift.py` | ALPHA-DECAY as a first-class primitive — estimate each funded track's EDGE HALF-LIFE and detect live-vs-funded DRIFT early, so ca… |
| `execution.py` | the SINGLE order path for sim AND live — every intended order runs the master/risk.py gauntlet first (reject + audit on fail), th… |
| `fdr.py` | Benjamini-Hochberg false-discovery-rate control across all candidate trials so an LLM generating unlimited ideas can't manufactur… |
| `holdout.py` | enforce one-shot holdout evaluation so an autonomous loop cannot silently overfit the untouched set |
| `lane_router.py` | the TYPED two-lane router — read a StrategySpec's `lane` discriminator and dispatch to the ONE correct evaluator path, so routing… |
| `lifecycle.py` | the ADDITIVE lifecycle-trace audit — a thin, append-only journal of a strategy version's backtest → paper → forward → live-ready… |
| `live_eligibility.py` | the deterministic LIVE-ELIGIBILITY gate — what CAN be armed. A strategy may go live ONLY when it has BOTH (a) >= PAPER_MIN_DAYS o… |
| `neutral.py` | the TWO-LEG delta-neutral track (DERIVATIVES_PLAN P0.3, §6) — pair a LONG-SPOT leg with a SHORT-PERP leg held under ONE strategy_… |
| `paper_maturity.py` | the paper maturity signal per SIM track — has a funded track lived long enough on real closes, AND is it net-of-fee positive, to… |
| `portfolio.py` | the sim/live portfolio of record — hold positions, mark-to-market on latest bars, persist portfolio_snapshots, compute net-of-cos… |
| `promotion.py` | the live-replication FREEZE — turn a gate-passing Version into ONE durable `strategy_promotions` row that snapshots EVERYTHING ne… |
| `rejects_lane.py` | the REJECTS WATCH-LIST lane — OBSERVE-ONLY. The Gate is correctly strict (0 survivors = the machine working) and we NEVER loosen… |
| `reset.py` | CLEAN SIM-STATE CUTOVER — purge the synthetic-era discovery + sim state so the honest real-data loop starts from a clean $100k fo… |
| `risk.py` | enforce deterministic order safety for paper and live |
| `risk_metrics.py` | drawdown-aware performance metrics the Sharpe is blind to. Sharpe rewards smooth per-bar returns but ignores TAIL DEPTH: two book… |
| `scheduler.py` | the AUTONOMOUS MASTER TICK — one bounded, idempotent, audited self-driving cycle the human oversees. It composes the seams alread… |
| `scorer.py` | score strategy evidence deterministically |
| `screen_universe.py` | ONE source of truth for the per-symbol cost + calendar context a cross-asset SCREEN needs — which market symbols are equity / Hyp… |
| `sizing.py` |  |
| `strategy_correlation.py` | pure diagnostic helper for cross-strategy return-stream correlation — identify REDUNDANT funded or candidate tracks before the fl… |
| `tracks.py` | Track lifecycle helpers shared by every create lane (evolution loop, finder, spine, research arms). |
| `trade_floor.py` | the per-combo TRADE FLOOR — the single source of truth for the minimum number of trades a tradeable cell (algorithm × asset × ven… |
| `trials.py` | global multiple-testing ledger so the Deflated Sharpe deflates against every hypothesis ever run, not just one strategy's params |
| `verdict_log.py` | persist EVERY cohort Gate verdict to `gate_verdicts` so the machine's FULL experiment-memory is queryable (the Mind page + a "hav… |
| `zero_capital.py` | the ZERO-CAPITAL PAPER TRACK opener — shared by the two observe-only lanes (the VIBE/EXPLORE lane and the REJECTS WATCH-LIST lane… |

### `cosmu/mind/` — the Mind — the trading agent's standardized self-knowledge surface. It answers three questions in one vocabulary: what it KNOWS (…

_14 module(s) total. Top-level modules:_

| module | summary |
|--------|---------|
| `analysts.py` | the analyst panel — a TradingAgents-style team of perspectives that each read ONE family of the agent's existing point-in-time si… |
| `authority.py` | PHASE 3 of "PageRank for credibility" — PRIMACY + AUTHORITY. Deterministic, NO LLM. Three signals fuse into a credibility weight… |
| `claims.py` | PHASE 1 of "PageRank for credibility" — CLAIM EXTRACTION. An LLM-as-extractor reads a voice's timeline (X → Reddit → Substack/new… |
| `debate.py` | the debate — combine the analyst panel's stances into ONE standardized market read (consensus · conviction · agreement) plus the… |
| `judge.py` | the Mind's LLM-as-JUDGE seam. Given a pillar's RUBRIC + its point-in-time evidence, ask a model for a typed Verdict (instructor-s… |
| `matcher.py` | the NL→strategy pipeline's GROUNDING step — map the Thinker's modern feature TERMS onto the real, enabled FEATURE_REGISTRY (cosmu… |
| `news_intel.py` | assemble a point-in-time news/intel panel from ingested news_event_score data. Inputs: the append-only alt_data store. Outputs: a… |
| `outcomes.py` | PHASE 2 of "PageRank for credibility" — DETERMINISTIC OUTCOME RESOLUTION + per-author track record. NO LLM on this path: resolve… |
| `rubric.py` | the committee's RUBRICS + the typed VERDICT an LLM judge returns. Each MARKET pillar has a rubric — its trading prior, the criter… |
| `scores.py` | compose the SCORES COCKPIT — per-source + composite INDEX scores grouped by category (crypto · social · macro · OSINT · metals/fo… |
| `signal_builder.py` | the NL→strategy pipeline's CLAIM-GROUNDING step — turn a complex, non-registry claim the Matcher couldn't resolve ('astrological… |
| `snapshot.py` | assemble the full Mind payload — KNOWS (data sources grouped by perspective + freshness), THINKS (the analyst panel + debate), LE… |
| `source_trust.py` | compute a plain-language trust score for every registered data source. Inputs: the append-only alt_data store (point-in-time fres… |
| `thinker.py` | the NL→strategy pipeline's REASONING step — read the parsed DocumentChunk(s) and STANDARDIZE the prose (a vibe, an abstract, a pa… |

### `cosmu/ml/` — the ML phase — a deterministic regime classifier the model later refines, and a tabular SURVIVAL model that only ORDERS the valid…

_5 module(s) total. Top-level modules:_

| module | summary |
|--------|---------|
| `logistic.py` | the shared pure-Python regularized-logistic primitives used by every tabular ML head in cosmu.ml (the survival ranker AND the tri… |
| `meta_label.py` | the META-LABEL MODEL interface — a SECONDARY, PROPOSE-ONLY classifier that consumes the experiments registry's continuous forward… |
| `metalabel.py` | the runtime for triple-barrier META-LABELING — a SECONDARY regularized-logistic gate that the backtest consults at each primary e… |
| `regime.py` | deterministic market-regime classifier — realized-vol tercile x trend sign on a reference close series, reusing data/backtest._re… |
| `survival.py` | the tabular SURVIVAL model — it predicts an edge-persistence score in [0,1] for each screen-survivor and uses it ONLY to ORDER wh… |

### `cosmu/notify/` — lean Slack notifier — best-effort, never blocks caller, no-op when webhook unset.

_1 module(s) total. Top-level modules:_

| module | summary |
|--------|---------|
| `slack.py` | lean Slack notifications — post to a webhook on the few high-signal events only (gate verdict / first paper survivor, deploy heal… |

### `cosmu/ops/` — _(no package summary)_

_2 module(s) total. Top-level modules:_

| module | summary |
|--------|---------|
| `capital_guard.py` | the CAPITAL-PROTECTION SUPERVISOR — a deterministic, read-then-reduce probe that protects a FUNDED combo's capital independently… |
| `heartbeat.py` | the dead-man's-switch for the autonomous cron fleet. A scheduled probe (Modal cron) that detects SILENT fleet death — the ingest… |

### `cosmu/orchestrator/` — orchestrator — the live autonomous loop (ingest → signals → ML → gate → paper tracks)

_2 module(s) total. Top-level modules:_

| module | summary |
|--------|---------|
| `loop.py` | CLOSE THE AUTONOMOUS LOOP — read REAL persisted survivors (Finder/research gate-passers with tracks), open a STANDALONE paper tra… |
| `paper_step.py` | THE PAPER EXECUTOR — make a funded track a GENUINE paper run by running each survivor's OWN strategy logic forward on the latest… |

### `cosmu/portfolio/` — portfolio-plane lifecycle — keep proven standalone tracks funded and defund decayed ones

_1 module(s) total. Top-level modules:_

| module | summary |
|--------|---------|
| `rotation.py` | per-track lifecycle decisions for the standalone paper model — decide which proven tracks stay funded and which have decayed (→ d… |

### `cosmu/realtime/` — the realtime lane (realtime-data-lane epic P3) — an in-process, OFF-by-default recording worker: Binance WS closed candles → bars…

_4 module(s) total. Top-level modules:_

| module | summary |
|--------|---------|
| `bars_store.py` | the INTRADAY BAR STORE (realtime-data-lane epic P3) — durable, deduped persistence for the closed 1m candles the realtime worker… |
| `binance_ws.py` | the Binance WebSocket KLINE consumer (realtime-data-lane epic P3) — subscribe to the combined 1m-kline stream for the configured… |
| `collectors.py` | BUDGET-GUARDED POLL COLLECTORS (realtime-data-lane epic P3) — the worker's short-poll lane for sources with no stream: each Colle… |
| `worker.py` | the REALTIME WORKER SUPERVISOR (realtime-data-lane epic P3) — one asyncio task tree that RECORDS: Binance WS closed 1m candles →… |

### `cosmu/research/` — research harnesses (edge gate) that run hand-built signals through the deterministic wall.

_65 module(s) total. Top-level modules:_

| module | summary |
|--------|---------|
| `_arm_regimes.py` | DERIVE an arm's proven-regime passport from its OWN per-regime PnL instead of hardcoding the full set ['bull','bear','chop']. The… |
| `arm_fleet.py` | arm_fleet.py — one-command entrypoint to arm the full equity paper fleet. |
| `arm_rotation.py` | ONE rotation-close for every deploy-lane arm. A documented rotation strategy (GEM, GTAA, VAA, PAA, DAA, sector/TSMOM, risk-parity… |
| `attribution.py` | SIM→LIVE VARIANCE ATTRIBUTION — decompose the divergence between a track's sim paper and its realized live results into named, si… |
| `carry_ablation.py` | the Phase-0 P0.6 carry/neutral ablation harness — run the funding-carry + cross-sectional-neutral specs through the EXISTING dete… |
| `correlation_scan.py` | the HONEST alt-data correlation engine — "look for correlations" across EVERY ingested alt-data feature without lying. For each (… |
| `cost_basis.py` | recompute a stored strategy-version's NET performance under several COST BASES — the friction-free baseline ("No fees") and each… |
| `cost_surface.py` | answer "does this strategy still HOLD across fees / venues / asset types?" by sweeping a compiled strategy over a scenario grid {… |
| `cross_feature_scan.py` | the CROSSING engine — find correlations BETWEEN alt-data sources, not just feature→return. The single- feature correlation_scan a… |
| `disconfirmers.py` | a REUSABLE disconfirmer harness — the standard "prove the IC isn't an artefact" tools any new feature / signal must survive BEFOR… |
| `equity_accel_dual_momentum.py` | DEPLOY-A-DOCUMENTED-STRATEGY track (NOT the in-sample 0.95 deflated-Sharpe Gate). ACCELERATING DUAL MOMENTUM (ADM), popularized b… |
| `equity_accel_dual_momentum_arm.py` | ARM the validated ACCELERATING DUAL MOMENTUM (ADM / Engineered Portfolio) strategy as a COSMU paper — register it into the SAME c… |
| `equity_daa.py` | DEPLOY-A-DOCUMENTED-STRATEGY track (NOT the in-sample 0.95 deflated-Sharpe Gate). Wouter Keller & Jan Willem Keuning's DEFENSIVE… |
| `equity_daa_arm.py` | ARM the validated KELLER DEFENSIVE ASSET ALLOCATION (DAA, top-6, canary EEM/AGG) strategy as a COSMU paper — register it into the… |
| `equity_dual_momentum.py` | DEPLOY-A-DOCUMENTED-STRATEGY track (NOT the in-sample 0.95 deflated-Sharpe Gate). Gary Antonacci's GLOBAL EQUITIES MOMENTUM (GEM… |
| `equity_dual_momentum_arm.py` | ARM the validated Global Equities Momentum (GEM / Antonacci Dual Momentum) strategy as COSMU's FIRST LIVE PAPER — register it int… |
| `equity_dual_momentum_qqq.py` | DEPLOY-A-DOCUMENTED-STRATEGY track — a TECH-TILT VARIANT of Antonacci's Global Equities Momentum (GEM). The canonical GEM rotates… |
| `equity_dual_momentum_qqq_arm.py` | ARM the QQQ/EFA tech-tilt dual-momentum variant (equity_dual_momentum_qqq) as a SIM paper track — the SAME control-plane rows the… |
| `equity_faber_gtaa.py` | DEPLOY-A-DOCUMENTED-STRATEGY track (NOT the in-sample 0.95 deflated-Sharpe Gate). Mebane Faber's "A Quantitative Approach to Tact… |
| `equity_faber_gtaa_arm.py` | ARM the validated FABER GTAA (Mebane Faber 2007, 10-month SMA timing) strategy as a COSMU paper — register it into the SAME contr… |
| `equity_faded_backfill.py` | reduce SURVIVORSHIP bias in the equity universe. The cached 73 names are TODAY's mega-cap survivors (AAPL/NVDA/META/TSLA...) — a… |
| `equity_haa.py` | DEPLOY-A-DOCUMENTED-STRATEGY track — Wouter Keller & Jan Willem Keuning's HYBRID ASSET ALLOCATION (HAA), from "Relative and Absol… |
| `equity_haa_arm.py` | ARM the validated KELLER HYBRID ASSET ALLOCATION (HAA, top-4, single TIP canary) strategy as a COSMU paper — register it into the… |
| `equity_holdout.py` | provide a REAL purged + embargoed out-of-sample HOLDOUT for the equity research cohorts, replacing the hardcoded `holdout_deflate… |
| `equity_lowvol_bab_cohort.py` | test the documented LOW-VOLATILITY / BETTING-AGAINST-BETA (BAB) anomaly on REAL split-adjusted equity daily data — rank the unive… |
| `equity_managed_futures_overlay.py` | the FIRST genuinely-DIFFERENT risk premium added to the floor — MANAGED FUTURES (time-series trend-following, long/short across a… |
| `equity_paa.py` | DEPLOY-A-DOCUMENTED-STRATEGY track (NOT the in-sample 0.95 deflated-Sharpe Gate). Wouter Keller & Jan Willem Keuning's PROTECTIVE… |
| `equity_paa_arm.py` | ARM the validated KELLER PROTECTIVE ASSET ALLOCATION (PAA1, top-6, a=1) strategy as a COSMU paper — register it into the SAME con… |
| `equity_reversal_cohort.py` | test whether EQUITY short-term (1-week) cross-sectional reversal carries an exploitable edge after REALISTIC equity costs. Rank t… |
| `equity_risk_parity.py` | DEPLOY-A-DOCUMENTED-STRATEGY track (NOT the 0.95 in-sample Gate). A simple, textbook RISK-PARITY sleeve: inverse-realized-vol wei… |
| `equity_risk_parity_arm.py` | ARM the validated RISK-PARITY ({SPY, AGG, GLD} inverse-realized-vol, monthly rebalance) strategy as a LIVE PAPER — register it in… |
| `equity_risk_parity_backfill.py` | backfill DAILY ADJUSTED-CLOSE (total-return) bars for the inverse-vol Risk-Parity sleeve {SPY, AGG, GLD} into a parallel `<SYM>_t… |
| `equity_sector_rotation_arm.py` | ARM the validated SECTOR-MOMENTUM ROTATION (TAA) strategy as a COSMU paper track — register it into the SAME control-plane rows t… |
| `equity_sector_rotation_taa.py` | DEPLOY-A-DOCUMENTED-STRATEGY track (NOT the in-sample 0.95 deflated-Sharpe Gate). SECTOR-MOMENTUM ROTATION with a market-regime r… |
| `equity_taa_cohort.py` | give the DOCUMENTED multi-asset TAA ROTATION strategies a FAIR test through the REAL honest Gate (master.cohort.promote_cohort: p… |
| `equity_taa_ensemble.py` | RECOMBINE the honest-Gate survivors (the evolve-strategy move: replicate/mix what works). The seven survivors from equity_taa_coh… |
| `equity_taa_robustness.py` | REPLICABILITY pass on the honest-Gate survivors (DAA/VAA/ADM from equity_taa_cohort). A real "snipe" must survive its own PARAMET… |
| `equity_total_return_backfill.py` | backfill ADJUSTED-CLOSE (total-return) daily bars for the ETFs the Dual-Momentum (GEM) strategy ranks — EFA (intl equity), AGG (U… |
| `equity_tsmom_trend.py` | DEPLOY-A-DOCUMENTED-STRATEGY track (NOT the in-sample 0.95 deflated-Sharpe Gate). TIME-SERIES MOMENTUM / absolute trend-following… |
| `equity_tsmom_trend_arm.py` | ARM the validated diversified TIME-SERIES MOMENTUM (TSMOM trend-following) strategy as a COSMU paper — register it into the SAME… |
| `equity_vaa.py` | DEPLOY-A-DOCUMENTED-STRATEGY track (NOT the in-sample 0.95 deflated-Sharpe Gate). Wouter Keller & Jan Willem Keuning's VIGILANT A… |
| `equity_vaa_arm.py` | ARM the validated KELLER VIGILANT ASSET ALLOCATION — AGGRESSIVE (VAA-G4) strategy as a COSMU LIVE PAPER — register it into the SA… |
| `event_corpus.py` | the EVENT CORPUS bridge (realtime-data-lane epic §4.3) — turn raw text corpora into the typed, CLUSTERED MarketEvent timeline the… |
| `event_study.py` | the DETERMINISTIC EVENT-STUDY harness (realtime-data-lane epic §4) — measure whether typed unstructured events (news / tweets / P… |
| `event_study_run.py` | the RUNNABLE pre-registered EVENT-STUDY experiment (realtime-data-lane epic §4.3) — one CLI that loads a raw text corpus (JSONL),… |
| `fixtures.py` | deterministic synthetic bars + alt-data so the edge gate runs offline (CLI demo + tests) |
| `funding_crowding_cohort.py` | the Phase-0 funding-as-CROWDING/POSITIONING cohort harness — run the five funding-crowding specs (contrarian crash-filter, reset… |
| `gate.py` | the edge-existence gate — run a small, attempt-capped set of hand-built social-momentum signals through the deterministic wall an… |
| `gkg_corpus.py` | the DEEP raw-text corpus builder for the LLM-narrative axis — pull GDELT GKG (Global Knowledge Graph) RAW 15-min files directly f… |
| `llm_narrative_cohort.py` | the HONEST first-cut Gate harness for the LLM-NARRATIVE axis — score RAW GDELT news headlines with our OWN OpenRouter LLM (conten… |
| `llm_narrative_pipeline.py` | the LLM-NARRATIVE feature factory — turn RAW unstructured news TEXT (GDELT headlines, free + keyless + point-in-time) into ONE ty… |
| `loop.py` | the bounded, cron-able auto-research loop — remove the human from the loop. TWO INDEPENDENT steps per pass: (1) ingest a fresh fr… |
| `matrix_search.py` | the STRATEGY × ASSET × TIMEFRAME survivor-hunt (backlog item P, the #1 search move). Runs EVERY inbox StrategySpec through the ho… |
| `perp_gate_sweep.py` | run the existing gate infrastructure against a matrix of REAL perpetual-futures cost scenarios (venue × funding-regime) and repor… |
| `perp_market_neutral.py` | a runnable CROSS-SECTIONAL LONG/SHORT MARKET-NEUTRAL harness on PERPETUAL futures — the un-exhausted direction the carry verdict… |
| `perp_market_neutral_arm.py` | ARM the cross-sectional LONG/SHORT MARKET-NEUTRAL PERP book (the perp-momentum-neutral lead) as a COSMU paper track — register it… |
| `regime.py` | a NO-REPAINT, stationary-feature market-regime classifier done RIGHT — per the quant critiques the retail "hedge-fund Markov" hyp… |
| `regime_cohort.py` | the HONEST verdict on the regime-detection lever (HANDOFF §8). It asks the only question that matters: does a NO-REPAINT, stride-… |
| `rerun_cohort.py` | the HONEST re-run harness — judge the LOW-TURNOVER btc-social risk-on OVERLAY and the orphaned Polymarket positioning-risk-flip s… |
| `social_nonobvious_cohort.py` | route the THREE non-obvious social specs (social-accel-uncrowded-momentum, galaxy-altitude-drawdown- avoidance, btc-social-contag… |
| `social_norm.py` | turn the RAW LunarCrush social series (social_volume / galaxy_score), whose absolute scale drifts ~160x over 2020-26, into SCALE-… |
| `social_signal_cohort.py` | the Phase-0 SOCIAL-signal cohort harness — run the five LunarCrush social-signal specs (galaxy-score momentum breakout, social-se… |
| `summary_facts.py` | assemble the DETERMINISTIC facts a per-strategy plain-language summary is written from, plus the sha256 staleness pin. inputs: a… |

### `cosmu/snipe/` — the SNIPE LANE — an independent, lean prediction-market conviction-betting path (Polymarket-direct), deliberately separate from t…

_4 module(s) total. Top-level modules:_

| module | summary |
|--------|---------|
| `agent.py` | the snipe-lane AGENT — a framework-agnostic, VISUALIZABLE node graph that turns data + memory + a prompt into ConvictionProposals… |
| `gate.py` | the DETERMINISTIC money envelope for the snipe lane — the "disposes" half of "LLM proposes, deterministic disposes". Given a Conv… |
| `proposal.py` | the typed bet an agent (or human) PROPOSES on a prediction market — the ONLY artifact the snipe-lane agent emits. It carries the… |
| `viz.py` | render the snipe AGENT's node graph (and the lane's end-to-end pipeline) to Mermaid, so the operator can SEE the agent — and, cri… |

### `cosmu/spine/` — Engine spine package.

_5 module(s) total. Top-level modules:_

| module | summary |
|--------|---------|
| `asset_fees.py` | the ONE per-asset / per-category fee model — turn a venue's REAL commission structure (which is NOT a flat bps for Polymarket or… |
| `engine.py` | expose one deterministic facade over backtest, sandbox, and live execution contexts |
| `fee_router.py` | the fee-optimizing VENUE ROUTER — "know where to send". For a base asset, find every venue that lists it, compare effective fees… |
| `universe.py` | read/write the global trading universe — which venues and asset classes are enabled system-wide |
| `venue.py` | describe tradable instruments at actual venues |

### `cosmu/strategy/` — Strategy specification and compiler package.

_16 module(s) total. Top-level modules:_

| module | summary |
|--------|---------|
| `agent_author.py` | persist an AgentSpec as a kind='llm' strategy_version so the LLM model exists end-to-end (and shows in the leaderboard with the `… |
| `agent_decision.py` | the DETERMINISTIC half of "LLM proposes, deterministic disposes" for ONE Decision. Takes a Decision the Mind proposed + its Agent… |
| `agent_executor.py` | the OBSERVE-ONLY executor for LLM strategies. For each kind='llm' strategy, reason over each PRODUCT (symbol × venue) — the Mind… |
| `agent_loop.py` | the reasoning loop for an LLM strategy — turn the Mind's analyst panel into ONE typed Decision per symbol. "LLM proposes": the Mi… |
| `agent_run.py` | the OBSERVE-ONLY LLM-strategy run — one pass, the tick-cron entry point. Reasons every kind='llm' strategy (the Mind panel |
| `agent_spec.py` | the LLM strategy MODEL artifact (kind='llm'). An AgentSpec is a reasoning-loop strategy — the Mind reasons over `sources` per its… |
| `author_agent.py` | the AUTHORING ENTRYPOINT for LLM/agent strategies — the prod front door to open_agent_strategy (which until now was only ever exe… |
| `blocks.py` | decompose a StrategySpec into content-hashed, reusable BUILDING BLOCKS (signal · filter · setup · exit · sizing) so identical log… |
| `compiler.py` | compile StrategySpec into deterministic trusted strategy code |
| `event_router.py` | the single dispatch seam that routes a StrategySpec to the correct backtest by its TYPE discriminator (strategy_kind), so the mas… |
| `event_spec.py` | the first-class ALT-DATA / EVENT strategy TYPE — typed predicates over a MarketEvent and the point-in-time event→bar matcher the… |
| `pine.py` | translate a TradingView Pine Script strategy/indicator into a typed StrategySpec so mined OSS strategies enter the same determini… |
| `pine_samples.py` | a small library of realistic community-style Pine strategies used to exercise + demo the translator |
| `spec.py` | define the typed hypothesis format authored by the lab agent |
| `static_check.py` | reject unsafe or overfit-prone strategy specs/code before execution |
| `taxonomy.py` | derive a strategy's faceted taxonomy (signal-family, asset class, venue, timeframe, edge-type) from its typed spec — NEVER from a… |
<!-- END GENERATED: module-tree -->
