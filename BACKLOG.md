# Cosmu Backlog

> Agents: read on session start (after `AGENTS.md` → `docs/MASTER_PLAN.md`). Suggest splitting big items for parallel agents.
> Tag: (engine|web|config) + (opus|sonnet). **Build on the M2 (local) by default; cloud only for many parallel agents.**
> Done — do NOT re-add: all pre-2026-06-07 items above plus the following.
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
