---
name: strategize
description: The ONE front door for strategy intake — chat a vibe, paste a URL or Pine script, say "find me something on funding", or "generate N from a theme". It classifies the intent, routes to the right existing skill, authors typed StrategySpecs, and runs them through the deterministic Gate. Use whenever the operator wants to turn an idea (any shape) into a tested strategy and isn't sure which specific skill to reach for.
---

# strategize

One command, any input shape. The operator shouldn't have to know whether their idea is a "dump-idea" or an "import-pine" — `/strategize` reads the input, **routes to the right existing skill**, authors typed `StrategySpec`s, and hands them to the deterministic Gate. **No magic numbers** (thresholds always live in `param_space`), everything **tracked** (an audited event per spec), nothing judged here (the Gate alone disposes).

This is a **thin orchestrator**: it REUSES the sibling skills' machinery — it never reimplements the scorer, the Gate, the translator, or the author.

## The router (single source of truth)

`cosmu/lab/strategize.py:strategize(...)` does the deterministic classification + offline authoring. The CLI:

```
PYTHONPATH=apps/engine python3 -m cosmu.lab.strategize "<input>" [--n N] [--theme T] [--llm] [--gate]
```

`classify_intent` maps the input to one of six intents, each owned by an existing skill:

| Input shape | Intent | Routes to | Authored offline? |
|---|---|---|---|
| Loose idea / "fade crowded funding" | `vibe` | [`dump-idea`](../dump-idea/SKILL.md) | ✅ one spec → inbox |
| "generate 5 from a funding theme" (`--n`/`--theme`) | `batch` | [`create-strategy`](../create-strategy/SKILL.md) | ✅ N specs → inbox |
| Pasted Pine source (`//@version=`, `strategy(...)`) | `pine` | [`import-pine`](../import-pine/SKILL.md) | ✅ translate → inbox |
| A URL | `url` | [`pine-from-url`](../pine-from-url/SKILL.md) | ⛔ needs a live fetch |
| "find me something on funding" / "what to try next" | `scan` | [`scan-signals`](../scan-signals/SKILL.md) | ⛔ propose-only sweep |
| "evolve / compound the winner" | `evolve` | [`evolve-strategy`](../evolve-strategy/SKILL.md) | ⛔ needs a cohort + FDR |

The **authorable** intents (`vibe`, `batch`, `pine`) are fully handled offline by the router — it drafts the typed spec(s) (reusing `draft_from_brief` / `translate_pine`, so magic numbers are lifted into `param_space`) and writes them to `apps/engine/strategies/inbox/` as `.json`, recording a `strategize_authored` event each. The **delegated** intents (`url`, `scan`, `evolve`) need a page fetch / the cross-asset Gate / a FarmLoop cohort, so the router returns a route that names the sibling skill and you drive it.

## Steps

1. **Run the router** on the operator's raw input:
   `python3 -m cosmu.lab.strategize "<their words>"` (add `--n`/`--theme` for an explicit batch, `--gate` to screen immediately).
2. **If authored** (`vibe` / `batch` / `pine`): the spec(s) are already in the inbox and tracked. Report what was authored and the file paths. Run `/run-gate` (or `--gate`) to get the stop-or-go verdict; otherwise the next boot scan / autonomy tick gates them.
3. **If delegated** (`url` / `scan` / `evolve`): invoke the named sibling skill to finish the job (it owns the network/Gate work). The router has already told you which one and why.
4. **Batch mode — "Claude Code authors, cheap LLM formats":** the router seeds N falsifiable briefs from the theme (distinct economic angles). With a model key set (`--llm`), `draft_from_brief`'s cheap-LLM seam formats each brief's structure; offline, the deterministic template author runs. Either way every spec is re-validated (no magic numbers) before it's written.

## Invariants

- **Thin.** Reuses `dump-idea` / `create-strategy` / `import-pine` / `pine-from-url` / `scan-signals` / `evolve-strategy` — never duplicates them. The router only classifies + composes.
- **No magic numbers.** Every authored spec passes `validate_spec` (thresholds are `ParamRef`s into `param_space`) before it lands in the inbox.
- **Tracked.** Each authored spec records a `strategize_authored` event; the inbox scanner records `inbox_imported` when it gates them.
- **Judges nothing.** strategize routes and authors; the deterministic Gate (CSCV-PBO + deflated Sharpe + cohort FDR) alone decides what earns money.
- **Offline-safe.** The authoring path needs no keys/network; clamps a runaway batch to a sane cap.

## Verify

- `cd apps/engine && python3 -m pytest tests/test_lab_strategize.py -q`
- Authored specs appear in `apps/engine/strategies/inbox/` and clear `validate_spec`; a `--gate` run shows them screened in the `CohortSummary` (the Gate, not this skill, decides survival).
