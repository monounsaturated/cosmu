# Cosmu Backlog

> Agents: read on session start (after `AGENTS.md` → `docs/MASTER_PLAN.md`). Suggest splitting big items for parallel agents.
> Tag: (engine|web|config) + (opus|sonnet). **Build on the M2 (local) by default; cloud only for many parallel agents.**
> Done this session (do NOT re-add): finder significance leaks fixed (P0), forward-test is a hard gate (P1), pre-push verify hook (P3), cost/ROI writers + `/costs` 500 fixed, managed data layer + `/manage-data` (D), all 40 alt-features wired into the backtest (1), control-room overview + idea inbox (2).

## Now (the honest-edge path — data first, then trust, then lift)
- [ ] Run robust full backfill + activate all FREE sources via `/manage-data` → deep, broad data (the #1 unblock) (engine, local)
- [ ] Adversarial validation tests: shuffled-label / no-edge data → 0 survivors; known-edge fixture → pass (proves the gate isn't leaky) (engine, opus)
- [ ] LLM data-formatting layer: raw (news/social/scraped) → typed point-in-time features (sign·magnitude·category); cheap OpenRouter; schema-out; NEVER in the money path (engine, sonnet)
- [ ] Experiment tracking: runs/experiments registry (config + seed + metrics + data_version) — comparable + exactly regenerable (engine, opus)

## Next
- [ ] Meta-labeling model (triple-barrier) on real outcomes; soft-labels to break the no-positive-labels cold-start (engine, opus)
- [ ] Wire the evolve flywheel (`run_evolution_cohort`) into the scheduler — self-reinforcing (engine, opus)
- [ ] `/generate-strategies` command: Claude Code mass-authors + LLM-formats + tracks specs, replicable, all gated (config+engine, opus)
- [ ] Scores / indexes dashboard: LunarCrush + sources + OSINT + LLM review; pick-sources, greyed if no key (web, sonnet)
- [ ] More data sources (a ton) addable via `/add-data-source`; add OSINT feeds (engine, sonnet)

## Later
- [ ] Kraken Futures live adapter (post-edge) · IBKR equities (data-only first)
- [ ] Gate hardening: route the cohort through the full `research/gate.py:PREREGISTERED_BAR`
- [ ] Cross-strategy correlation signals
- [ ] Fly.io scale-to-zero worker for unattended 24/7 ML (ONLY post-edge)
- [ ] Options support
