---
name: ORB + FVG-multiple (upside-only)
strategy: opening-range breakout confirmed by stacked fair-value gaps
rationale: >
  After an opening-range breakout to the upside, price that has left multiple
  unfilled fair-value gaps below signals strong one-directional imbalance; a
  retest into the breakout that holds tends to continue. Long-only on spot.
universe:
  venues: [binance]
  asset_classes: [crypto]
  min_liquidity_usd: 10000000
  min_instruments: 5
horizon:
  bar_size: 1h
  min_hold_days: 1
  max_hold_days: 5
catalyst: opening-range breakout with multiple fair-value gaps
modules: [orb, fvg_multiple, multi_tp, break_even+runner]
entry:
  - feature: {name: ret_Nd, lookback: {param: or_window}}
    op: gt
    threshold: {param: breakout_buffer}
  - feature: {name: vol_realized, lookback: {param: fvg_lookback}}
    op: gt
    threshold: {param: imbalance_floor}
exit:
  stop_loss: {param: stop}
  take_profit: {param: tp2}
  time_stop_days: {param: time_stop}
  signal_exits:
    - feature: {name: rsi, lookback: {param: rsi_lookback}}
      op: gt
      threshold: {param: rsi_exit}
param_space:
  # orb
  or_window:        {kind: int,   lo: 3,    hi: 24,   step: 1}
  breakout_buffer:  {kind: float, lo: 0.001, hi: 0.02}
  # fvg_multiple
  fvg_lookback:     {kind: int,   lo: 6,    hi: 48,   step: 1}
  fvg_count:        {kind: int,   lo: 2,    hi: 4,    step: 1}
  retest_tol:       {kind: float, lo: 0.001, hi: 0.01}
  imbalance_floor:  {kind: float, lo: 0.01,  hi: 0.08}
  # multi_tp
  tp1:              {kind: float, lo: 0.02,  hi: 0.08}
  tp2:              {kind: float, lo: 0.06,  hi: 0.2}
  tp_size_1:        {kind: float, lo: 0.3,   hi: 0.7}
  # break_even+runner
  be_trigger:       {kind: float, lo: 0.01,  hi: 0.05}
  runner_trail:     {kind: float, lo: 0.01,  hi: 0.06}
  # exit
  stop:             {kind: float, lo: 0.01,  hi: 0.08}
  time_stop:        {kind: int,   lo: 1,    hi: 7,    step: 1}
  rsi_lookback:     {kind: int,   lo: 7,    hi: 21,   step: 1}
  rsi_exit:         {kind: float, lo: 70.0,  hi: 90.0}
---

# ORB + FVG-multiple (upside-only) — the video strategy

**Thesis.** An opening-range breakout (`orb`, upside-only) that leaves *multiple*
stacked fair-value gaps below it (`fvg_multiple`) shows decisive one-directional
buying. Entering on the breakout/retest and scaling out (`multi_tp`) while moving
the stop to break-even on the runner (`break_even+runner`) captures the
continuation while capping downside.

**Why these features.** `ret_Nd` over the opening-range window expresses the
breakout magnitude; `vol_realized` over the FVG lookback proxies the imbalance
that creates stacked gaps. `rsi` provides an overextension signal exit.

**Modules.** `orb` (range high break, long-only) · `fvg_multiple` (require
`fvg_count` gaps within `fvg_lookback`, enter within `retest_tol`) · `multi_tp`
(scale out `tp_size_1` at `tp1`, rest at `tp2`) · `break_even+runner` (move stop
to break-even after `be_trigger`, trail the runner by `runner_trail`).

No thresholds are fixed — every number lives in `param_space` for the Finder to fit.
