---
name: import-pine
description: Translate a TradingView Pine Script into a typed StrategySpec (magic numbers lifted into a fitted param_space). Use when the user pastes Pine code or wants to import a TradingView strategy.
---

# import-pine

Convert Pine → typed `StrategySpec`. **Key invariant:** Pine's hardcoded thresholds/lengths are **lifted into a fitted `param_space`** — magic numbers become a search space, never baked in.

## Two modes — pick by what the script IS

1. **Strategy** (entry/exit rules, `strategy.entry`/`strategy.close`, `ta.crossover` signals) → `StrategySpec` (this skill, below).
2. **Indicator** (the OUTPUT NUMBER is the signal — a classifier score, oscillator, custom-logic line; often `indicator(...)` with `plot`/boxes and no `ta.*` on the signal path) → a **computed data source** in `cosmu/research/pine_indicators/` (`compute(bars, **params) -> IndicatorResult`), NOT a StrategySpec.

The regex translator (`translate_pine`) is **lossy for indicators**: it flattens custom logic to `ret_Nd > 0` and can even misread null-guards (`atrVal > 0`) as entry signals. If a script's value is its number, port it as an indicator instead. The ML Liquidity Zone Classifier is the reference port (`ml_liquidity_zone.py`): faithful KNN confidence series, causal/non-repainting, with a `correlate()` harness so you MEASURE whether the number predicts forward returns before trusting it. Register new ports in `pine_indicators/__init__.py:INDICATORS`. A validated indicator earns a `feature_registry` entry (via `IndicatorResult.as_altdata`) — not before.

## Input is copy-paste only

TradingView renders Pine client-side, so URL scraping does not work (the old `/pine-from-url` is removed). Paste the source. To translate, either `POST /strategy/pine` for a preview, or drop a `.pine` file into `apps/engine/strategies/inbox/` for the scanner. **Copyright:** keep the raw `.pine` local; commit the translated `.json` spec (your own work), not verbatim MPL-2.0 Pine.

## "Create strategies from Pine?" — honest scope

Pine import does NOT discover strategies by volume. Bulk-importing community scripts is curve-fit junk that the Gate (correctly) kills ~all of — and it burns the multiple-testing budget the FDR/PBO brake depends on. Use it for: (1) **transcribing one mechanistic edge you already trust** into a spec, (2) **feature mining** (indicator mode above) so the existing evolution loop (`cosmu/evolution/` seeder/mutator/evolve) is what actually *creates* new strategies by recombining features — Pine widens the palette, it doesn't paint. Bulk path (for #1/feature seeds): drop N `.pine`/`.json` files in the inbox, then `python -m cosmu.lab.inbox` translates + screens all new ones in one idempotent cohort.

## Steps (strategy mode)
1. **Translate:** `POST /strategy/pine` (body: the Pine source) → `PineTranslateResponse` (name, indicators, conditions, `lifted_params`, the spec). Logic in `cosmu/strategy/pine.py:translate_pine`.
2. **What it maps:** `ta.*` → the feature registry; `input.*` vars and tuple destructuring (`[macd, signal, _] = ta.macd(...)`); band breakouts (`close > upper` → `bb_z`). Unsupported indicators surface as notes — don't silently drop them.
3. **Review the lift:** confirm every Pine literal became a `ParamRef` with sane bounds (`lifted_params`). Anything still hardcoded will be rejected by `static_check`.
4. **Sample library:** `GET /strategy/pine/samples` (`cosmu/strategy/pine_samples.py`) has community-style examples (RSI, MACD, golden cross, Bollinger, ADX) that are asserted to translate + compile.
5. **Flow it through:** the resulting spec goes inbox → static_check → Lab → Finder → Gate like any other (use create-strategy / run-gate).

5b. **What happens to the `.pine` after:** the file stays in `strategies/inbox/` as provenance (content-hash idempotency → imported exactly once; edit it → re-imports). The derived spec lives as audited events + Versions; the Gate alone decides survival.

## Verify
- Strategy mode: `cd apps/engine && python3 -m pytest tests/test_pine_and_author.py -q` — the translated spec compiles and the Finder can grid-search its `param_space`.
- Indicator mode: `cd apps/engine && python3 -m pytest tests/test_pine_indicators.py -q` — the ported number is bounded, causal/non-repainting (truncation-stable), and `correlate()` runs.
