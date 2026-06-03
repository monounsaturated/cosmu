---
name: import-pine
description: Translate a TradingView Pine Script into a typed StrategySpec (magic numbers lifted into a fitted param_space). Use when the user pastes Pine code or wants to import a TradingView strategy.
---

# import-pine

Convert Pine → typed `StrategySpec`. **Key invariant:** Pine's hardcoded thresholds/lengths are **lifted into a fitted `param_space`** — magic numbers become a search space, never baked in.

## Steps
1. **Translate:** `POST /strategy/pine` (body: the Pine source) → `PineTranslateResponse` (name, indicators, conditions, `lifted_params`, the spec). Logic in `cosmu/strategy/pine.py:translate_pine`.
2. **What it maps:** `ta.*` → the feature registry; `input.*` vars and tuple destructuring (`[macd, signal, _] = ta.macd(...)`); band breakouts (`close > upper` → `bb_z`). Unsupported indicators surface as notes — don't silently drop them.
3. **Review the lift:** confirm every Pine literal became a `ParamRef` with sane bounds (`lifted_params`). Anything still hardcoded will be rejected by `static_check`.
4. **Sample library:** `GET /strategy/pine/samples` (`cosmu/strategy/pine_samples.py`) has community-style examples (RSI, MACD, golden cross, Bollinger, ADX) that are asserted to translate + compile.
5. **Flow it through:** the resulting spec goes inbox → static_check → Lab → Finder → Gate like any other (use create-strategy / run-gate).

## Verify
- `cd apps/engine && python3 -m pytest tests/test_pine_and_author.py -q`
- The translated spec compiles and the Finder can grid-search its `param_space`.
