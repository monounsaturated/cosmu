# COSMU — MASTER HANDOFF (local orchestrator) · updated 2026-06-07

> Paste-ready context for a fresh **local** master session on `main`. Pair with `docs/DECISIONS.md` (verdict log),
> `docs/OPEN_THREADS.md` (registry), `docs/STRATEGIES.md` (what's tested). You are the LOCAL orchestrator on the Mac.

## 1. WHAT COSMU IS (+ inviolable rules)
Autonomous trading research machine. LLM proposes typed `StrategySpec`s; a **deterministic Gate** disposes — deflated-Sharpe ≥ 0.95 · CSCV-PBO · BH-FDR (q=0.10) · **purged+embargoed OOS holdout** · beat-buy&hold, **net of REAL fees**. **THE LLM NEVER TOUCHES MONEY. NEVER tune the Gate to pass. No synthetic/zero-fill/look-ahead. An honest FAIL is valid.** North star: profit net of fees.

## 2. WHERE WE ARE (honest)
- **Search phase DONE.** Crypto (5 waves / ~16 spaces) + equity *factor* search are honestly exhausted — 0 novel survivors, ALL audited, the machine has **0 false positives and audited itself**. That trustworthy machine is the durable asset.
- **THE REFRAME (the unlock):** the 0.95 Gate is a *novel-exceptional-edge* detector. Making money needs **positive + robust**, not exceptional. → **TWO LANES:**
  - **DEPLOY-LANE** — documented, externally-validated strategies (TAA). Bar = positive OOS net-of-fees + beat B&H risk-adjusted + the REAL holdout → **ARM forward-test.** (NOT the 0.95 Gate — that's an overfitting guard for *mined* edges.)
  - **GATE-LANE** — novel / mined / popular-pinescript → the 0.95 `promote_cohort` BH-FDR Gate.
- **LIVE NOW:** **9 strategies forward-testing in Simulation** (all honest **0% forward**, $10k SIM each) — 8 documented-TAA (GEM, Faber GTAA, ADM, Risk Parity, Keller VAA, TSMOM, Sector-Mom, Dual-Mom-QQQ) + 1 gate-survivor (Donchian, caveated/short-window). Marking daily via the asset-aware clock. **The floor is real.**

## 3. THE TWO TRACKS (the plan — no more circling)
- **TRACK 1 · FLOOR:** deploy documented-robust strategies live (GEM + fleet) → modest-but-real compounding (~0.6-0.8 Sharpe, crash protection). Iterate: more TAA models, **variations of winners (FDR-counted)**, pinescript imports (honestly gated).
- **TRACK 2 · UPSIDE:** LLM-narrative. **Corpus DONE** — 115,006 GKG news items, 10 assets (BTC/ETH + AAPL/MSFT/GOOGL/AMZN/META/NVDA/TSLA/QQQ), span **2023-01→2026-06**, on the Modal volume (built via `apps/engine/remote/gkg_narrative.py`, in worktree `agent-add72795`). **Score+verdict running on Modal** (LLM-score content-only + cached → `research/llm_narrative_cohort` gate, real holdout + shuffle-placebo) → **verdict PENDING.** *Fresh session: check the Modal `cosmu-gkg-narrative` app + worktree `agent-af43d48`; if the score stalled, re-run the score+verdict stage. The question: does narrative carry a Gate-clearing edge on deep data?*

## 4. MONITOR LIVE STRATEGIES (do this — "monitor heavy")
- **Watch:** `GET /leaderboard` (Strategies page) + `GET /overview` — `forward_age_days`, `live_ready` (crosses True at +31d), `return_pct`.
- ✅ **The forward-mark clock is now ASSET-AWARE** (`cosmu.orchestrator.loop` / `mark_tracks` → `PricingRouter`: crypto→Binance, equity→Yahoo total-return). Marks all 9 tracks (973 tests green). Run `python3 -m cosmu.orchestrator.loop`.
- **ACTION: deploy the daily Railway cron** (already in `apps/engine/railway.toml`, `10 22 * * *` after US close) so the floor accrues hands-off. The leaderboard now serves `forward_return_pct` (real marked forward, null at day-0) distinct from backtest OOS.

## 5. OPERATING RULES (locked — `memory/compute_placement.md`)
- **Local default; heavy/long compute → MODAL by reflex** (`modal run apps/engine/remote/app.py --job ...`); always-on/crons → **Railway**; orchestration + ultracode/Workflow → **this local session**.
- **Git hygiene:** EVERY workflow/Agent uses `isolation:'worktree'` (a non-isolated agent drifted `main` once). Orchestrator: `git pull --rebase` before committing `main`; watch for stray untracked files left in the main checkout.
- **Efficiency:** never re-search an exhausted surface; parallel agents only for genuinely-new space; Modal for scale; Sonnet for mechanical, Opus for judgment.
- **⚡ Operator preference (locked):** clear, well-scoped fixes — suggested-task chips, obvious bugs — **DO them immediately, don't suggest or ask.** (e.g. the Yahoo monthly-bars fix `eb2915c`.)
- **PRs:** small disjoint branches; operator merges (this session merged the wins #140/#142/#143/#144). GitHub Actions CI is OFF — verify locally/in-worktree.

## 6. KEY FILES
- **Gate:** `master/cohort.py::promote_cohort` + `master/fdr.py::benjamini_hochberg` + `research/equity_holdout.py` (REAL purged+embargoed holdout). **NEVER** `gate.evaluate_cross_asset_ablation` (leaky).
- **Deploy-lane + ARMING pattern:** `research/equity_dual_momentum.py` + `equity_dual_momentum_arm.py` — mirror these to validate+arm a new documented strategy (idempotent, SIM-only).
- **LLM:** `lab/llm.py::openrouter_chat` (SSL-fixed — certifi); `research/llm_narrative_pipeline.py` + `llm_narrative_cohort.py`.
- **Data:** `.cosmu/market_data/equities/` (Yahoo v8, ~135 names + `_tr.json` total-return) + `binanceperp/` (deep perps). **Stooq is dead** (paywalled) — use Yahoo v8 + certifi.
- **Modal:** `apps/engine/remote/app.py` (jobs: gate_sweep/ingest/forward_mark/...).

## 6b. DATA — the lever (TOP priority; smart data > model cleverness)
- **FREE / pulling now (no operator action):** GDELT GKG deep news (2015+, free download → Modal scoring → LLM-narrative verdict); existing Yahoo equities (135 + TR), deep perps, LunarCrush social (1.3M rows), funding/OI.
- **FREE / worth adding (cheap, agent-doable):** SEC EDGAR filings, CryptoPanic crypto news, Reddit/X social (idea-ingestion).
- **BUY (optional — the ONE thing worth paying for):** a **PIT survivorship-free equity dataset** (Norgate Data, or Sharadar SEP/SF1 via Nasdaq Data Link, ~$30-50/mo) → unblocks honest equity factor tests (BAB, sector-neutral momentum) + fundamentals on a clean universe (the cap that killed equity factors). Add the vendor key to `.env.local` → sync to Modal.
- **DB:** KEEP Supabase Pro (8GB) — we store only small numeric PIT scores; raw text is scored on Modal + discarded. No swap/supplement needed (huge corpora → object storage/BigQuery, not a DB change).
- **Stack is right + modern:** Modal (compute) · Railway (crons) · Supabase (store). No new infra.

## 7. RESUME — next actions (priority order)
1. **Read the strategy-fleet report** (run `wf_f7bb544d`) — how many strategies armed live; then **iterate variations of the winners** (FDR-counted) + add more TAA.
2. **Make the forward-mark clock asset-aware** + schedule the equity `--mark` Railway cron → the floor monitors hands-off.
3. **Track 2:** the LLM-narrative deep-corpus **Modal** pull → real verdict.
4. **Keep the fleet iterating** (more TAA + pinescript + variations) — Karpathy throughput, FDR-disciplined, deploy the robust + gate the novel.

## 8. NEXT-PHASE LEVERS (validated by practitioners — r/algotrading + the data)
The METHOD is validated: WFA + deflated-Sharpe + trial-counting + real-costs + forward-test = exactly what the few profitable retail quants describe (most skip it). The gap is (a) a real edge and (b) **NOT meta-overfitting** — *do not re-mine the same data tweaking until it clears the OFFLINE gate (that contaminates the holdout); trust the LIVE forward-test as the fresh OOS arbiter.* Under-exploited levers:
- ✅ **Explicit regime detection (Markov) — DONE, HONEST FAIL (real-but-SUBSUMED).** Built it RIGHT (`research/regime.py`: no-repaint, stride-sampled, stationary features, 8 invariant tests incl. the no-repaint crown jewel; `research/regime_cohort.py`: gated through BH-FDR + real holdout vs flat + naive-price-momentum + shuffle-placebo). On the DEEP data (SPY TR, 8395 bars/33yr) it halves max-drawdown but (a) the **naive price-momentum gate beats it** (regime-momentum in disguise — deploy-lane TAA already captures it, better) and (b) the **shuffle placebo reproduces it** (timing carries no info). Crypto (BTC, thin): in-sample-promising, holdout DSR NEGATIVE → decays OOS. **Verdict: NOT a standalone edge; keep `research/regime.py` as a reusable feature/gating overlay.** (DECISIONS entry 2026-06-07.) *An HMM variant is the only remaining untried form — likely same outcome; low priority.*
- **Live-vs-backtest divergence monitoring** — flag when a forward-test stops tracking its backtest (alpha-decay / regime-shift early warning). Step one shipped (forward vs backtest columns on the leaderboard); step two = the divergence alert.
- **Market-neutral / directionless** — the realest crypto signal was L/S-neutral (spot-only killed it); on a short-capable venue it's the validated direction.

**TRIAGED IDEA BACKLOG (2026-06-07 review — ranked profit-impact ÷ effort; all built from parts we own, no new data):**
1. **Strategy × asset × timeframe matrix (FDR) on Modal** — widen honest search to surface the first survivor (search is "exhausted" only on the *current* grid). MEDIUM, reuses Modal + FDR. *Highest-leverage search move.*
2. **CPCV (combinatorial purged CV + embargo)** — stronger OOS than single-path WFA; hardens any survivor against overfit. MEDIUM, extends purged-holdout.
3. ✅ **Recovery Factor + Calmar (drawdown-aware ranking)** — DONE this session (`master/risk_metrics.py` + `BacktestMetrics.recovery_factor`).
4. **Slippage VARIANCE** — model slippage as a distribution not flat bps; kills fragile flat-bps-only edges before a forward-test slot. MEDIUM.
5. **Live-vs-backtest reconciliation alert** — finish the half-shipped divergence columns into an alert; closes the SIM→live trust loop. QUICK (~1hr).
- **Next BIG bet after the above:** **intraday data (equity+crypto)** — the binding daily-thinness unlock; hard prerequisite for order-flow/volume-profile (a genuinely orthogonal microstructure axis) + maker-rebate/prediction-market surfaces.
- **DEFERRED (premature while the Gate has 0 survivors):** ensemble-weak-signals (do after the matrix widens the pool), idea-ingestion engine, MCP-over-our-data (read-only investigation; NOT execution), LLM-quantified alt-data beyond news (day-of-week is the one cheap slice). **SKIP (regime axis is FAILed-subsumed — stop polishing it):** symbolic-regression regime discovery, cycle-position, matrix-power decay, multi-domain conviction. **POST-EDGE:** France live adapter (Kraken Futures/IBKR).

## 9. MINOR CLEANUPS (batch, low-urgency)
- `/live/positions` + `/live/venues` (`api/routers/live.py`): scope to live-armed server-side (frontend gates it for now).
- Hardcoded `CACHE = Path("/Users/device/cosmu/…")` in `equity_dual_momentum.py` + sibling arms → make configurable (breaks off this Mac / on Modal-Railway). *(The new `regime_cohort.py` already does this right — `COSMU_EQUITY_CACHE` env override; mirror that pattern.)*
- Verify `schema_postgres.sql` carries the survival columns (the live store got the out-of-band migration 2026-06-07; fresh provisions need them too).
- **Worktree-isolation footgun keeps recurring** — agents write to main/orchestrator branch via absolute `/Users/device/cosmu/…` paths. Enforce "edit only within your worktree (relative paths)" in every agent prompt.
- **Prune ~19 accumulated worktrees** — `git worktree list` → remove stale agent dirs (KEEP `agent-add72795` = gkg pipeline code, + any still-active).
- ✅ **`gate_verdicts` storage gap — FIXED.** `master/verdict_log.py` (`CohortPersist` + `persist_cohort_verdict`, best-effort/offline-safe) + opt-in `persist=` on `promote_cohort` (pure by default). Wired the LIVE `gate_stage` + the regime cohort (from birth) + the llm-narrative exemplar; GET `/research/gate` skips cohort rows so they can't 500 the single-signal card. Validated end-to-end (0 → 3 queryable cohort rows from the regime runs). **Remaining (mechanical, low-value): the 6 CLOSED research runners** (equity_reversal/lowvol/sector, social_dominance/signal, funding_crowding) aren't wired — they produce no new results; retrofit is a one-liner `persist=durable_persist(run_id=…, hypothesis=…, source=…)` at their `promote_cohort` call IF ever re-run.

## 🤖 AUTONOMOUS SESSION 2026-06-07 (PR #148, ~14 commits — the "data machine" pass)
- **EXPERIMENT MEMORY is now VISIBLE + the product centerpiece.** `gate_verdicts` (every theory tested + verdict) is served by `GET /research/experiments` (hypothesis · source · verdict · best dSR vs 0.95 · REAL holdout DSR · per-candidate kill-reasons) and rendered as the **`/verdicts` → "Theories"** UI surface (searchable, decay-tagged, honest empty state). **64 theories tested, 0 PASS** — the machine that never lies, now legible.
- **Unified theory loop (NO new bespoke scripts):** `research/matrix_search.py` runs ANY inbox StrategySpec through the honest Gate (BH-FDR + real holdout + fees) on any (asset,timeframe), persists the verdict. A parallel agent workflow AUTHORED 8 new computable specs (Bollinger/Donchian/ATR/ADX) → validated → inbox → gated across assets → all honest FAIL. Add theories = drop a spec → it auto-gates + shows in the UI.
- **Survivor-hunt (backlog P): 55 cells (spot+equity+perp), 0 survivors** — inbox families spent; need ORTHOGONAL data, not more sweeps. ~960k tokens across two parallel Modal-style local fan-outs.
- **Trust + cost hardening banked (additive, wire post-survivor):** `master/cpcv.py` (combinatorial purged CV), `data/slippage.py` (slippage-variance + fragility flag), `master/risk_metrics.py` (Calmar + Recovery Factor).
- **⚖️ Gate calibration verdict: correctly STRICT — never loosen** (see DECISIONS + `memory/gate_calibration_locked`); the only fix is the typed TWO-LANE routing (deploy-lane bar already exists in `equity_sector_rotation_taa.py`). GEM re-confirmed DEPLOYABLE (½ SPY's drawdown, +45% in the 2008 crash).
- **⚡ Web perf FIXED** — SSR fetch + proxy now fast-fail (AbortSignal.timeout) + 30s cache so a cold Railway engine can't hang the page. *(Persistent "Engine not connected" = the Railway engine itself is asleep/down → wake it.)*
- **NEXT:** (1) 🩺 wake the Railway engine + finish two-lane routing → the FLOOR shows + arms; (2) 🔭 orthogonal DATA (intraday microstructure / alt-data beyond news) — the only un-exhausted axis; (3) repoint the Overview "verdicts" preview at `getExperiments` + retire the stale markdown `/verdicts` path (UI agent flagged the source mismatch).

## ⏳ IN FLIGHT (a fresh session inherits — check these FIRST; they will NOT auto-notify a new session)
- ✅ **LLM-narrative verdict: DONE — HONEST FAIL** (0/10 assets clear; momentum-in-disguise + partial look-ahead; best dSR 0.889 vs 0.95). The upside axis is honestly closed. **Code + evidence now BANKED on this branch** (salvaged the gkg deep-corpus pipeline + thread-safe scorer from `worktree-agent-aa771aa` WITHOUT its stale web reverts — that branch forked pre-#147 and would have clobbered the data-viz + reverted the Yahoo true-daily fix). The Yahoo monthly-bars bug is already fixed on main (`eb2915c`). *Nothing left to merge from aa771aa.*
- **Merged this session:** #140 (Explorer) · #142 (real holdout) · #143 (LLM-narrative machine) · #144 (GEM pilot) · #145 (UI honesty) · #146 (UI cohesion) · **#147 (data-viz: sparklines/gauges/interlock-strip/tabs)** · leaderboard forward-return · Overview force-dynamic build fix. Survival migration applied. 9 strategies live at honest 0%. *(UI = a disciplined OKLch design system with a real data-viz layer — not vibe-coded.)*

**The ONE goal:** strategies that survive honestly and compound; the machine that never lies is the asset. Floor + upside. Go.
