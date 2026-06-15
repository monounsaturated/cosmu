# Local-agent prompts (run these on the Mac / a deps-installed session)

> **Why this file exists.** The cloud review session (2026-06-15) could not run `engine:test` or
> `next build` (Python 3.11, no engine deps installed) and must never touch `.env.local`, Modal,
> Railway, or live keys. Everything below **needs a real verify run** or **local secrets**, so it is
> handed to a local agent. Each task is a **self-contained, copy-paste prompt** — one branch per agent.
> Findings + rationale: `docs/REVIEW_2026-06-15.md`. Invariants: `AGENTS.md`.

---

## 0. One-time local setup (do once, then never again)

```bash
cp .env.example .env.local          # fill the 5 keys at the top (DATABASE_URL, XAI_API_KEY,
                                    #   OPENROUTER_API_KEY, MODAL_TOKEN_ID, MODAL_TOKEN_SECRET)
pnpm install                        # node deps (web + contracts)
pip install -e "apps/engine[dev]"   # pytest + engine deps  (needs Python 3.12 — pyproject requires >=3.12)
pnpm modal:secret                   # push .env.local → Modal secret `cosmu-engine` (re-run when a key changes)
node scripts/setup-hooks.mjs        # arm the pre-push gate (core.hooksPath was UNSET in the cloud clone)
```

**Keys live in 3 places, `.env.local` is the source:** `.env.local` → Railway dashboard → `pnpm modal:secret`.
The web app needs `API_BASE_URL` + `API_SECRET_KEY` (must match the engine) + `NEXT_PUBLIC_API_BASE_URL`.

## 1. The verify gate (run before EVERY push)

```bash
pnpm verify        # naming + contracts-drift + engine:test + typecheck + next build  (the full gate)
pnpm verify:fast   # same minus next build (tight loop for engine-only changes)
# targeted while iterating:  PYTHONPATH=apps/engine python3 -m pytest apps/engine/tests/test_<x>.py -q
```
Push = deploy (Railway + Vercel auto-deploy on push to your branch). **Never** also run `railway up`/`vercel deploy`.
**One branch per agent; never two agents in one working tree** (proven branch-stomping). Heavy/parallel agents
get their own `git worktree`.

---

## 2. PARALLEL TASKS (dispatch one agent per block, each on its own branch)

### TASK A — [HIGH · money-path · opus] Charge real per-venue depth in the screen
**Branch:** `fix/screen-venue-depth`
```
The strategy screen passes per-venue FEES but not per-venue slippage/impact, so every screen falls back to
the global DEFAULT_SLIPPAGE_BPS=5 / DEFAULT_IMPACT_BPS=50 (data/backtest.py:35-36). Thin-book venues
(Polymarket 30/150, Coinbase 8/60, Hyperliquid 6/60) are screened far too cheap → strategies can pass the
Gate on costs they'd never survive live.

Fix: at the two screen call sites, also pass the venue's depth.
- apps/engine/cosmu/lab/finder.py:356 and :421 — calls run_strategy_backtest*(..., fee_bps=venue.taker_fee_bps)
- apps/engine/cosmu/evolution/loop.py:436 and :588 — same pattern
Both call sites already hold the resolved `venue` object (catalog.venue_for(spec.universe.venues)). Add
`slippage_bps=venue.slippage_bps, impact_bps=venue.impact_bps` (or call venue.cost_inputs() and unpack).

This WILL change gate verdicts (intended — it makes the screen honest). Then:
1. Run pytest apps/engine/tests/test_gate_backtest_cost_parity.py and the finder/loop tests; fix fallout.
2. Re-run a small cohort and note which strategies flipped pass→fail (expected for thin-book specs).
3. pnpm verify, commit, push, open PR. Do NOT merge to main yourself.
```

### TASK B — [HIGH · iteration · sonnet] Modal `.map` fan-out for parallel cohort backtests
**Branch:** `feat/modal-sweep-fanout`
```
Today matrix_search.run_sweep is a serial asset×timeframe×spec loop on one core (the "we're too slow").
run_matrix_cell (apps/engine/cosmu/research/matrix_search.py:86) is already self-contained and map-ready.

1. In apps/engine/remote/app.py add (mirror the existing @app.function(**_HEAVY) jobs):

    @app.function(**_HEAVY)
    def matrix_cell(asset: str, timeframe: str) -> dict:
        import dataclasses
        from cosmu.research.matrix_search import run_matrix_cell
        return dataclasses.asdict(run_matrix_cell(asset, timeframe))

    @app.local_entrypoint()
    def sweep(assets: str, timeframes: str = "1d"):
        cells = [(a, tf) for a in assets.split(",") for tf in timeframes.split(",")]
        for r in matrix_cell.starmap(cells):   # TRUE fan-out: N parallel containers
            print(r)

2. Add to root package.json scripts:  "modal:sweep": "modal run apps/engine/remote/app.py::sweep"
3. CAVEAT (remote/app.py:158): only daily bars are baked into the Modal image. A 1d sweep works; for
   intraday, bundle bars to R2 first (COSMU_BARS_SRC) — note this in the script comment.
4. Point the default asset list at the BROAD perp universe + the alt-joined feature space (the unsearched
   ~75 features), NOT the exhausted bar-TA grid — that's where a novel survivor could still live.
5. Smoke-test: `pnpm modal:sweep --assets BTCUSDT,ETHUSDT --timeframes 1d` and confirm verdicts persist.
   pnpm verify, commit, push, PR.
```

