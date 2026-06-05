# COSMU — Next-Session Handoff (2026-06-05, main @ 24c9c1a)

> Complete, ordered work plan from two verified deep-reviews (integrity + product/architecture).
> The HUMAN dispatches the prompts; AGENTS open PRs (never merge); the HUMAN merges in order.
> One branch = disjoint files. Push `--no-verify` (heavy verify is CI). Repo stays PRIVATE (decided).

---

## 0. WHAT COSMU IS
A private, single-operator cockpit for an **autonomous crypto trading research machine** (Binance
spot). You drop a vibe in plain language → the machine authors a typed `StrategySpec` → backtests on
point-in-time data → a deterministic, **LLM-free Gate** (Deflated/Probabilistic Sharpe + CSCV-PBO +
holdout + regime folds + BH-FDR + buy-and-hold) renders stop-or-go → survivors forward-test → human
arms live, small. LLM proposes; Gate disposes; **LLM never touches money.** North star: profit net of
fees. The product's proof isn't "it made money" — it's that **the falsification loop visibly works.**
Engine `apps/engine` (pure-Python), web `apps/web` (Next.js), Railway+Vercel+Supabase+Modal, push=deploy.

## 1. CURRENT STATE
- main @ 24c9c1a, 0 open PRs, prod healthy. Cost ≈ $120/mo (Claude ~70%). Repo PRIVATE (GH Actions ~$6/mo accepted).
- **0 real edges.** 7 theses falsified WITH power (carry, funding-crowding, xsec-momentum, meta-label,
  social, cross-market, social-lead-lag) — the gate working. Verdicts in `docs/reports/phase0-*.md`.
- Engineering: A. Honesty: A+. Alpha: not yet.

---

## THE PLAN — 5 finite waves. Finish a wave before the next ONLY where noted.

### WAVE 0 — INTEGRITY (do first; a "PASS" is worthless until these land)
Money-path fixes must be trustworthy before autonomy runs or any POC is believed.
**Order: fix-1 then fix-2 (shared scorer.py/backtest.py). fix-3/4/5 parallel, disjoint.**

**fix-1 — FarmLoop global deflation** · opus · `fix/farmloop-global-deflation` · RUN FIRST
> P0 money-path. `cosmu/evolution/loop.py:331` calls `score()` with NO `trials=` → deflates each
> candidate vs only ~7 params; BH-FDR is cohort-local. Violates "deflate vs every hypothesis ever run."
> Thread the global ledger mirroring `cosmu/lab/finder.py` (finder.py:287,335,435; contract in
> master/cohort.py:42-68): split run_cohort → (1) screen all + `register_trial(...)` each
> (source="farmloop"), snapshot ledger once; (2) `combined=trial_stats(store)` then
> `score(metrics, settings.gates, trials=combined)`, persist that deflated_sharpe. Update only the
> cohort.py:60 docstring. Tests: 2 sequential cohorts deflate the 2nd vs 1st; trials rowcount==screened.
> Do NOT edit scorer/backtest logic (fix-2 owns them). pnpm verify + /deploy-check. PR, don't merge.

**fix-2 — buy-and-hold gate** · opus · `fix/gate-beat-buy-and-hold` · AFTER fix-1
> P1 money-path. Deployed promotion has no BnH check → a bull-regime momentum can beat DSR/PBO/holdout/FDR
> yet underperform BTC and get funded. Port `research/gate.py:35,135-136`: (1) backtest.py ~80-181 compute
> validation-slice BnH NET return (reuse gate.py:379-393 `_buy_and_hold` on bars[:split], NEVER holdout),
> surface on BacktestMetrics; (2) scorer.py:20 add `buy_and_hold_return: Decimal`; (3) scorer.py:188-203
> add `if gates.require_beat_buy_and_hold and metrics.oos_return <= metrics.buy_and_hold_return:
> reasons.append("buy_and_hold")`; (4) settings.py:28 `require_beat_buy_and_hold: bool=True`; (5)
> orchestrator/loop.py:51 add `AND b.holdout_passed=1`. Tests + regenerate contracts if exposed. PR, don't merge.

