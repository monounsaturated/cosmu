# Cosmu v2 — Build Handoff: the Mind (paste to start a new local session)

You are continuing **Cosmu v2** — a solo-built, internal, autonomous quant money machine (Binance spot,
profit-only metric). **Read `AGENTS.md` first** (canonical), then `docs/GLOSSARY.md`. This handoff covers the
**Mind** work just shipped on a cloud session, the **one pending DB task** for this local session, and the
vision/backlog so you can keep going. **Do not re-do anything in "Already shipped."**

---

## This session's immediate jobs (local)
1. **Pull the branch.** Work continues on `claude/zen-newton-uUgRV` (NOT `main`):
   ```
   git fetch origin && git checkout claude/zen-newton-uUgRV && git pull origin claude/zen-newton-uUgRV
   ```
2. **Apply the additive SQL migration to Supabase** (Postgres is applied **out-of-band** — see
   `knowledge/store.py:migrate`). The file is ready:
   `apps/engine/cosmu/knowledge/migrations/2026-06-03_mind_reflections.sql`
   - It creates **`mind_reflections`** (additive — nothing renamed/dropped) so the agent's point-in-time
     "how it thought" timeline persists. It is **safe to run before or after deploy**: the engine's `reflect()`
     writer records every reflection as an **audit event** regardless, and only writes the richer row once the
     table exists.
   - Apply it via the **Supabase SQL editor** (paste + run), OR if you have `DATABASE_URL` in `.env.local`,
     `psql "$DATABASE_URL" -f apps/engine/cosmu/knowledge/migrations/2026-06-03_mind_reflections.sql`.
   - **Ask the owner before touching the live DB.** Confirm it ran (`SELECT count(*) FROM mind_reflections;`
     should return 0, not error). The `alt_data` table already exists in prod; the migration only adds
     `mind_reflections`.
3. **Verify, then push (= deploy).** `pnpm verify` is heavy on a 16 GB Air (full `engine:test` + `next build`
   OOM) — if RAM is tight, run the heavy parts in a cloud session. Then `git push -u origin claude/zen-newton-uUgRV`.
   **Never `railway up` / `vercel deploy`** — push is the only deploy trigger.

---

