---
name: create-strategy
description: Author a new trading strategy as a typed StrategySpec and flow it through the Gate. Use when the user wants to add a strategy idea, hypothesis, or edge to COSMU (by brief, or by hand-writing a spec/inbox file).
---

# create-strategy

Author a `StrategySpec` (the typed hypothesis contract) and let the deterministic Gate judge it. **No magic numbers** — every threshold lives in `param_space` and is fit from data.

## When to use
The user describes a trading idea ("fade crowded perp funding", "ORB breakout on BTC") and wants it tried.

## Steps
1. **Pick the authoring path:**
   - *Plain-language brief* → `POST /lab/author` (deterministic template match; LLM proposes structure only if a key is set). See `cosmu/lab/author.py`.
   - *By hand* → drop a `*.md` / `*.json` / `*.pine` file in `strategies/inbox/` (scanned on boot). See `strategies/inbox/README.md`.
2. **Compose from named building blocks**, don't re-derive structure: declare `setup` (e.g. `ma_trend_filter`, `orb`, `fvg_retest`) and `exit.plan` (`multi_tp`, `break_even+runner`) — see `docs/GLOSSARY.md` "Composable module". Reference features by name from `cosmu/config/feature_registry.py` only.
3. **Keep thresholds in `param_space`** (`cosmu/strategy/spec.py`): every entry/exit number is a `ParamRef` fit by the Finder grid, never a literal. `static_check` rejects magic numbers.
4. **Set the universe** (`spec.universe.venues` + `asset_classes`) — this is what the screen prices fees against (`catalog.venue_for(...)`).
5. **Screen it:** run the Finder (`python3 -m cosmu.lab.finder --seed-real`) or a cohort (`POST /evolution/run`). Survivors must clear the Gate (deflated Sharpe, PBO, holdout, FDR) — ranking ≠ promotion.

## Verify
- `cd apps/engine && python3 -m pytest tests/test_composable_specs.py tests/test_strategy.py -q`
- The spec compiles (`compile_spec`) and `static_check` passes (no blocked imports, no magic numbers).
- It appears in `/strategies` at the right stage; a gate-passer earns its own standalone Track.