### TASK C — [MED · iteration · sonnet] One-command "generate N → backtest N → gate"
**Branch:** `feat/lab-batch`
```
There's no single command for "generate 50 + screen 50"; you stitch strategize → cosmu.lab.inbox →
matrix_search. Build apps/engine/cosmu/lab/batch.py composing EXISTING functions only (no new gate logic):

  python3 -m cosmu.lab.batch --n 50 --theme "funding dispersion" --gate

It should: (1) author N theme-varied specs via lab/strategize (cap now 64), validate each against the real
compiler (scripts/seed_inbox_strategies.py validates the same way — reuse that path), write to
apps/engine/strategies/inbox/, then (2) if --gate, call lab/inbox.scan_inbox(run_cohort=True) once.

ALSO widen theme diversity so 50 don't collapse to ~6 near-dupes the novelty gate rejects:
- apps/engine/cosmu/lab/strategize.py:155 (_THEME_ANGLES — only 8)
- apps/engine/cosmu/lab/author.py:24-94 (_FEATURE_HINTS + only 4 templates) — vary horizon/direction/
  feature-combos per angle so structural distance clears novelty_gate min_distance=0.25 (memory.py:348).

Keep EVERY batch flowing through promote_cohort/run_cohort (the FDR ledger) — never add a path that scores
specs outside the trial ledger (that's the anti-p-hacking brake). pnpm verify, commit, push, PR.
```

### TASK D — [HIGH · budget · sonnet] Make "always show fees + where are we at budget-wise" real
**Branch:** `feat/budget-truth`
```
The /costs dashboard + costs/llm_calls tables + budget caps already exist. Close the gaps:
1. LLM cost is hardcoded $0 (apps/engine/cosmu/costs/writer.py:38,89 _FREE_COST). Add a small
   {model_id: ($/1k_in, $/1k_out)} table for the xAI Grok + paid OpenRouter models; fall back to 0 ONLY
   for model ids ending ":free". Tokens are already estimated (lab/router.py:137). This turns the always-$0
   "AI spend" KPI into a real number.
2. Schedule the live-spend refresh: add `schedule=modal.Cron("0 */6 * * *")` to the @app.function decorator
   on cost_refresh (apps/engine/remote/app.py:130). (This starts a 6h Modal cron — confirm with the operator;
   it's the thing that keeps vendor_actuals fresh.)
3. Fix the infra seed (costs/writer.py:24): drop the phantom "Fly.io" line, ADD Modal (~$0 idle).
4. Record fees-paid into costs as category="trading" rows (sum executions.fee per month/strategy) so the
   Trading tile shows real dollars and opex_vs_alpha includes fees. Add a dated spend series to the /costs
   response so the (currently always-empty) spend chart fills.
5. Web: surface fees at the decision point — apps/web/components/strategy/go-live-modal.tsx already loads
   VenueFeeInfo but renders none of it; show taker_fee_bps + slippage_bps next to the venue dropdown.
Contracts-first for any new API field (edit the Pydantic model → pnpm contracts:generate → consume the
generated type). pnpm verify, commit, push, PR.
```

### TASK E — [HIGH · data · sonnet] Use data + web + xAI tweets in research; close PIT hazards
**Branch:** `feat/research-uses-everything`
```
xAI tweets ARE ingested (twitter_sentiment) but the research bus ignores them, and web search runs once with
a hardcoded query. Make research actually use what we have:
1. apps/engine/cosmu/lab/research.py:gather_context (~:125-135): add a "tweets" line reading the
   already-ingested twitter_sentiment from the store (PIT-honest, $0), and fold it into
   _prior_art_from_context (research.py:152) so the author conditions on it.
2. De-hardcode the Tavily query (research.py:130 "crypto swing strategy edge") → derive from brief/symbol.
3. Add an xai_live research tool: mirror _web_search in lab/tools/research_tools.py:73 but POST
   https://api.x.ai/v1/chat/completions with tools:[{"type":"live_search"}], key server-side from settings;
   register it (research_tools.py:131) and call it from gather_context.
4. Register twitter_sentiment in default_source_registry (data/sources/registry.py:~202) as a store-backed
   AltMetricSource (provider="xai", market_wide, confidence~0.4) — read the STORE, not a live LLM call
   (keep the registry no-LLM per its header). Today registry.query("twitter_sentiment") KeyErrors.
PIT fixes (separate concerns, same branch ok):
5. Quarantine gtrends_search_interest to paper/backfill until profile-source clears revision_safety
   (catalog.py:481 / run.py — it "rescales history" = look-ahead).
6. Disable twitter_influencer_sentiment until its hit-rate store is real (xai_twitter.py:113 stub returns
   0.5 for everyone → it's a byte-identical duplicate of twitter_sentiment inflating the gate's N), OR route
   weighting through mind/authority.py social-authority. (BACKLOG.md:65.)
Also fix the stale doc MASTER_PLAN.md:28 ("xAI ... source not wired" — it IS). pnpm verify, commit, push, PR.
```

