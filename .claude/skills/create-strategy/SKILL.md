---
name: create-strategy
description: Author a new trading strategy as a typed StrategySpec and flow it through the Gate. Use when the user wants to add a strategy idea, hypothesis, or edge to COSMU (by brief, or by hand-writing a spec/inbox file).
---

# create-strategy

Author a `StrategySpec` (the typed hypothesis contract) and let the deterministic Gate judge it. **No magic numbers** — every threshold lives in `param_space` and is fit from data.

## When to use
The user describes a trading idea ("fade crowded perp funding", "ORB breakout on BTC") and wants it tried.
Usually reached via `/strategize` (the single intake router that classifies the intent); reach for this directly only when you already know the spec shape.

## The Creation Contract (don't forget stuff)
Every spec MUST clear `validate_spec` (`cosmu/strategy/static_check.py`) — it is the machine-enforced floor on every authoring path (chat/inbox/pine/compiler). Authoring at scale means filling these *deliberately*, not letting defaults silently swallow them:

| Field | Rule | Why |
|------|------|-----|
| `rationale` | **non-empty** — the disconfirmable WHY ("signal X predicts return Y because …") | the thesis the Gate tests + the summary is written from; empty ⇒ rejected (`empty_rationale`) |
| `entry` | **≥1 Condition**, every threshold a `ParamRef` into `param_space` | a spec with no entry never fires; a literal threshold ⇒ rejected (`literal_threshold`) |
| features | reference registry names **only** (`cosmu/config/feature_registry.py`) | unknown feature ⇒ rejected (`unknown_feature`); keeps spec ↔ data bound |
| `param_space` | every `ParamRef` resolves here; **no magic numbers** | the Finder fits them — never hardcode an entry/exit number |
| `universe` | `venues` + `asset_classes`; `min_instruments ≥ 5` | this is what fees are priced against (`catalog.venue_for`) |
| `horizon` | `bar_size` ∈ {1h,4h,1d}; `1 ≤ min_hold ≤ max_hold` | — |
| `lane` | `gate` (novel, in-sample) vs `deploy` (documented, decades OOS) — pick deliberately | routes to the correct evaluator; default `gate` |
| `catalyst` | set it for `event`/`carry` edges (advisory) | what makes the trade fire |
| `direction` | `1` long/spot · `-1` short/perp · `0` signal-decides | a `-1`/perp leg needs a funding/borrow cost — don't leave carry unmodelled |
| `funding_feature` | set when the perp funding leg matters | accrues PIT funding P&L (long pays, short receives) |

**Use the standard words** — facets (`signal_family`, `edge_type`, `lane`, `direction`, `asset_class`, `timeframe`) are *derived* from the spec, never hand-tagged; their closed value sets are in `docs/GLOSSARY.md` → "Taxonomy facets". Author so the facets come out right; don't invent new vocabulary.

**Never try the same strategy twice** — the deterministic `novelty_gate` runs on the author path. For an **agent batch** (`authored_by="agent"`, e.g. `strategize` theme batches) a too-similar-to-a-dead-end candidate is a **hard reject** (the inbox flood guard); for a human re-running a known structure on purpose it's advisory. Before authoring a variant, check what's already been tried (the leaderboard facets / `docs/STRATEGIES.md` campaign memos) so you don't re-walk a killed structure.

**Fees are always real** — the Gate scores **net of per-venue maker/taker fees + slippage** (PIT `venue_fees`, else the catalog tier); a ranking is not a promotion. Set the `universe.venues` honestly so the right fee is charged.

## Steps
1. **Pick the authoring path:**
   - *Plain-language brief* → `POST /lab/author` (deterministic template match; LLM proposes structure only if a key is set). See `cosmu/lab/author.py`.
   - *By hand* → drop a `*.md` / `*.json` / `*.pine` file in `apps/engine/strategies/inbox/` (scanned on boot). See `apps/engine/strategies/inbox/README.md`.
2. **Compose from named building blocks**, don't re-derive structure: declare `setup` (e.g. `ma_trend_filter`, `orb`, `fvg_retest`) and `exit.plan` (`multi_tp`, `break_even+runner`) — see `docs/GLOSSARY.md` "Composable module". Reference features by name from `cosmu/config/feature_registry.py` only.
3. **Keep thresholds in `param_space`** (`cosmu/strategy/spec.py`): every entry/exit number is a `ParamRef` fit by the Finder grid, never a literal. `static_check` rejects magic numbers.
4. **Set the universe** (`spec.universe.venues` + `asset_classes`) — this is what the screen prices fees against (`catalog.venue_for(...)`).
5. **Screen it:** run the Finder (`python3 -m cosmu.lab.finder --seed-real`) or a cohort (`POST /evolution/run`). Survivors must clear the Gate (deflated Sharpe, PBO, holdout, FDR) — ranking ≠ promotion.

## Verify
- `cd apps/engine && python3 -m pytest tests/test_composable_specs.py tests/test_strategy.py -q`
- The spec compiles (`compile_spec`) and `static_check` passes (no blocked imports, no magic numbers).
- It appears in `/strategies` at the right stage; a gate-passer earns its own standalone Track.

## The standardized-freedom guardrails (author at scale, never make a mess)
- **Creation contract:** every `StrategySpec` carries a REQUIRED `rationale` (the *why*) and ≥1 entry condition — `cosmu/strategy/spec.py`; a spec missing them won't construct.
- **Novelty:** `novelty_gate` (`cosmu/knowledge/memory.py`) prunes a candidate too similar to a recent dead-end or a live spec — enforced by the screening cohort (not the drafter), so a batch fan-out can't flood near-duplicates into the FDR budget. Compose something structurally distinct.
- **Facets are DERIVED, never hand-tagged:** signal-family ∈ Social · News/Events · Math/Price · Macro/Positioning · On-chain/Flow, plus edge-type/asset/venue/timeframe — all read off the spec (`cosmu/strategy/taxonomy.py`).
