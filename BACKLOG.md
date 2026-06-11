# Cosmu Backlog

> Agents: read on session start (after `AGENTS.md` → `docs/MASTER_PLAN.md`). Suggest splitting big items for parallel agents.
> Tag: (engine|web|config) + (opus|sonnet). **Build on the M2 (local) by default; cloud only for many parallel agents.**
> Done — do NOT re-add: all pre-2026-06-07 items above plus the following.
> **Merged 2026-06-09/10 (audit fix-wave — do NOT re-add):** forward-test EXECUTOR (`orchestrator/forward_step.py` — tracks run their OWN exits/re-entries; funder funds once; sim fills pay 5 bps slippage; reduce_only gauntlet lane) · matrix sweep alt-data join (the sweep now actually searches funding/social/news specs) · rotation arms close stale legs (`arm_rotation.py`, all 10 equity arms + daily re-arm cron) · API shared-secret auth enforced (docs/KEYS.md is now true) · spine/evolution track capital unified to `sim_track_capital` · Gate calibration pinned by test · pre-push hook now runs naming+drift+pytest+typecheck · autonomy cron default ON · /correlations + autonomy-tick web contract fixes + ~1,100 dead web lines removed · order-path positions mark via instrument's real venue.

## 🧭 EPICS (2026-06-11 operator session — interface consolidation + real-time lane)
- [ ] **EPIC: Real-time data lane** — bots live · data live · marks live. Tiered plan (fast crons → always-on worker + websockets → profit-gated paid social), full detail in **`docs/epics/realtime-data-lane.md`**. Tier 1 (15-min ingest cron + hourly mark-to-market) is a ~½-day quick win that unblocks honest "24h perf" on the web. (engine+infra, opus)
- [ ] **Live/sim split in the backend** — first-class `mode` (paper|live) on tracks/marks/aggregates + one `/portfolio/summary` endpoint returning both totals (invested/free/P&L per mode). Prerequisite for the web redesign's one-line strip, separate Paper/Live dashboards, variance attribution, and honest accounting (today `/live` shows SIM capital while disarmed). (engine, sonnet)
- [ ] **Web redesign v3 — consolidation** — 15 pages → 5 (Strategies · Paper · Live · Costs · Commands); one filterable strategies table with lifecycle timeline per row (Queued→Backtest→Gate ✓→Paper→Live, Killed visible); strategy detail absorbs the Explorer (equity gross/net + markers) + building blocks + data-source feed; console removed (go-live from strategy detail, steering from Claude Code); Lab/Mind/Verdicts/Correlations leave the nav (backend keeps gathering — fold key facts into strategy detail). 5 exploratory mockups in `mockups/variant-*.html` (2026-06-11); operator picks a direction first. (web, sonnet)
- [ ] **"Liquidate all" (live-only)** — real execution path: market-sell every live position to USDC via the adapter + disarm, 2-click confirm in the web. Today `/live/defund` only zeroes `positions.qty` in DB — it does NOT place venue orders. Pair with a separate quiet "Pause all paper" (pause, never kill — paper history is training data). (engine+web, opus)
- [ ] **Rename forward_test → paper everywhere** (operator decision 2026-06-11: uniform "paper", front AND back) — DB value migration + tolerant readers (accept both during transition), event kinds, contracts regen, config (`FORWARD_TEST_MIN_DAYS`), module/docs/skills sweep; add a legacy note to docs/GLOSSARY.md ("paper == formerly forward_test; pre-2026-06 events keep old kinds"). Own PR, never mixed with the redesign. (engine+web, sonnet)
- [ ] **Building-block registry (mix-and-match v2)** — decompose every spec into content-hashed typed blocks (signal · filter · setup · exit · sizing) + a lineage table (version → blocks, parents); block-level leaderboard (survivor rate per block, observational only — FDR stays the only funder); dedup by combo-hash protects the multiple-testing budget; feeds `evolve-strategy` sampling and the "similar strategies" panel on strategy detail. (engine, opus)
- [ ] **Paper-twin for live strategies** — when a track is launched live, keep its paper twin running on the same spec (until manually killed) so SIM↔live divergence is measured continuously (`/variance-attribution` input) and paper history keeps accumulating as training data. (engine, sonnet)

