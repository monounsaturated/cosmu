---
name: Event-entry template (news/OSINT breaker)
strategy_kind: event
strategy: enter on a typed MarketEvent (e.g. a high-magnitude cryptopanic headline) and exit on the spec's stop/take/time
rationale: >
  This is the first-class EVENT strategy TYPE — distinct from an indicator
  strategy, but scored by the SAME gate. The entry does NOT read a price/TA
  feature; it fires when a typed MarketEvent matching `event.entry.filter`
  became KNOWN to us in a bar's interval (joined point-in-time on `available_at`,
  never the event's own publish `ts` — a scraped archive is honestly available
  at scrape time, never backdated). The exit reuses ordinary ExitRules, so the
  backtest produces an identical BacktestMetrics shape. Replace the filter and
  thesis below with your event hypothesis.
universe:
  venues: [binance]
  asset_classes: [crypto]
  min_liquidity_usd: 10000000
  min_instruments: 5
horizon:
  bar_size: 4h
  min_hold_days: 1
  max_hold_days: 7
catalyst: a high-magnitude, directional news/OSINT breaker
# The event payload. `entry.filter` is the typed predicate over a MarketEvent:
#   source        — the event provider (gdelt | cryptopanic | rss | xai_twitter | polymarket | ...); omit for any
#   kind          — the extractor's typed event_type; omit for any
#   min_magnitude — require the extractor's surprise/magnitude in [0,1] to clear a floor; omit for no floor
#   direction     — require the extractor's signed claim (-1 | 0 | +1); omit for any side
# `cooldown_bars` collapses one clustered news burst into one trade (>=0; 0 = re-fire every matching bar).
event:
  entry:
    filter:
      source: cryptopanic
      min_magnitude: 0.6
      direction: 1
    cooldown_bars: 6
# Event entries carry NO price/TA condition by default — the trigger is the event match itself. Add ordinary
# entry conditions here only to additionally GATE the event (they are AND-ed after the event trigger); leave the
# list empty for a pure event entry.
entry: []
exit:
  stop_loss: {param: stop}
  take_profit: {param: tp}
  time_stop_days: {param: time_stop}
  signal_exits: []
risk:
  max_concurrent_positions: 3
  max_position_pct: 0.05
  conviction: 0.5
param_space:
  stop:      {kind: float, lo: 0.03, hi: 0.14}
  tp:        {kind: float, lo: 0.05, hi: 0.30}
  time_stop: {kind: int,   lo: 1,    hi: 14, step: 1}
---

# Event-entry template

**Thesis.** A typed market event — a high-magnitude, directional breaker — is the
catalyst; price reacts after we *know* about it. The edge (if any) is in the
window between an event becoming known to us (`available_at`) and the market
fully pricing it. This template fires a long on a matching `cryptopanic` headline
with extractor magnitude ≥ a floor and a bullish directional claim, then manages
the trade with an ordinary stop / take-profit / time-stop.

**Why an event type, not an indicator.** An indicator strategy reads a numeric
price/TA/alt feature each bar; an event strategy reads the *event timeline*. The
match is point-in-time on `available_at` — the honest trading clock — so the
backtest can never trade on an event before we received it. Everything
downstream (the split/holdout, PBO, deflated Sharpe, the FDR cohort gate) is
identical to an indicator strategy: the event TYPE only changes how the entry is
generated, never how it is scored.

**Filter knobs.** `source` pins the provider; `kind` the typed event_type;
`min_magnitude` the extractor's surprise floor; `direction` the claimed side.
Omit any to leave it unconstrained. `cooldown_bars` makes one news burst one
trade. All exit thresholds are params — the Finder fits the stop, target, and
time-stop from data. No magic numbers.
