# Polymarket alt_data coverage — 2026-06-05

## AUDIT RESULT: DATA TOO THIN — lead-lag analysis blocked

### Actual DB state (queried live from Supabase, 2026-06-05)

| metric | rows | ts range | notes |
|--------|------|----------|-------|
| `pm_implied_prob` | 7 | 2026-06-05 only | intraday snapshots, not daily candles |
| `pm_book_depth` | 7 | 2026-06-05 only | intraday snapshots |
| `risk_on` | 6 | 2026-06-01 → 2026-06-05 | intraday snapshots |
| `pm_prob_velocity` | **0** | — | not present |

### Root problems

1. **No historical backfill run** — the ingest pipeline exists (fixed in #89) but the
   historical CLOB fetch (`fidelity=1440&interval=max`) was never executed against
   production. Only the live ingest cron has fired.

2. **`ts` is the ingest timestamp, not a date bucket** — rows record the exact ingest
   moment (`2026-06-05T15:09:17.425846+00:00`) not a daily bucket
   (`2026-06-05T00:00:00+00:00`). This makes daily grouping unreliable.

3. **`pm_prob_velocity` absent** — requires at least two distinct daily rows to derive.

### Previous coverage doc was incorrect

The doc written alongside #89 claimed 380 rows / GO verdict — that reflects intended state
after a backfill, not actual DB state. No backfill was ever run in production.

### What the lead-lag analysis needs

| requirement | min threshold |
|-------------|---------------|
| daily `pm_implied_prob` (one row per calendar day, ts = midnight UTC) | ≥ 180 days |
| `pm_prob_velocity` (day-over-day delta, one row per day) | ≥ 179 days |
| paired observations vs Binance daily closes | ≥ 60 paired obs |

### How to unblock

```bash
# From repo root — fetches full CLOB history per discovered market, writes daily rows
cd apps/engine
PYTHONPATH=. python3 -m cosmu.ingest.run --provider polymarket_clob --backfill-days 365
```

After backfill: re-run `scripts/polymarket_leadlag.py` to compute lead-lag.
Signal threshold: |r| ≥ 0.12 at any lag 1-7d → author StrategySpec.

### No StrategySpec authored

Insufficient data. Policy: no manufactured result. Spec pending valid backfill.
