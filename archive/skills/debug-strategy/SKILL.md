---
name: debug-strategy
description: Diagnose why a strategy isn't trading, isn't passing the Gate, or shows surprising backtest numbers. Use when a spec produces zero trades, gets killed, or its metrics look wrong.
---

# debug-strategy

Work the funnel backwards: compile → features → signals → trades → gate. The backtest is deterministic, so a fixed spec + bar cache reproduces exactly.

## Common failures, in order
1. **Won't compile / static_check fails** (`cosmu/strategy/static_check.py`): blocked import, or a **magic number** (a literal threshold not in `param_space`). Move it to a `ParamRef`.
2. **Zero trades:** in `cosmu/data/backtest.py` —
   - The feature is alt-data with **no point-in-time series** → it reads `None`, the condition can't fire (honest). Check the alt join (`align_asof`) and that the source actually ingested.
   - `_warmup_bars` ate the series (lookback too long for the bar count) — need more bars or a shorter lookback.
   - The `setup` gate (MA/ORB/FVG) never opens — loosen the param bounds.
   - It's **long-only spot**: a short-only idea produces nothing.
3. **Trades but killed by the Gate:** read the verdict reasons — failing deflated Sharpe, too few trades, drawdown over the bar, PBO too high, or it doesn't beat buy-and-hold. The Gate ranks by Score (deflated Sharpe); profit factor is display-only.
4. **Surprising returns:** fees are venue-derived (`catalog.venue_for(spec.universe.venues)`); slippage scales with participation (`_slippage`). A tiny `num_trades` makes Sharpe noisy — check `n_obs`.

## Tools
- Re-run one spec: `python3 -m cosmu.lab.finder --seed-real` or a targeted `run_strategy_backtest` in a scratch test.
- `/strategies/{id}` shows the spec, compiled code, trades, backtests, and holdout.

## Verify
- `cd apps/engine && python3 -m pytest tests/test_strategy.py tests/test_execute_stage.py -q`
