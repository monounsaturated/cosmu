# Strategy Inbox

Drop a strategy file here and the engine picks it up. Each file is one **Version** of a **Strategy** (see `docs/GLOSSARY.md`).

## How it works

- Accepted file types: `*.md` (YAML front-matter + thesis prose), `*.json` (raw spec), `*.pine` (TradingView Pine — auto-translated, thresholds lifted into a fitted `param_space`).
- The inbox is **scanned on deploy/boot.** Each file is parsed to a `StrategySpec`, run through `static_check`, then enters the Lab.
- Flow: `inbox → static_check → Lab → Finder → Gate`. A Version that clears the **Gate** earns its own standalone **Track** — a $100k SIM forward-test (no pooled wallet, no cross-strategy allocation). **Live stays off** until armed.
- These are **data files**, not code. The engine owns the scanner that reads them; authors only write the spec.

## The format (`.md`)

YAML front-matter carries the typed spec; the body is human-readable thesis notes. The front-matter mirrors `StrategySpec` (`apps/engine/cosmu/strategy/spec.py`). To author one, follow the **create-strategy** skill (`.claude/skills/create-strategy/SKILL.md`). The hard rules:

- **No magic numbers** — every threshold is a `param` in `param_space`, fit from data.
- **`stop_loss` and `take_profit` are REQUIRED** in `exit`.
- **Named features only** — every `feature` must exist in the feature registry and be valid for the `asset_classes`.
- **`min_instruments >= 5`**; valid horizon (`min_hold_days >= 1 <= max_hold_days`).
- Declare **composable modules** (`multi_tp`, `break_even+runner`, `ma_trend_filter`, `orb`, `fvg_retest`, `fvg_multiple`) instead of re-deriving structure; every param a module needs goes in `param_space`.

## Seed files (the documented format, internally consistent with the spec contract)

- `orb-fvg-multiple.md` — ORB + FVG-multiple, upside-only (the video strategy).
- `funding-gated-momentum.md` — momentum gated by a crowded-funding long filter.
- `oversold-mean-reversion.md` — washed-out mean reversion.

Each declares its thesis + named features + composable modules + a `param_space` with no magic numbers.
