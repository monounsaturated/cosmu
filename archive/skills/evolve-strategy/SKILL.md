---
name: evolve-strategy
description: Isolate a gate-passed strategy's winning signal, graft it onto other assets, recombine it with other survivors, and route the resulting cohort through the existing Gate. Use when you want to compound a proven edge — replicate what works — without letting volume manufacture a winner.
---

# evolve-strategy

The self-reinforcing core. Take ONE **gate-passed** survivor, **isolate its winning signal logic** (entry conditions + entry-setup modules + the `param_space` ranges they reference), then:

- **graft** that logic onto OTHER asset classes in the universe (features retargeted per the registry; a graft that loses every original feature is dropped, not emitted as a hollow spec), and
- **recombine** it with other survivors' exit/risk plumbing (proven entry, borrowed trade management).

The output is a **cohort of fresh `StrategySpec`s** — which is then handed to the **existing** `FarmLoop` Gate (screen → `score()` → cohort Benjamini-Hochberg **FDR**). This skill **never judges edge**: the deterministic Gate does, and FDR over the whole family is the brake so authoring more grafts per tick can't manufacture a winner.

## When to use
A strategy has cleared the Gate and you want to compound it — try the same edge on more markets / different exit plumbing — rather than start from scratch. **No magic numbers**: every grafted threshold stays a `ParamRef` carrying the parent's fitted range.

## Entry points (`cosmu/evolution/evolve.py`)
- `isolate_winning_logic(spec) -> WinningLogic` — pull out the transferable signal core.
- `evolve_survivor(survivor, *, siblings=None, seed=7, max_specs=16) -> EvolvedCohort` — deterministic cohort of grafts + recombinations. Pure; judges nothing.
- `run_evolution_cohort(farm_loop, survivor, *, siblings=None, seed=7) -> CohortSummary` — glue that routes `.specs` through `FarmLoop.run_cohort(extra_seeds=..., explore_pct=0.0)` (the EXISTING Gate). This is how the cohort reaches the Gate.

## Steps
1. **Pick a survivor.** Read a gate-passed `strategy_versions` row's `spec` (e.g. via the Curator query in `cosmu/lab/curator.py`) or pass a known `StrategySpec`. Optionally collect other survivors as `siblings` to recombine with.
2. **Evolve.** Call `evolve_survivor(...)` to get the deterministic `EvolvedCohort` (grafts onto other classes + recombinations). Inspect `.grafts`, `.recombinations`, `.dropped`.
3. **Route through the Gate.** Call `run_evolution_cohort(farm_loop, survivor, siblings=...)`. The evolved specs enter `FarmLoop.run_cohort` as `extra_seeds` (alongside the standard seed population) with `explore_pct=0.0` — screened, scored, and FDR-culled by the SAME deterministic path. Survivors earn their own standalone Tracks; the rest go to the graveyard with reasons.
4. **Read the verdict.** The returned `CohortSummary` reports `generated/passed/killed/kill_rate` and the survivor ranking. Ranking ≠ funding; a gate-passer still needs the 5 interlocks for live.

## Invariants
- This code **never** decides edge — the deterministic `score()` + FDR (in `FarmLoop`) is the sole judge. The Gate/scorer/FDR are **not** reimplemented or bypassed here.
- Deterministic + seeded: same survivor + `seed` → same cohort (sibling order doesn't matter).
- No magic numbers: grafted thresholds stay `ParamRef`s; `validate_spec` must be clean on every emitted spec.
- Volume can't manufacture a winner: the whole evolved family is one cohort under Benjamini-Hochberg FDR.

## Verify
- `cd apps/engine && python3 -m pytest tests/test_evolve.py tests/test_farmloop_fdr.py -q`
- Every emitted spec passes `validate_spec` (no magic numbers) and `compile_spec` (compilable).
- The cohort appears screened in the `CohortSummary` (`generated` = seed population + evolved specs) and the gate — not this skill — decides which survive.
