---
name: Funding-gated momentum
strategy: ride medium-term momentum only when perp funding is not crowded
rationale: >
  Medium-term momentum persists, but chasing it when perp funding is already
  extreme buys into a crowded, over-levered long that is prone to unwind. Use
  funding as a long FILTER (spot, long-only): take momentum entries only while
  funding sits below a fitted ceiling, and require a moving-average trend to align.
universe:
  venues: [binance]
  asset_classes: [crypto]
  min_liquidity_usd: 10000000
  min_instruments: 5
horizon:
  bar_size: 4h
  min_hold_days: 2
  max_hold_days: 14
catalyst: momentum continuation under non-crowded funding
modules: [ma_trend_filter, multi_tp]
entry:
  - feature: {name: ret_Nd, lookback: {param: mom_lookback}}
    op: gt
    threshold: {param: mom_floor}
  - feature: {name: funding_rate}
    op: lt
    threshold: {param: funding_ceiling}
  - feature: {name: ret_Nd, lookback: {param: ma_lookback}}
    op: gt
    threshold: {param: trend_floor}
exit:
  stop_loss: {param: stop}
  take_profit: {param: tp2}
  time_stop_days: {param: time_stop}
  signal_exits:
    - feature: {name: ret_Nd, lookback: {param: mom_lookback}}
      op: lt
      threshold: {param: mom_exit}
param_space:
  # momentum
  mom_lookback:     {kind: int,   lo: 10,   hi: 60,   step: 1}
  mom_floor:        {kind: float, lo: 0.01,  hi: 0.12}
  mom_exit:         {kind: float, lo: -0.05, hi: 0.01}
  # funding long filter
  funding_ceiling:  {kind: float, lo: 0.0001, hi: 0.01}
  # ma_trend_filter
  ma_lookback:      {kind: int,   lo: 20,   hi: 100,  step: 1}
  trend_floor:      {kind: float, lo: 0.0,   hi: 0.05}
  # multi_tp
  tp1:              {kind: float, lo: 0.03,  hi: 0.1}
  tp2:              {kind: float, lo: 0.08,  hi: 0.3}
  tp_size_1:        {kind: float, lo: 0.3,   hi: 0.7}
  # exit
  stop:             {kind: float, lo: 0.03,  hi: 0.14}
  time_stop:        {kind: int,   lo: 3,    hi: 21,   step: 1}
---

# Funding-gated momentum

**Thesis.** Momentum works, but not when everyone is already long. Perp
`funding_rate` is a fast read on crowded leverage; on spot (long-only) it is a
clean **filter** — only buy momentum while funding is below a fitted ceiling.

**Why these features.** `ret_Nd` over `mom_lookback` is the momentum trigger;
`funding_rate` (used as `lt funding_ceiling`) keeps us out of over-levered crowds;
a second `ret_Nd` over a longer `ma_lookback` is the `ma_trend_filter` alignment.

**Modules.** `ma_trend_filter` (only take entries aligned with the longer-horizon
trend) · `multi_tp` (scale out `tp_size_1` at `tp1`, remainder at `tp2`).
`funding_rate` is a long filter, never a short trigger.

All thresholds are params — the Finder fits the funding ceiling, the trend floor,
and the targets from data.