## 🚧 PRE-LIVE GATES from the 2026-06-10 adversarial review (sim is honest; these MUST land before any track is armed live)
- [ ] **Bar-cache freshness for the executor** — `BinanceSpotOHLCVProvider.fetch_bars` serves cache with no freshness check when `len(cached) >= limit` (market.py:40-43), and `_merge_bars` keeps the OLD row on ts collision while the 22:10 cron caches the in-progress daily candle. Ephemeral Railway masks it; on any persistent filesystem the executor would decide on frozen bars forever. Fix: drop the unclosed last candle, refetch when newest cached ts ≥ 1 bar period old, prefer fetched over cached for the final ts. (engine, opus)
- [ ] **Fill-convention alignment executor↔screen** — the screen fills signal exits at next-bar open with signals read at idx-1; the executor decides and fills at the latest close (take side now capped at the limit; stop side honestly pessimistic). For equities the 22:10 UTC fill is >1h after the cash close. Quantify the gap (variance-attribution) and align or document per-venue. (engine, opus)
- [ ] **Live-exit lane for reduce_only** — the executor is sim-only; a live position's exit needs the live book + adapter path (the validate/fill book mismatch is fixed for sim; live closes are simply not routed yet). Required before arming anything live. (engine, opus)
- [ ] **Neutral-track funding cliff** — when a two-leg neutral track's legs fully close, accrued funding falls out of its scope='track' series (artificial step in the drift monitor's input). Carry terminal funding into the flat-track value. (engine, sonnet)
- [ ] **Dust trap** — a position whose marked notional falls below venue min_notional can never close (base checks still apply to reduce_only). Exempt closes from min_notional/lot_size or close-at-dust policy. (engine, sonnet)