**fix-3 — remove synthetic display leak** · sonnet · `fix/no-synthetic-seed` · PARALLEL
> P2 display. `spine/engine.py:158` fakes sharpe≈1.35, seeded on boot (app.py:217); fails gate (can't reach
> money) but shows fake numbers + hardcoded "WFO accepted/holdout passed" (app.py:638-639) on
> /leaderboard + /strategies. Remove boot seed (KEEP `EngineFacade.create` — seed_catalog is real),
> remove POST /spine/backtest + dead synthetic code in spine/engine.py (grep refs first), drop the
> hardcoded notes/holdout → honest empty. Net-negative diff. PR, don't merge.

**fix-4 — LunarCrush cache/cost safety** · sonnet · `fix/lunarcrush-cache-safety` · PARALLEL
> P2 cost. Ingest re-spends API + double-writes on re-run (pipeline.py:99 raw `append`, no incremental).
> (1) use `append_dedup`; read max ts → pass `since`. (2) altdata.py LunarCrushProvider.fetch_series: add
> `since` → `start=<epoch>` on v4 URL. (3) schema.sql UNIQUE INDEX on (provider,symbol,metric,ts) + ON
> CONFLICT DO NOTHING. (4) research_tools.py ~104 _social: serve from store if <25h fresh before API.
> Tests: re-run writes 0; since forwarded; store hit avoids API. (One-time row dedup may precede the index.)
> **UNTIL THIS MERGES: do NOT re-run LunarCrush ingest.** PR, don't merge.

**fix-5 — docs vendor-reality** · sonnet · `docs/reconcile-vendor-reality` · PARALLEL
> <40-line annotate. WIRED: ccxt, XGBoost/LightGBM, Modal, FastAPI, SQLAlchemy, pgvector(hash embeddings).
> NOT WIRED (mark aspirational): NautilusTrader, vectorbt, Optuna, Deepgram/ElevenLabs, E2B. Edit
> VISION.md~290, IMPLEMENTATION.md:211, BUILD_PLAN.md~67-89 (Status col), PLAN.md~254-257,
> schema_postgres.sql:195 comment. PR, don't merge.

### WAVE 1 — DE-COLLIDE THE GOD-FILES (ends the merge pain we kept hitting)
4 files cause ~all collisions: app.py(42 touches), models.py(32), page.tsx(30), data.ts(23).
**Land R1 first (rewrites app.py; collides with fix-3 → do AFTER fix-3 merges). Then R2/R3/R4 parallel.**

**R1 — split api/app.py into routers** · opus · `refactor/api-routers`
> Convert `cosmu/api/app.py` (1876 lines, 52 routes) → `cosmu/api/routers/*.py` (one APIRouter per
> prefix: health, spine, evolution, population, strategy, lab, overview, leaderboard, strategies, console,
> recommendations, autonomy, live, universe, research, mind, scores, settings, drift, skills, memory,
> costs, events, intelligence, verdicts). Each router carries only its routes + private helpers it uses
> (shared → api/_shared.py). app.py → app construction + CORS + lifespan + include_router (<120 lines).
> Each router imports only the models it uses (kills the 107-line import block app.py:17-123). Keep
> `from cosmu.api.app import app` working. ZERO behavior change; OpenAPI schema set identical. Verify:
> pytest + generate_contracts + `git diff --stat openapi.json`. `# intent:` header per AGENTS.md:132. PR.

**R2 — split models.py by section** · sonnet · `refactor/api-models-pkg` · AFTER R1
> `cosmu/api/models.py` (1193 lines, 123 classes, already `# ----` sectioned) → `models/` package, one
> module per section, re-export ALL from `models/__init__.py` so `from cosmu.api.models import X` is
> unchanged. No renames/field changes. Verify pytest + contracts identical. PR.

