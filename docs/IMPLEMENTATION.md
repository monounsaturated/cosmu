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

**Gate-first (decided 2026-06-01): prove the differentiator on free data before building any more product.** Phase 1.5 (single-asset aggregation ablation) is **built and green on the fixture**. The active build is **Phase 1.6 — the cross-asset extension** (the multi-asset thesis: does combining asset classes beat any single one?). Product/UI work stays **deferred until the gate passes** (don't gold-plate a surface for an unproven edge).

1. **Phase 1.6 — the cross-asset extension** (`docs/BUILD_BRIEF.md`, active unit). Add free **equities** (daily bars + FRED) and **prediction-market odds** (Polymarket public API) behind the existing seams + cross-asset features → a **fourth arm** on the built ablation: cross-asset+alt vs single-asset price-only vs single-asset+alt vs buy-and-hold, with per-asset-class drop-one. **Execution + paid vendors deferred** (two-plane split, PLAN §2). **Nothing below matters until cross-asset+alt beats the single-asset baseline.**
2. *(after PASS)* **Split into the three engines + the six real routes**, collapsible icon sidebar, 2-click Live modal.
3. *(after PASS)* **Pine inbox folder.**
4. *(after PASS)* **Dashboard redesign**: real charts (Tremor/Recharts), plain language, mobile pass.
5. *(after PASS)* **Settings page** for the operator knobs.
6. *(after PASS)* agentic research tools + ML survival model + pgvector RAG.