## ⚡ OPERATOR ACTIONS unlocked by the 2026-06-09 audit fix-wave (run locally / Modal — need data + creds a cloud agent lacks)
- [ ] **Re-run the matrix sweep over the ALT-JOINED feature space** — the previous "search exhausted, 0 survivors" verdict only ever searched bar-TA (the sweep never joined alt data; fixed). `python3 -m cosmu.research.matrix_search --sweep` locally or the Modal lane. The first honest survivor may be in the ~75 unsearched features. (local/Modal, operator)
- [ ] **Set AUTONOMY_CRON_ENABLED on Railway to taste** — code default is now ON (sim-only, bounded); set 0 to freeze. Verify the 4 crons fire: ingest 6h · tick 4h · clock 22:10 (now step-then-mark) · arm-fleet re-arm 22:40. (Railway, operator)
- [ ] **Confirm API_SECRET_KEY is set on BOTH Railway and Vercel** — the engine now actually enforces it (it didn't before); a mismatch will 401 the web proxy. (Railway+Vercel, operator)
- [ ] **Check the prod trials ledger for synthetic pollution** — audit claimed fixture trials leak into prod; code paths all use temp stores, so verify against the DB: `SELECT source, COUNT(*) FROM trials GROUP BY source` and eyeball for fixture/demo sources. (local, operator)
> **Merged 2026-06-07 (5-PR wave — do NOT re-add):** hygiene sweep + deploy-lane fleet (#151) · typed two-lane routing + perp harness + intraday source + control-room overview + Theories surface + arm_fleet (#152) · divergence alert + fleet ETF catalog (#153) · Faber phantom-mark fix (#154) · 10 PIT-honest alt-data sources (21 features) + full frontend overhaul (#155).
> **Previously merged (do NOT re-add):** finder significance leaks (P0), forward-test hard gate (P1), pre-push verify hook (P3), cost/ROI writers, managed data layer, 40 alt-features wired · 2026-06-04 7-PR train (#47–60) · bar backbone / Binance Vision backfiller (#129) · MCP layer (#128) · honesty harness: fake exchange_netflow disabled, funding annualization, FRED ALFRED vintage, registry⊆routable guard (#132).

## Now (the honest-edge path — data first, then lift)
- [ ] Run robust full backfill + activate all FREE sources via `/manage-data` → deep, broad data across the now-wide (~30) perp universe + multi-timeframe (the #1 unblock) (engine, **local/Railway** — needs live data-API network, not a cloud agent)
- [ ] **Re-run the gate on the deep data** — author the lucrative set (funding-carry · cross-sectional momentum · funding-contrarian · vol-regime) → first real survivor (or honest fail) (engine, opus)
- [ ] **Compute Phase 1** (see docs/COMPUTE.md): parallelize `verify.yml` into jobs + cache pnpm & `.next/cache` + add `pnpm verify:remote` (push→tail CI). Kills the local-verify wait (config, sonnet)
- [ ] **Tech-debt: consolidate the two LLM formatters.** `ingest/llm_formatter.py` (wired, lexicon fallback) is canonical; if the point-in-time `ts`/`source`/`rationale` fields from the dropped #56 `FormattedFeature` are wanted, fold them INTO `llm_formatter.py` — do NOT reintroduce a parallel module (engine, sonnet)

## Next
- [ ] Meta-labeling model (triple-barrier) on real outcomes; soft-labels now wired (#48) to break the no-positive-labels cold-start (engine, opus)
- [ ] **Compute Phase 2** (see docs/COMPUTE.md): thin `apps/engine/remote/` Modal app for backtests/ML/gate sweeps, driven by `modal run` — scale-to-zero heavy lane (engine+infra, opus)
- [ ] `/generate-strategies` command: Claude Code mass-authors + LLM-formats + tracks specs, replicable, all gated (config+engine, opus)
- [ ] Scores / indexes dashboard: LunarCrush + sources + OSINT + LLM review; pick-sources, greyed if no key (web, sonnet)
- [ ] More data sources (a ton) addable via `/add-data-source` (now with `/profile-source` GO/REVIEW/NO-GO gate, #58); add OSINT feeds (engine, sonnet)
- [ ] Strategy × asset × timeframe matrix (the core ML feature) — now unblocked by the wide universe + multi-timeframe panels (#60) (engine, opus)

## Later
- [ ] Kraken Futures live adapter (post-edge) · IBKR equities (data-only first)
- [ ] Gate hardening: route the cohort through the full `research/gate.py:PREREGISTERED_BAR`
- [ ] Cross-strategy correlation signals
- [x] **Modal heavy-compute lane scaffolded** (2026-06-05, see docs/COMPUTE.md): `apps/engine/remote/app.py` (gate_sweep · ingest · forward_mark · run_module) + `scripts/sync_modal_secret.py` + `pnpm modal:gate/ingest/secret`. Hybrid: **Railway keeps the backend**. Fly rejected; RunPod deferred (post-edge GPU). *Remaining:* run a first real `modal run` end-to-end and confirm it writes to Supabase (needs Modal account + `pnpm modal:secret`) (infra, opus)
- [ ] Options support

## ⭐ TOP OF QUEUE — 2026-06-06 session (SUPERSEDES the stale "Now" above; detail in docs/HANDOFF_NEXT.md + docs/reports/)
> Big reframe this session: the "0 edges" verdict was untrustworthy — the harness was broken. P0 now FIXED (#123/#126).
- [x] **Bar backbone** — `BinanceVisionBarBackfiller` shipped (#129, 2026-06-06). Run it locally to fill the cache.
- [x] **Honesty fixes** — all 4 shipped (#132, 2026-06-06): exchange_netflow disabled, funding annualization fixed, FRED ALFRED vintage, registry⊆routable guard.
- [ ] **Re-run the crypto cohort** on the trustworthy harness — btc-social risk-on OVERLAY first + Polymarket family on
      historical odds (data-only); one BH-FDR family → honest edge verdict. (local)
- [x] **MCP layer** — Supabase + Postgres + engine read-only MCPs shipped (#128, 2026-06-06).
- [ ] **P2 integrity** — route/disable the 5 enabled-but-unrouted registry features; harden `ingest/ml_panel.py`. (engine, sonnet)
- [ ] **Ingest off leaky gate** — remove / quarantine the leaky cross-asset ingest paths (`evaluate_cross_asset_ablation` seam + its `StoreBackedAltProvider`) from the live cron so only PIT-honest features feed Gate runs. (engine, sonnet)
- [ ] **scan-signals reads the registry** — wire `/scan-signals` to iterate the feature registry so every enabled, routable feature gets a hypothesis generated and submitted to the Gate. Today it works off a fixed brief list. (engine+config, sonnet)
- [ ] **Run new-source ingest** — after the 10 sources shipped in #155, trigger a real `python3 -m cosmu.ingest.run` pass against Supabase to populate the new features end-to-end (needs live Railway env or Modal). (local/Railway, operator)
- [ ] **Hot/cold data tiering** — archive full history to parquet on Cloudflare R2 (DuckDB reads), keep hot in PG; build when
      the 8 GB Supabase Pro cap nears (~6 GB now) → infra <$100/mo at scale. (engine+infra) — see docs/reports/scaling-economics.md
- [x] **Data-viz overlay charts** — shipped in frontend overhaul (#155, 2026-06-07).
- [x] **"cohort" UI tooltip** — shipped (#155, 2026-06-07).
- [ ] **Branch graveyard cleanup** — prune stale worktrees/branches WHEN no agents active. (git)
- [ ] **$15 LunarCrush BUILDER mega-grab** (when wanted): upgrade Builder 1 day (100 req/min) → `scripts/lunarcrush_max_extract.py
      --coins 4000 --stocks 2000 --topics 800 --categories 300 --sleep 0.7` (gated-skip + batched writes already in) → store → CANCEL.
- [ ] **Lane A2 buys** (AFTER the Gate is proven): LlamaParse filings (`.claude/tasks/lane-a-filings-llamaparse.md`),
      Firecrawl/GDELT/Quiver, Cohere Rerank, Renovate + CodeRabbit. See docs/reports/generalization-plan-2026-06-06.md.
- [x] **Decided 2026-06-06:** keep GitHub-hosted CI (PR-only, lean) — NOT self-hosted/Codespaces; NO VPS; Polymarket =
      backtest-only (live parked, US blocked); Supabase Pro (8 GB) is the data home until tiering.
