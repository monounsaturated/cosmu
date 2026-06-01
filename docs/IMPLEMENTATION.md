# Cosmu v2 — Implementation Log

> Tracks what is actually built and the decisions taken, so `VISION.md` (contract) and `BUILD_PLAN.md` (how) stay honest. When code and the big docs diverge, reconcile here on purpose.

## Built

### Spine & control plane
- `spine/engine.py` — deterministic facade (`run_backtest`/`run_sandbox`/`run_live`), `VenueCatalog`, fill-log, seeded determinism. Live blocked unless the global toggle is on.
- `knowledge/store.py` — SQLite/Postgres-ready store. **Batched writes:** `Store.batch()` yields one connection + one transaction for a whole cohort (400 candidates persist in ~0.15s vs thousands of connections before). WAL + `synchronous=NORMAL`.
- `master/scorer.py` + `master/risk.py` — deterministic scorer (deflated Sharpe, PBO, gates) and risk gauntlet. **Out of the agent's reach.**

### Autonomous evolution loop (`evolution/`) — the differentiator
- `loop.py` `FarmLoop.run_cohort(...)` — generates a wide population (seeds + chat briefs + Pine imports → exploit mutations + explore wildcards), compiles + static-checks each, runs a cheap deterministic screen, scores through the out-of-reach scorer, keeps gate-passers as `$100k` paper sleeves, sends the rest to the graveyard **with kill reasons**. Seeded/reproducible. Measured **90–97% kill rate** (matches §8 DoD).
- `mutator.py` — §F operator catalog (`swap_feature`, `widen/narrow_param`, `tighten/loosen_risk`, `change_horizon`, `add_condition`, `crossover`) + wildcard generators. Two lanes (exploit single-operator for clean attribution; explore unrestricted).
- `seeder.py` — diverse seed templates (breakout, mean-reversion, carry, momentum) so the population never starts collapsed.

### Pine Script import
- `strategy/pine.py` `translate_pine(source)` — TradingView Pine → typed `StrategySpec`. Maps `ta.*` to the feature registry; resolves `input.*` vars, tuple destructuring (`[macd, signal, _] = ta.macd(...)`), and band breakouts (`close > upper` → `bb_z`). **Key invariant:** Pine's hardcoded thresholds/lengths are **lifted into a fitted `param_space`** — magic numbers become a search space, never baked in.
- `strategy/pine_samples.py` — community-style sample library (RSI, MACD, golden cross, Bollinger, ADX); every sample is asserted to translate + compile in tests.

### Chat strategy authoring (`lab/author.py`)
- `draft_from_brief(brief, features?, venues?)` — plain-language brief → validated `StrategySpec` draft. Picks a base template by intent, retargets universe/horizon/risk, detects/accepts features, derives **data sources** from the feature registry. **Guardrails:** structure-only (thresholds stay in `param_space`), money-adjacent intent flagged for approval, scorer never in this path. LLM-optional: deterministic template-match today; an OpenRouter call slots into the same seam when a key is set.

### API & frontend
- New endpoints: `POST /evolution/run`, `GET /population`, `POST /strategy/pine`, `GET /strategy/pine/samples`, `POST /lab/author`, `POST /lab/author/run`. TS contracts regenerated from OpenAPI (no hand-typing).
- Web (`apps/web`, Next 16 + Tailwind v4 + shadcn-style "Obsidian Iris" theme): Dashboard, **Farm** (run cohorts, watch the funnel, graveyard, Pine import + sample picker + file upload), Leaderboard, Strategy detail, and a **chat authoring Console** (brief → draft → send to farm). Graceful offline-demo fallback throughout.

## Decisions

- **Pine import = paste / file upload / bulk, not TV link.** TradingView doesn't expose script source over a public URL (closed-source scripts; scraping violates ToS). Paste + `.pine`/`.txt` upload + the sample library is the robust path. A CSV/bulk-paste of `{name, source}` is the multi-import seam.
- **LLM-optional by default.** Authoring + generation run deterministically without any model key, so the machine is fully functional offline; the model router is an enhancement at a single seam, never a hard dependency. Keeps the scorer/money partition intact regardless.
- **Cohort screen is a deterministic surrogate** standing in for the vectorbt/Nautilus two-tier backtest (those are BUY/BORROW vendors). The architecture (cheap screen → full validate) mirrors the plan so wiring the real vendors is a swap, not a rewrite. The scorer/gates are already the real, authoritative deterministic layer.
- **External coding agents (Claude Code / Cursor) author by writing typed specs**, not by a bespoke bridge: a spec is JSON validated by `static_check` + `instructor`/Pydantic. The in-product path is the Console; both funnel into the same farm under the same guardrails.

## Not yet wired (vendor swaps, same seams)
NautilusTrader event-driven validation · vectorbt fast screen · Optuna param fitting · OpenRouter model router + `instructor` · ccxt/Databento data ingestion · Supabase Postgres/pgvector in prod.
