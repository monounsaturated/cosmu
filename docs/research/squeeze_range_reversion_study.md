# Study — `bb_width` squeeze + `range_position` reversion on real bars (2026-06-16)

**Question:** do the two grid-bot-video-inspired specs (commits `c6c74df`, `5fbb5fc`) carry any tradeable spot edge net of fees?

**Method:** real Binance **4h** bars, **8 symbols** (BTC/ETH/SOL/BNB/XRP/ADA/DOGE/LTC; AVAX/LINK dropped on fetch timeout), **3000 bars each (≈500 days, 2025-02 → 2026-06)**. 48-variant deterministic grid per spec via the real `build_grid`, pooled across symbols, Binance spot taker **10 bps** + default slippage/impact. Raw `run_strategy_backtest_detailed` — NOT the deflated cohort gate (which is stricter and applies BH-FDR). Fees verified to flow (oos_return 0bps +0.36% → 10bps +0.18% → 100bps −1.49%).

## Result — no tradeable spot edge (the designed-correct "0 survivors", now measured)

| | Squeeze-release | Range-floor accumulation |
|---|---|---|
| best-variant net OOS | −0.56% | +0.04% |
| buy & hold (same window) | −48.6% | −48.6% |
| sharpe | −0.51 | 0.02 |
| max drawdown | 3.0% | 3.8% |
| profit_factor | 0.68 | 1.01 |
| PBO | 0.497 | 0.469 |
| holdout deflated-Sharpe | 0.281 | −0.469 |
| variants net-positive | **0 / 42** | **1 / 48** |
| median PF | 0.47 | 0.52 |

Both "best" variants are noise-level / overfit: PBO sits right at the 0.50 chance line, holdout DSR is near-zero or negative (vs the 0.95 gate bar), and ~0 of the grid is net-positive. There is **no edge** — neither would survive the honest gate. This loosens nothing ([[gate_calibration_locked]]); it confirms the features are correctly wired (they compute, the specs trade, fees apply, the gate metrics are sane) and the limit is signal, not plumbing.

## The one honest, non-trivial observation

Over a window where buy-&-hold lost **−48.6%**, both specs sat at **~flat P&L with 3–4% max drawdown**. The squeeze gate + ADX regime-break exit did exactly what the video prescribes — **they stayed out of the down-trend**. But on a **spot-only** book, "avoid the crash" = "be in cash" = **no return** (flat ≠ alpha). The capital-preservation behaviour only converts to profit with a **short leg (perps)** or **cross-asset rotation** — which is the known spot-only binding wall again ([[strategy_research_direction]], [[next_phase_plan]]).

## Takeaways

1. `bb_width` and `range_position` are now real, validated bar-TA features in the vocabulary — available to the autonomous finder / matrix_search. They earned a fair test and produced a clean negative.
2. Do **not** add more squeeze/range-family specs — that lane is measured and dry on spot.
3. The high-value next lever is **not** more entry features; it is a **short/perp venue** (so the regime-avoidance becomes a profit) or the locked research direction (xsec momentum + funding-contrarian + meta-labeling).

## Repro

`/tmp/squeeze_range_study.py` (one-off; public klines, unverified SSL for the sandbox proxy). Not committed — re-derivable from this note. A `cost_ratio` reporting quirk (the metric field reads 0.000 even though fees demonstrably flow through `oos_return`/PF) is worth a separate look but does not affect this verdict.
