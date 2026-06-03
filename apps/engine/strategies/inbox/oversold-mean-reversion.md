---
name: Oversold mean reversion
strategy: buy statistically washed-out selloffs in liquid names when crowd fear is high
rationale: >
  At the swing horizon, statistically unusual selloffs in liquid spot names tend
  to revert once sentiment is washed out. Combine an oversold oscillator with a
  band z-score for "statistically unusual," and require crowd fear to confirm the
  capitulation. Long-only, mean-reversion (no trend filter — this fades, not follows).
universe:
  venues: [binance]
  asset_classes: [crypto]
  min_liquidity_usd: 5000000
  min_instruments: 5
horizon:
  bar_size: 1d
  min_hold_days: 2
  max_hold_days: 10
catalyst: capitulation selloff with washed-out sentiment
modules: [multi_tp]
entry:
  - feature: {name: rsi, lookback: {param: rsi_lookback}}
    op: lt
    threshold: {param: rsi_floor}
  - feature: {name: bb_z, lookback: {param: bb_lookback}}
    op: lt
    threshold: {param: bb_floor}
  - feature: {name: fear_greed}
    op: lt
    threshold: {param: fear_floor}
exit:
  stop_loss: {param: stop}
  take_profit: {param: tp2}
  time_stop_days: {param: time_stop}
  signal_exits:
    - feature: {name: rsi, lookback: {param: rsi_lookback}}
      op: gt
      threshold: {param: rsi_exit}
param_space:
  # oversold
  rsi_lookback:     {kind: int,   lo: 5,    hi: 30,   step: 1}
  rsi_floor:        {kind: float, lo: 15.0,  hi: 40.0}
  rsi_exit:         {kind: float, lo: 50.0,  hi: 70.0}
  # statistically unusual
  bb_lookback:      {kind: int,   lo: 10,   hi: 40,   step: 1}
  bb_floor:         {kind: float, lo: -3.0,  hi: -1.0}
  # sentiment confirmation
  fear_floor:       {kind: float, lo: 10.0,  hi: 35.0}
  # multi_tp
  tp1:              {kind: float, lo: 0.02,  hi: 0.08}
  tp2:              {kind: float, lo: 0.04,  hi: 0.18}
  tp_size_1:        {kind: float, lo: 0.4,   hi: 0.7}
  # exit
  stop:             {kind: float, lo: 0.02,  hi: 0.1}
  time_stop:        {kind: int,   lo: 2,    hi: 14,   step: 1}
---

# Oversold mean reversion

**Thesis.** Liquid names that sell off into a statistically unusual zone while
the crowd is fearful tend to bounce at the swing horizon. We fade the move, not
follow it — so no trend filter.

**Why these features.** `rsi` (`lt rsi_floor`) marks oversold; `bb_z`
(`lt bb_floor`) marks "statistically unusual" distance from the mean;
`fear_greed` (`lt fear_floor`) confirms washed-out sentiment — buy fear.

**Modules.** `multi_tp` to scale out as the reversion plays out. Exit on `rsi`
recovering past `rsi_exit`, a stop, a take-profit, or the time stop.

Every threshold is a param fit by the Finder; the gate ranks on deflated Sharpe.