**R3 — modularize web data.ts** · sonnet · `refactor/web-data-fetchers` · PARALLEL (engine-independent)
> `apps/web/app/data.ts` (481 lines, ~22 getX) → `app/data/` (client.ts + one file per domain),
> barrel `data/index.ts` so `import {getX} from "@/app/data"` keeps working. No behavior change.
> Verify `pnpm --filter web build`. PR.

**R4 — split altdata.py by provider** · sonnet · `refactor/data-providers-split` · PARALLEL
> `cosmu/data/altdata.py` (1468 lines, ~15 providers) → `data/providers/` (lunarcrush, reddit,
> funding_binance/okx/kraken, news, store.py, _types.py). Re-export from altdata.py so imports unchanged
> (sources/registry.py:18). Makes "add a venue source" a NEW FILE. Verify pytest. PR.
> AFTER all land: add to AGENTS.md — add endpoint→routers/, add model→models/, add source→providers/+1 registry line, add surface→app/data/.

### WAVE 2 — MAKE THE CORE PROMISE VISIBLE (parallel; the vibe loop is invisible today)
**P1 — close the vibe loop on Overview** · sonnet · `web/vibe-loop-overview` · apps/web only
> The loop DIES at "queued": `getInboxQueue()` (data.ts:253) has ZERO callers; `components/overview/
> idea-inbox.tsx` (renders per-item status) is ORPHANED; no web code calls `POST /lab/author`. Engine
> fully supports it — just connect the pipes. Replace `idea-dump-box` with `idea-inbox.tsx`; server-fetch
> `getInboxQueue()` in page.tsx, pass as initial. Add "Preview typed spec" → POST /lab/author
> (AuthorResponse) rendering named features+fitted params read-only. Link `imported` items → /strategies
> (and /strategy/[id] when version_id exists). Honest empty/offline states; additive only. pnpm verify. PR.

