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
- **LIVE NOW:** **GEM** (dual-momentum) forward-test ARMED in prod (`version 4695617d`, SPY SIM position, $10k) — the FLOOR. The **strategy-fleet** (run `wf_f7bb544d`) is arming more TAA strategies alongside it.

## 3. THE TWO TRACKS (the plan — no more circling)
- **TRACK 1 · FLOOR:** deploy documented-robust strategies live (GEM + fleet) → modest-but-real compounding (~0.6-0.8 Sharpe, crash protection). Iterate: more TAA models, **variations of winners (FDR-counted)**, pinescript imports (honestly gated).
- **TRACK 2 · UPSIDE:** LLM-narrative (machinery merged, PR #143). Next = pull a **DEEP raw-text corpus** (GDELT GKG via BigQuery, or CryptoPanic/news archive; 2-3yr, liquid names) → score on **MODAL** (embarrassingly parallel, content-hash cached, ~$ few) → materialize daily PIT scores to `alt_data` → run `research/llm_narrative_cohort` unchanged → real verdict.

## 4. MONITOR LIVE STRATEGIES (do this — "monitor heavy")
- **Watch:** `GET /leaderboard` (Strategies page) + `GET /overview` — `forward_age_days`, `live_ready` (crosses True at +31d), `return_pct`.
- ⚠️ **The generic forward-mark clock (`cosmu.orchestrator.loop` / `mark_tracks`) prices via Binance → CANNOT mark EQUITY tracks** (leaves them flat). **PRIORITY TASK: make the forward-mark clock ASSET-AWARE** (price equity tracks via Yahoo total-return) so ALL equity forward-tests accrue hands-off.
- Until then, the equity clock: `python3 -m cosmu.research.equity_dual_momentum_arm --mark` (marks GEM). **Schedule it as a daily Railway cron.** Fleet-armed strategies need their marking folded into the generalized clock.

## 5. OPERATING RULES (locked — `memory/compute_placement.md`)
- **Local default; heavy/long compute → MODAL by reflex** (`modal run apps/engine/remote/app.py --job ...`); always-on/crons → **Railway**; orchestration + ultracode/Workflow → **this local session**.
- **Git hygiene:** EVERY workflow/Agent uses `isolation:'worktree'` (a non-isolated agent drifted `main` once). Orchestrator: `git pull --rebase` before committing `main`; watch for stray untracked files left in the main checkout.
- **Efficiency:** never re-search an exhausted surface; parallel agents only for genuinely-new space; Modal for scale; Sonnet for mechanical, Opus for judgment.
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

**The ONE goal:** strategies that survive honestly and compound; the machine that never lies is the asset. Floor + upside. Go.
