# Cosmu Backlog

> Agents: read on session start (after `AGENTS.md` → `docs/MASTER_PLAN.md`). Suggest splitting big items for parallel agents.
> Tag: (engine|web|config) + (opus|sonnet). **Build on the M2 (local) by default; cloud only for many parallel agents.**
> Done this session (do NOT re-add): finder significance leaks fixed (P0), forward-test is a hard gate (P1), pre-push verify hook (P3), cost/ROI writers + `/costs` 500 fixed, managed data layer + `/manage-data` (D), all 40 alt-features wired into the backtest (1), control-room overview + idea inbox (2).
> **Merged 2026-06-04 (7-PR train — do NOT re-add):** evolve flywheel wired into the tick (#47) · experiments registry + soft-labels (#48) · adversarial gate proof (#57) · SIM→live variance-attribution + `/profile-source` (#58) · modular cockpit UI rebuild (#59) · wider perp universe + multi-timeframe + ML-ready PIT panels (#60). LLM-formatting layer (#56) **dropped as duplicate** — see debt note below.

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
- [ ] **Bar backbone** — `BinanceVisionBarBackfiller` (bulk OHLCV 2017→now, spot+perp, full universe); the bar cache is
      EMPTY → every Gate run is starved. THE precondition. Keyless/free; run is LOCAL. (engine, opus)
- [ ] **Honesty fixes** — fake `exchange_netflow` (rename/disable), funding annualization (per-symbol interval, 2–8× off),
      FRED ALFRED vintage, + `registry ⊆ routable` guard test. (engine, sonnet) — *serialize after bar backbone*
- [ ] **Re-run the crypto cohort** on the trustworthy harness — btc-social risk-on OVERLAY first + Polymarket family on
      historical odds (data-only); one BH-FDR family → honest edge verdict. (local)
- [ ] **MCP layer** — Supabase + Postgres + thin engine/Gate-CLI MCP (Claude Code drives it natively). (infra) — parallel-safe
- [ ] **P2 integrity** — route/disable the 5 enabled-but-unrouted registry features; harden `ingest/ml_panel.py`. (engine, sonnet)
- [ ] **Hot/cold data tiering** — archive full history to parquet on Cloudflare R2 (DuckDB reads), keep hot in PG; build when
      the 8 GB Supabase Pro cap nears (~6 GB now) → infra <$100/mo at scale. (engine+infra) — see docs/reports/scaling-economics.md
- [ ] **Data-viz overlay charts** — recover stash `data-viz-wip-2026-06-06` or re-run (price+social+funding overlay, event dots). (web)
- [ ] **"cohort" UI tooltip** — "tested together so a winner isn't just lucky." (web, xs)
- [ ] **Branch graveyard cleanup** — prune stale worktrees/branches WHEN no agents active. (git)
- [ ] **$15 LunarCrush BUILDER mega-grab** (when wanted): upgrade Builder 1 day (100 req/min) → `scripts/lunarcrush_max_extract.py
      --coins 4000 --stocks 2000 --topics 800 --categories 300 --sleep 0.7` (gated-skip + batched writes already in) → store → CANCEL.
- [ ] **Lane A2 buys** (AFTER the Gate is proven): LlamaParse filings (`.claude/tasks/lane-a-filings-llamaparse.md`),
      Firecrawl/GDELT/Quiver, Cohere Rerank, Renovate + CodeRabbit. See docs/reports/generalization-plan-2026-06-06.md.
- [x] **Decided 2026-06-06:** keep GitHub-hosted CI (PR-only, lean) — NOT self-hosted/Codespaces; NO VPS; Polymarket =
      backtest-only (live parked, US blocked); Supabase Pro (8 GB) is the data home until tiering.