**P2 — fix nav surface map** · sonnet · `web/nav-surface-map` · apps/web only
> app-nav.tsx:27-30 ships Overview·Strategies·Costs·Console — **Mind is missing** (only linked from
> orphaned widgets) and Lab has no primary path. Add Mind (/mind, Brain icon) + a path to Lab (/lab);
> strategy-stages.tsx:16 repoint dead `/forward-test` → /strategies status facet. Keep desktop rail +
> mobile tabs + More drawer, ≤5 surfaces. KEEP all redirect stubs (/farm,/paper,/research,/scores,/steer).
> **DECISION: do NOT build a "Stack & Tools" links section** (bookmarks don't help decide/earn). pnpm verify. PR.

### WAVE 3 — LEAN THE TREE + SURFACE THE MOAT (parallel; after R1 so router files are stable)
- **C1** `chore/delete-research-cohorts` · sonnet · delete falsified one-shot harnesses
  `cosmu/research/{carry_ablation,perp_gate_sweep,social_signal_cohort,funding_crowding_cohort,
  social_nonobvious_cohort,social_norm,attribution}.py` (~-2200 LOC). KEEP gate.py, loop.py,
  cost_surface.py, fixtures.py. Verdicts already preserved in docs/reports + /verdicts.
- **C2** `chore/delete-unconnected-adapters` · sonnet · delete `adapters/data/{ibkr,okx,kraken_futures}.py`
  + `master/neutral.py` + `ml/metalabel.py` + test_neutral_marking.py (~-580 LOC; carry/meta falsified).
- **C3** `chore/prune-registry-orphans` · sonnet · set `enabled=False` (don't delete names) on registry
  orphans: cftc_net_positioning, short_interest_ratio, insider_buy_ratio, days_to_earnings,
  xasset_risk_appetite, authority_weighted_claim_signal, author_authority, reg_risk_crypto, risk_on_off, pm_prob_velocity.
- **A1** `feat/lab-coverage-and-graveyard` · opus · expose GET /ingest/coverage; add Data-Freshness strip +
  Graveyard summary above the inbox; move "the deterministic Gate alone decides" to the hero. The moat = the falsification record; make it the hero, not a buried widget.
- **D1** `web/overview-intake-dedupe` · sonnet · AFTER P1 · one intake, remove orphaned widgets, net-negative.

### WAVE 4 — EARN THE EDGE (the only open-ended stretch — and the right one to be)
1. **Close the 7→45 feature-wiring gap** — only ~7 of ~45 registry features reach the backtest; the Gate
   is SOTA but starved. THIS is the binding constraint on finding an edge, not more surface. (Continue
   the fix-4-adjacent wiring; PR #104 wired pm_risk_on + liquidation_cascade — keep going.)
2. **Run wider FarmLoop sweeps on the richer data** through the now-trustworthy gate (post fix-1/fix-2).
3. **Pull the one untested lever** — derivatives / cross-sectional funding-dispersion / funding-contrarian
   on perps (`DERIVATIVES_PLAN.md`; perp harness bugs fixed in #103). Spot-only is the binding limit.
   Also re-attack PR #105's REAL social lead-lag signal that died on *costs* (lower-fee venue / longer holds).
4. **On the first 30-day forward-test survivor:** complete the `adapter="nautilus.binance"` execution
   path (BUY NautilusTrader — MIT, slots behind the typed ExecutionAdapter), arm live small via /console.

---

## BUY / BUILD / KEEP
| Capability | Decision | Why |
|---|---|---|
| Backtest engine | KEEP-CUSTOM | PIT fees/embargo/CSCV-PBO/regimes; vectorbt only if sweeps >10k/run (cohorts are O(10-100)) |
| Data ingest | KEEP | thin urllib; bottleneck is data quality not harness |
| Experiment tracking | KEEP-CUSTOM | MLflow NO-GO; registry ~80 LOC, carries data_version+code_hash |
| Param opt (Optuna) | NO-BUY | Gate caps attempts to prevent p-hacking; a Bayesian optimizer fights it |
| Vector memory | KEEP-CUSTOM | deterministic FNV TF-IDF = keyless + reproducible |
| Monitoring (Slack) | KEEP | one cron; buy observability only at multi-strategy scale |
| **Execution adapter** | **BUY NautilusTrader WHEN-LIVE** | trigger = first 30-day forward survivor; MIT, slots behind typed ExecutionAdapter; raw ccxt order loop is a maintenance sink |
No second buy is warranted now — the bottleneck is data coverage + feature wiring, not infra.

## HUMAN CHECKLIST (only you)
- [ ] Dispatch Wave 0 (fix-1→fix-2; fix-3/4/5 parallel) → merge each green PR.
- [ ] Then Wave 1 (R1 → R2/R3/R4 parallel). Then Waves 2/3 (mostly parallel). Then Wave 4 (the edge).
- [ ] Do NOT enable `AUTONOMY_CRON_ENABLED` (Railway) until fix-1+fix-2 merge (else autonomy funds on a leaky gate).
- [ ] Do NOT re-run LunarCrush ingest until fix-4 merges (re-spends $5/day). Buy a fresh $5 day before any new ingest.
- [ ] Repo stays PRIVATE. GH Actions ~$6/mo accepted.
- [ ] POC target: ONE strategy survives the HONEST gate (post fix-1/2) AND survives 30-day forward-test (SIM). That is "it works."

## THE HONEST FRAME
The expensive part is done: an honest machine + 7 powered falsifications. The rest is FINITE — fix
integrity → de-collide the god-files → make the vibe loop visible → lean the tree → then the open-ended
hunt for an edge through a now-trustworthy gate, with feature-wiring (7→45) as the real lever. Don't
polish UI or widen the funnel as a substitute for finding an edge. The moat is the honest Gate + PIT
discipline + the falsification record — make that the hero.

> Deeper raw reviews (this session) are in the workflow transcripts if needed; everything actionable is above.
