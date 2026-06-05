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
- [ ] **Consolidate compute onto Modal** (decision 2026-06-05, see docs/COMPUTE.md): Phase 2 Modal app for backtests/ML/gate sweeps first; then fold the engine API (ASGI) + 4h cron onto Modal and retire Railway. Fly.io rejected (services-first, no free tier, not in VISION) (infra, opus)
- [ ] Options support
