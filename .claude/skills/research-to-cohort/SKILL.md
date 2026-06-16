---
name: research-to-cohort
description: Automated idea→edge loop — fan out a deep web/tweet/data research pass (via a Claude Code sub-agent), turn the findings into N typed StrategySpecs, batch-backtest them, route the whole cohort through the deterministic FDR Gate, and report survivors with fees. Use when the operator wants to "generate and backtest 50 strategies at once" on a theme, or run continuous automated research. Propose-only; the Gate alone funds.
---

# research-to-cohort

One command from a theme to a gate verdict. **The LLM proposes; the deterministic FDR Gate disposes.**
Volume cannot manufacture a winner — every candidate is registered as a trial and deflated against the
running count (deflated Sharpe + cohort Benjamini-Hochberg). This skill orchestrates; the engine decides.

## When to use
- "Generate + backtest 50 strategies on funding dispersion."
- "Go find an edge in the alt-data we already ingest."
- Continuous automated research (run it on a cadence, or fan out several themes in parallel).

## Inputs
- A **theme** (free text), or "open" to let research pick.
- `N` (default 50, cap 64 per `lab/strategize.py:_MAX_BATCH`).
- Compute lane: **Modal** (`pnpm modal:sweep`, parallel — preferred) or **local** (`matrix_search --sweep`,
  serial — fine for small N / offline).

## Steps

1. **Deep research (a Claude Code sub-agent).** Launch the global `deep-research` skill inside an Agent
   (`subagent_type: general-purpose`, `run_in_background: true`) on the theme. **Always feed it real data +
   web + tweets**, not just the model's priors:
   - web search (the research bus uses Tavily; the operator may also want the global WebSearch tool),
   - the **already-ingested** signals (`twitter_sentiment`, funding, fear/greed, macro, on-chain — query the
     store; $0, PIT-honest),
   - xAI/Grok LiveSearch for fresh tweets if `XAI_API_KEY` is set.
   Ask it for **N falsifiable theses, each with a disconfirmer and the named feature(s) it rides** (no
   data-mined "weather" features without a prior mechanism — `MASTER_PLAN.md:5`).

2. **Author N typed specs.** Turn each thesis into a `StrategySpec` and write to
   `apps/engine/strategies/inbox/`. Preferred once built (see `docs/LOCAL_AGENT_PROMPT.md` Task C):
   ```bash
   PYTHONPATH=apps/engine python3 -m cosmu.lab.batch --n 50 --theme "<theme>" --gate
   ```
   Today (until `lab/batch.py` lands): `python3 -m cosmu.lab.strategize "<theme>" --n 50 --gate`
   (authors + screens), or seed by hand via `scripts/seed_inbox_strategies.py --write` (validates every
   spec against the real compiler first — nothing magic-number'd or inert lands).
   **Every spec needs a `rationale` + ≥1 entry condition + thresholds in `param_space` (no magic numbers).**

3. **Batch backtest + Gate.** Route the whole inbox through the honest cohort gate:
   - **Modal (parallel, preferred):** `pnpm modal:sweep --assets <broad perp universe> --timeframes 1d`
     (fan-out — Task B). **Point it at the alt-joined feature space** (the unsearched ~75 features), not the
     exhausted bar-TA grid — that's where a *novel* survivor could still live.
   - **Local (serial):** `PYTHONPATH=apps/engine python3 -m cosmu.research.matrix_search --sweep`
     (set `MATRIX_SWEEP_ASSETS` / `MATRIX_SWEEP_TIMEFRAMES` to widen). Heavy → prefer Modal/cloud over the M2.

4. **Read the verdicts (the truth, not a hand count).** Survivors + metrics land in `gate_verdicts` /
   `backtests`. Read them via the engine API / MCP (`leaderboard`, `gate_verdicts`) or `/verdicts`,
   `/strategies` in the web app. A candidate that clears `score()` but fails BH-FDR across its cohort is
   **demoted** — that is the machine working, not a bug.

5. **Report (ranked, with fees, honest).** Per `AGENTS.md` communication style:
   - **#1 survivors** (if any): name, net-of-fee edge, the venue + `fee_bps`/`slippage_bps` it was screened
     against, the disconfirmer it beat.
   - **#2 the budget line:** what this run cost (LLM tokens via `/costs`, Modal seconds) — "always say fees."
   - **#3 honest null:** if 0 survived, say so plainly (most mined theses die at the honest Gate — expected).
   - Next move: evolve a survivor (`/evolve-strategy`), or a new theme on genuinely new data.

## Guardrails (do not cross)
- **Never** add a path that scores specs **outside** the trial ledger / `promote_cohort` — that is the
  anti-p-hacking FDR brake. More drafts = more false positives, not more winners.
- **Never** put an LLM in the scoring/gate/funding path. It proposes structure only; thresholds are fitted.
- **Never** display or fund synthetic data. Empty = say so.
- **Don't** re-run exhausted/null surfaces (astro, spot funding-carry, regime) — search new data, not the
  same grid tweaked until it clears (that contaminates the holdout).

## Parallel themes (fan out)
Run several themes at once: one Agent (`isolation: "worktree"`, `run_in_background: true`) per theme, each
authoring to inbox on its own branch, then a single Modal sweep over the merged inbox. **One branch per
agent; never two agents in one working tree.** See `/fan-out` for the merge train.

## Verify
- The report names survivors-or-honest-null read from `gate_verdicts` (never a hand count), every survivor
  carries its screened `fee_bps`/`slippage_bps`, and the run's cost is stated.
- Every authored spec passed `validate_spec` (no magic numbers, ≥1 entry, required `rationale`).
- Nothing was funded by anything other than the deterministic Gate.