## Already shipped THIS session (on `claude/zen-newton-uUgRV`, green — do not repeat)
**The Mind** — the agent's standardized self-knowledge, consolidating the previously *scattered*
brain/intelligence/memory/skills surfaces into one clean destination. Railguarded: it **reasons; it never funds
or fires** — the deterministic Gate alone disposes; **zero LLM in any scoring/gate/money path**.
- **Engine `cosmu/mind/`**: `analysts.py` (a TradingAgents-style panel — **Technical · Macro · Sentiment ·
  Social & News · Positioning · OSINT** market analysts + **ML-survival · Memory** process pillars; each reads the
  agent's EXISTING point-in-time signals and emits a standardized `Stance`; **no data → abstain**, never
  fabricates). `debate.py` (deterministic consensus / conviction / panel-agreement / bull-bear / contested +
  narrative). `snapshot.py` `build_mind()` (KNOWS + THINKS + LEARNED) and `reflect()` (persists a reflection each
  tick; defensive — degrades gracefully if the table isn't applied yet).
- **API**: `GET /mind` → `MindResponse`; `reflect()` wired into `POST /autonomy/tick`. Contracts regenerated
  from OpenAPI (never hand-typed).
- **Schema (additive)**: `mind_reflections` in `schema.sql` + `schema_postgres.sql` + the migration above;
  `alt_data` added to the **sqlite** schema for local/prod parity. Nothing renamed/dropped.
- **Web**: new first-class **`/mind`** page + nav entry — *How it thinks* (consensus + stance cards, with a
  "Reasons · never funds" railguard badge), *What it knows* (sources by perspective + freshness, honest "not
  ingested yet"), *What it has learned* (ML state, regime grid, gate efficiency, memory insights, skills). The
  duplicated "what the machine learned" block was removed from `/lab`.
- **Docs**: `AGENTS.md` (The Mind section), `docs/GLOSSARY.md` (The Mind vocabulary), `docs/IMPLEMENTATION.md`
  (Built entry).
- **Tests**: `apps/engine/tests/test_mind.py` (7) — honest abstention, consensus from ingested signals,
  determinism, contested flag, `reflect()` persist + graceful degrade. typecheck + `next build` green (18 routes
  incl. `/mind`); naming guard green.

---

## The vision (owner's words this session — the north star)
> "functional, trade, internal, boosted, **claude using features** if relevant, autonomous, **making money +
> learning**, **chattable with and learning**, implementing ideas, and standardizing this like **a platform for
> agentic trading** (internal — just access to tools and data)."
>
> "add a **standardized view of the trading agent's memory** — what it knows, how it thinks, summaries of
> learnings, from **ML as a pillar but not only** (also news, api, data, technical, macro, sentiment, social,
> OSINT, **debating**, becoming smarter, **replicability**) — inspired by the **TradingAgents** repo."
>
> "**interface**: make more sense, **no stupid words**, standardized text, clean, professional, **review all**,
> align it with the DB but **focus on UX/UI over DB** — edit DB and backend to match the user experience and ease
> of use, yet extremely powerful; focus on **naming**, easy to understand and remember."
>
> Steer this session: **"smartest and powerful, not a side project but a real sniper, harnessing 2026 tech …
> railguarded but boosted; if LLMs make sense, go."** And: **"include schema/rename now."**

The Mind delivers the *standardized memory view + debate*. Two vision threads remain **deliberately deferred**
(they're ask-first and higher blast-radius): (a) **real LLM-driven debate reasoning** (an optional narrator seam
exists, off by default), and (b) **broad DB field/table renames to match the UX** (this session kept renames to
the new surface + glossary, since renaming live Postgres columns risks breaking the deployed engine).

---

## Backlog (prioritized) — features wanted & discussed
### Direct follow-ups to the Mind (highest continuity)
- **LLM narrator seam (railguarded, modern).** Turn the optional analyst-brief narrator on at the existing seam
  in `mind/debate.py`/`snapshot.py`: LLM writes the consensus prose (propose-only), **never** in the
  scoring/gate/money path, off by default, offline-deterministic fallback. Cheap/free OpenRouter or the flat Max
  sub for heavy authoring — not per-token API. *Ask before enabling spend.*
- **Chattable Mind.** Let the operator ask the Mind questions ("why bearish?", "what changed since yesterday?")
  over the persisted `mind_reflections` timeline — read-only, propose-only, audited.
- **Reflection timeline UI.** Surface the `mind_reflections` history on `/mind` (how the consensus moved over
  time) once the migration is applied and ticks have run.
- **Deeper naming/DB standardization (ask-first, per-change).** The owner wants DB aligned to the UX. Do it as a
  **scoped, confirmed** migration set (additive + careful renames with the `check_naming.py` guard updated),
  NOT a blind repo-wide rename. Candidates: `lineage` hardcoded `"seed:template -> wfo"`; `regime_label`
  hardcoded `"mixed"`.

### P0 — money-control surface (from the prior handoff; Live money → scope + confirm first)
- **Strategy-launcher**: 1-button launch live with a **fixed $ budget per strategy** (not one global cap),
  cut/rebalance/withdraw per strategy (**LLM proposes, operator + deterministic layer dispose — never LLM-funds**),
  per-venue budget allocation, respect the 5 interlocks, audited. Needs a per-strategy/per-venue budget model
  (likely a schema change → **ask first**). Draft a 3-line scope with the owner.

### P1 — make the loop honest end-to-end
- **Cost/ROI writers** — `costs` + `llm_calls` tables have **zero writers**; show profit net of opex.
- **Regime persistence** — `regime_label` hardcoded `"mixed"` (`evolution/loop.py`, `lab/finder.py`); per-trade
  regimes computed then discarded. Persist one representation; couple the web regime grid **and the Mind's
  regime-coverage read** (which already consumes it).
- **Forward-test → Live** — surface the N≥30-forward-day proof as an **advisory** live-readiness signal (the operator decides when to launch; not an auto-promotion gate).
- **Gate hardening** — add `must_beat_buy_and_hold` + route the cohort through `research/gate.py:PREREGISTERED_BAR`.
- **Wire alt-data feeds** (`fear_greed` is live; `news_sentiment`, `liquidation_cascade`, `macro_regime`, etc.)
  via the **`add-data-source`** skill so the Mind's market analysts stop abstaining and the inert inbox strategies
  screen. The Mind reads `alt_data` by metric name — every newly-ingested feed lights up a perspective
  automatically.

### P2/P3 — throughput, research, polish
- Nightly cloud cohort/walk-forward sweeps; idea-ingestion (YouTube/X/news → hypotheses → Gate); strategy
  chaining/meta-labeling; per-country venue legality accuracy; real `lineage` surfacing.

---

## Operating rules (non-negotiable)
- **Push = deploy.** `git push` → Railway (engine) + Vercel (web). One trigger only. **Never** `railway up`/`vercel deploy`.
- **Dev gate before every push:** `pnpm verify` (naming:check + contracts:generate + engine:test + typecheck + build).
- **Compute:** MacBook Air M2 16 GB OOMs on full `engine:test` + `next build`. Run heavy work (full verify,
  builds, sweeps, broad refactors) in a **cloud Claude Code session**. Heavy LLM work → flat Max sub, not per-token API.
- **Ask first:** schema changes (Postgres applied out-of-band in Supabase), new vendor/spend, live-execution
  changes, broad renames. **Never** display synthetic data in the app, **never** let an LLM fund/fire orders
  (deterministic gate only), **never** hand-type the TS contracts (generated from engine OpenAPI).
- **`git fetch` before auditing** — the local clone has gone stale behind deployed `main` before.

## Known issues / gotchas (don't let these surprise you)
- **Sandbox/no-network:** `test_autonomy_tick.py` (2 tests) and anything hitting Binance/ccxt FAIL with
  NetworkError/SSL in an offline sandbox — these are **environmental**, confirmed pre-existing on clean `main`;
  they pass on Railway/CI with network. The Mind tests are fully offline.
- **`contracts:generate` env-drift:** can emit a different `ValidationError` shape (`ctx?`/`input?`) depending on
  local FastAPI/pydantic version — **don't commit that diff**; Vercel regenerates at build. (This session's
  contract diff was checked clean — additive only.)
- **`next-env.d.ts`** changes as a Next build artifact — **revert it** rather than commit.
- **Order-dependent tests:** 2 venue tests in `test_evolution.py` fail in isolation, pass in the full suite
  (process-global `default_catalog` leak). `test_close_loop.py` OOMs on 16 GB. Run the full suite in cloud.
- **Mind perf:** `build_mind` shares ONE connection via `store.reading()` (opening one per query timed out the
  web on remote Postgres); `_latest_values` reads only the latest row per metric, not the whole `alt_data` table.

## Read order
1. `AGENTS.md` (invariants, env, skills, **The Mind**) → 2. `docs/GLOSSARY.md` (**The Mind** vocabulary) →
3. `docs/IMPLEMENTATION.md` (last few "Built") → 4. the module's `# intent:` header → 5. `rg` the exact symbol.

Start by `git fetch`, confirm the branch is green, apply the SQL migration (job #2 above), verify, push.