### TASK F — [HIGH · web viz · sonnet] The backtest equity curve (makes the web a real review tool)
**Branch:** `feat/web-backtest-equity`
```
/strategy/[id] plots only forward_equity (paper marks, <2 points → empty for almost every strategy) while a
full backtest curve sits unused. GET /explorer/{id} returns ExplorerDetailResponse.equity_curve with GROSS +
NET per point + stats (incl. max_drawdown) + trades.
1. New component apps/web/components/strategy/backtest-equity.tsx: fetch /explorer/{id}, plot gross vs net as
   a two-line overlay (the gap = cost drag = the story) using the existing
   apps/web/components/charts/equity-chart.tsx primitive; add a drawdown band from stats.max_drawdown.
2. Wire it into apps/web/components/strategy/strategy-sheet.tsx (replace/augment the empty PhasedEquity panel).
3. Surface max_drawdown visually in the strategies table (today renders a bare "—",
   components/research/strategies-table.tsx:493) and the strategy sheet.
While here, hide the honest-but-dead panels that read as "broken": Costs empty spend chart, Live "Recent
trades" panel, Live "Max DD" tile, the Strategies "Fees" column (until its field exists), and fix the dead
`cosmu live stop` copy in components/strategy/stage-control.tsx:112 → point to the Live Stop button.
Generated types only (packages/contracts-ts). pnpm verify (incl. next build), commit, push, PR.
```

### TASK G — [MED · correctness · opus] The remaining money-path hardening
**Branch:** `fix/gate-hardening`
```
Apply with targeted pytest green at each step:
1. verdict_log default: apps/engine/cosmu/master/verdict_log.py:44,54 — change data_source default
   "live" → "unknown" (fail-safe; explicit callers already pass "live", the API tests assert on those).
2. LLM-narrative placebo: apps/engine/cosmu/research/llm_narrative_cohort.py:243,291 — loop the
   time-shuffle placebo over ~20 seeds, require candidate DSR > placebo 95th percentile (not a single
   seed-4242 draw). Keep this cohort off the funding path until done.
3. FarmLoop per-symbol trade floor: apply finder.py:62 _MIN_TRADES_PER_SYMBOL in evolution/loop.py
   screening so a pooled 30-trade count can't be 6×5 correlated symbols.
4. research/gate.py purge/embargo: route _run_variant (gate.py:257) through data/backtest.py
   _purged_embargoed_split and use the embargoed _fold_returns (lower priority — this gate never funds).
5. Add a CI test asserting no apps/engine/cosmu/research/*_arm.py writes literal "passed_gates": 1 /
   "holdout_passed": 1 without a computed verdict variable (deploy-lane self-stamp guard).
pnpm verify, commit, push, PR.
```

### TASK H — [LOW · docs · sonnet] Reconcile the stale docs
**Branch:** `docs/reconcile`
```
- MASTER_PLAN.md:5 — funding-carry is NOT "the lucrative track"; it was falsified (DSR 0.429,
  docs/reports/phase0-carry-verdict.md). Re-point the headline to the defensive5 TAA floor + the
  SIM→live ignition wire as the real near-term money path.
- docs/PRODUCT.md — rewrite §0/§2/§4 to match the shipped 7-surface nav (Strategies·Paper·Live·Indexes·
  Costs·Keys·Commands), no Recharts/shadcn, / redirects to /strategies (next.config.ts is the nav truth).
- BACKLOG.md:132-133 — M1 "binding constraint" is half-stale: AssetClass.FX + Instrument
  (product_type/expiry/is_inverse/funding/max_leverage) already exist (core/interfaces.py:14-59); narrow
  M1 to the genuinely-missing strike/option_type/contract_multiplier/session + widening Venue.kind.
- HANDOFF_NEXT.md is self-flagged stale and contradicts START_HERE on survivor count — refresh or retire.
Docs only — no verify needed, but run naming:check. Commit, push, PR.
```

---

## 3. Suggested dispatch order

1. **Solo first (money):** the SIM→live ignition wire (not in this list — it needs the live order path;
   see `docs/REVIEW_2026-06-15.md` §7 and `BACKLOG.md:163-169`). This is the only path to a first dollar.
2. **Then fan out in parallel:** B+C (iteration) ∥ D (budget) ∥ E (data) ∥ F (web) ∥ H (docs) — independent,
   one branch each, background worktree agents.
3. **Careful/serial (opus):** A (venue depth) and G (gate hardening) — they move gate verdicts; run with
   full `pnpm verify` and review the flipped pass/fail set before merging.
4. Orchestrator merges PRs one at a time (`/fan-out` merge train), re-checking mergeability between each.
