# COSMU — Documentation Index

> The map of every doc under `docs/` (and the key root-level docs), grouped by purpose so a human can find the
> right one without grepping. **Current** = the live source of truth; **Historical** = a dated snapshot / superseded
> plan kept for the record (don't act on it). For the codebase itself, start with
> [ARCHITECTURE.md](ARCHITECTURE.md). The single canonical entry point for a coding agent is [../AGENTS.md](../AGENTS.md).

---

## Start here

| Doc | What it is | Status |
|---|---|---|
| [../README.md](../README.md) | One-screen project intro: what it does/doesn't, run/verify/deploy commands, stack. | Current |
| [START_HERE.md](START_HERE.md) | The 2-minute operator guide: run it, the 3 daily "doors", where things live. | Current |
| [../AGENTS.md](../AGENTS.md) | **The canonical entry point for any coding agent** — invariants, skills, conventions. | Current |
| [OWNER_SETUP.md](OWNER_SETUP.md) | Owner-facing setup & handoff (keys, deploy commands, cost). | Current (root facts; some 2026-06-01 detail dated) |

## Architecture (how the code fits together)

| Doc | What it is | Status |
|---|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | **The codebase map** — what COSMU does, the end-to-end pipeline, the subsystem table, the money path + safety interlocks, the product surface, and the auto-generated module tree. | Current |
| [IMPLEMENTATION.md](IMPLEMENTATION.md) | The build log — what is actually built and the decisions taken, in reverse-chronological "Built" sections. Detailed but accretive (older sections describe earlier states). | Current (log) |
| [MASTER_PLAN.md](MASTER_PLAN.md) | The single operating plan: what's real today (verified vs code), the gaps, the target architecture, the roadmap. | Current |
| [CODING_STANDARDS.md](CODING_STANDARDS.md) | Copy-paste templates + conventions for common code patterns. | Current |
| [COMPUTE.md](COMPUTE.md) | Where heavy work runs (Modal / CI / the M2) + the compute & CI plan. | Current |

## Product & vision

| Doc | What it is | Status |
|---|---|---|
| [VISION.md](VISION.md) | The strategic contract / product memo (north star, principles, the 17-section build plan). Marked historical/aspirational at the top — operational truth is AGENTS.md + IMPLEMENTATION.md. | Current (contract) — runtime details may be stale |
| [PRODUCT.md](PRODUCT.md) | The product definition for the web surfaces — the canonical nav, persona, and per-surface epics. | Current |
| [GLOSSARY.md](GLOSSARY.md) | **Canonical vocabulary** — the locked lifecycle, Strategy/Version/Track, the Gate, the Mind, taxonomy facets, code↔DB↔API identifiers. | Current (authoritative) |

## Data

| Doc | What it is | Status |
|---|---|---|
| [DATA_INDEX.md](DATA_INDEX.md) | Where everything lives — Supabase tables + R2 lake prefixes, connection footguns, the hot/cold cut-line. | Current |
| [KEYS.md](KEYS.md) | The canonical table of every secret/key, what it unlocks, required/free. | Current |
| [SETUP_APIS.md](SETUP_APIS.md) | How to set up external APIs & keys (engine runs with zero keys; this is the upgrade path). | Current |

## Strategy authoring

| Doc | What it is | Status |
|---|---|---|
| [AUTHORING.md](AUTHORING.md) | **Generated** never-drifting reference — the feature vocabulary + `StrategySpec` schema, dumped live from the code (`python3 -m cosmu.docs.authoring_fiche`). | Current (auto-generated) |
| [STRATEGIES.md](STRATEGIES.md) | What a "strategy" is in COSMU + the campaign memos (every theme tried + its honest Gate verdict). | Current |

## Operations & runbooks

| Doc | What it is | Status |
|---|---|---|
| [runbooks/kraken-activation.md](runbooks/kraken-activation.md) | Step-by-step to activate Kraken as the keyless crypto bars venue (and prep live exec). | Current (prepared, not activated) |
| [AGENT_TASKS.md](AGENT_TASKS.md) | The dispatch queue — copy-paste, self-contained prompts for parallel agents. | Current (working queue) |
| [LOCAL_AGENT_PROMPT.md](LOCAL_AGENT_PROMPT.md) | Prompts that must run on the Mac / a deps-installed session (not a cloud agent). | Current |
| [EXTERNAL_REPOS.md](EXTERNAL_REPOS.md) | Patterns borrowed from external repos without coupling the runtime. | Current (reference) |
| [RESEARCH_THROUGHPUT.md](RESEARCH_THROUGHPUT.md) | The best-practice workflow for autonomous data/research throughput. | Current |

## Research

| Doc | What it is | Status |
|---|---|---|
| [research/RESEARCH_LESSONS.md](research/RESEARCH_LESSONS.md) | Durable lessons from the research campaigns. | Current |
| [research/xsec_momentum.md](research/xsec_momentum.md) | Cross-sectional momentum study. | Current (study) |
| [research/squeeze_range_reversion_study.md](research/squeeze_range_reversion_study.md) | BB-width squeeze / range-reversion study (no spot edge found). | Current (study) |
| [research/astro_vs_markets.md](research/astro_vs_markets.md), [research/ASTRO_VERDICT.md](research/ASTRO_VERDICT.md) | The astrology-vs-markets study + verdict (0 edge — used as a non-causal control). | Current (study + verdict) |
| `research/astro_*.md`, `research/alt_data_pit_audit.md`, `research/RESEARCH_PREVIEW.md` | Supporting astro deep-dive plans/notes + the alt-data point-in-time audit. | Mixed (studies/plans) |
| [plans/social-llm-edge-lane.md](plans/social-llm-edge-lane.md) | **The next edge lane** — priority-1 social/LLM/niche plan. | Current (plan) |
| [epics/agentic-lane.md](epics/agentic-lane.md) | The agentic-lane design epic (eligibility gates, proof∝capital lanes). | Current (design) |
| [epics/indexes.md](epics/indexes.md) | The INDEX subsystem epic. | Current (design) |
| [epics/realtime-data-lane.md](epics/realtime-data-lane.md) | The realtime-data-lane epic (closed-candle guard, event machine). | Current (mostly shipped) |
| [epics/hot-cold-data-stack.md](epics/hot-cold-data-stack.md) | The hot/cold data-stack epic (Supabase hot window + R2 lake). | Current (shipped) |
| [epics/regime-context-deep-analysis.md](epics/regime-context-deep-analysis.md) | Regime-context deep-analysis epic. | Current (design) |
| [epics/web-redesign-compat.md](epics/web-redesign-compat.md) | Web redesign compatibility epic. | Current (design) |
| [epics/tasks/](epics/tasks/) | Per-epic task breakdowns (`local-agent-post-merge-actions.md`, `operator-local-missions.md`). | Current (task lists) |

## Decisions & lessons

| Doc | What it is | Status |
|---|---|---|
| [DECISIONS.md](DECISIONS.md) | **Append-only** log of what we concluded and why. | Current (authoritative) |
| [LESSONS.md](LESSONS.md) | Blunt list of mistakes actually made + the rule that prevents the repeat. | Current (authoritative) |
| [reports/](reports/) | Dated verdict/state reports (phase-0 verdicts, economics, edge plans, the defensive5 ignition, the Supabase-free downgrade). Each is a point-in-time finding — read the dated header. | Mostly Historical (dated findings; the verdicts remain valid) |

## Historical / archive

These are dated snapshots, superseded plans, or one-off checkpoints. Kept for the record — **do not act on them
as current**. **Recommendation (not performed here):** move the dated `CHECKPOINT_*` / `REVIEW_*` / superseded
`HANDOFF_*` files into `docs/archive/` to keep the top level lean.

| Doc | What it is | Status |
|---|---|---|
| [archive/BUILD_PLAN.md](archive/BUILD_PLAN.md), [archive/PLAN.md](archive/PLAN.md) | The historical deep build plans (refined by VISION/PRODUCT/IMPLEMENTATION). | Historical |
| [archive/HANDOFF.md](archive/HANDOFF.md), [archive/HANDOFF_MIND.md](archive/HANDOFF_MIND.md) | Archived handoffs. | Historical |
| [HANDOFF_NEXT.md](HANDOFF_NEXT.md) | The 2026-06-07 master handoff — **self-declared superseded** at the top. | Historical (→ archive candidate) |
| [HANDOFF_OSINT_SOURCES.md](HANDOFF_OSINT_SOURCES.md) | 2026-06-16 handoff for the OSINT sources wiring (now merged). | Historical (→ archive candidate) |
| [handoff/](handoff/) | Dated session checkpoints (`CHECKPOINT_2026-06-16_bb-width-squeeze.md`, `local-session-2026-06-13.md`). | Historical |
| [CHECKPOINT_2026-06-16_rho-bar-merge.md](CHECKPOINT_2026-06-16_rho-bar-merge.md) | Dated merge checkpoint. | Historical (→ archive candidate) |
| [REVIEW_2026-06-15.md](REVIEW_2026-06-15.md) | Dated app-review snapshot. | Historical (→ archive candidate) |
| [OPEN_THREADS.md](OPEN_THREADS.md) | 2026-06-07 open-threads/ideas registry. | Historical-leaning (dated; cross-check against current state) |
| [DERIVATIVES_PLAN.md](DERIVATIVES_PLAN.md) | The perp-carry derivatives plan — MASTER_PLAN flags it as **a historical reference, not the current priority**. | Historical reference |
| [runs/](runs/) | Raw run artifacts (`llm_narrative_verdict_deep.{json,log}`). | Historical (artifacts) |

---

_Maintenance: when you add a top-level doc, add a row here. When a dated checkpoint/review/handoff goes stale,
move it to `docs/archive/` and update its row. The architecture module tree maintains itself
(`python3 -m cosmu.docs.codebase_map`)._
