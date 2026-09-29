# intent: the realtime lane (realtime-data-lane epic P3) — an in-process, OFF-by-default recording worker:
# Binance WS closed candles → bars_intraday, budget-guarded poll collectors → market_events/alt_data, a 60s
# heartbeat, and retention. It RECORDS, never executes; the crons remain the fallback lane when it is off/dead.
