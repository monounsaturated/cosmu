# Polymarket CLOB Backfill Coverage

**Date:** 2026-06-05  
**Branch:** claude/heuristic-chandrasekhar-7ce1fc  
**Status:** DATA-UNBLOCKED — all three metrics pass profile-source with GO

## Depth Achieved

| metric | rows | span | first | last | verdict |
|---|---|---|---|---|---|
| pm_implied_prob | 380 | 398 d | 2025-05-03 | 2026-06-05 | **GO** |
| pm_prob_velocity | 379 | 397 d | 2025-05-04 | 2026-06-05 | **GO** |
| pm_book_depth | 380 | 398 d | 2025-05-03 | 2026-06-05 | **GO** |

Gap ratio: 5% (5 gaps / ~19 missing buckets across 380 daily rows — within the 10% threshold).  
Look-ahead violations: 0 (available_at == ts throughout).  
Revision safety: 0 same-ts revisions.

## What Changed

**Root cause of DATA-BLOCKED (#87):** `PolymarketClobProvider` was delegating to
`PolymarketGammaProvider.fetch_series()`, which returns only a single current-snapshot point
(the mean yes_prob of discovered markets right now). No historical data was ever fetched.

**Fix (`data/sources/polymarket.py`):**
- New `PolymarketClobSource` calls the Gamma API with the same events+keywords discovery logic
  as `PolymarketGammaProvider`, but preserves `clobTokenIds[0]` (the YES-outcome token) from
  each market.
- Per-market price history is fetched via:
  `GET https://clob.polymarket.com/prices-history?market={YES_token}&fidelity=1440&interval=max`
  The `interval=max` parameter returns the full history since market launch (free, no key,
  daily buckets at 1440-minute fidelity).
- The `market` parameter must be `clobTokenIds[0]` (the YES token ID, a large integer string).
  Neither the Gamma numeric `id` nor the hex `conditionId` work with this endpoint.
- History is aggregated daily: mean yes_prob across all discovered markets.

**`altdata.py` change:** `PolymarketClobProvider` is now a thin 2-line wrapper over `PolymarketClobSource`.

## Markets Discovered (as-of 2026-06-05)

| question | liquidity | rows | first |
|---|---|---|---|
| Xi Jinping out before 2027? | $165,936 | 308 | 2025-07-04 |
| Will China invades Taiwan before GTA VI? | $26,458 | 379 | 2025-05-03 |
| Trump eliminates capital gains tax on crypto before 2027? | $9,592 | 121 | 2025-12-31 |
| Kraken IPO by December 31, 2026? | $6,870 | 180 | 2025-11-20 |
| Will Pump.fun perform an airdrop by December 31, 2026 | $1,242 | 131 | 2025-12-31 |

**History limit:** Actively-open Gamma markets are used (closed=false, active=true). Currently the
oldest active macro market dates from 2025-05-03, giving ~13 months of aggregate signal.
Resolved (closed) markets are excluded — their post-resolution price would jump to 0/1 and
distort the feature. If more depth is needed, a future pass could include closed markets trimmed
at `closedTime`.

## PIT Semantics

`available_at = ts` — the daily midpoint price from a continuous CLOB is stamped at the start
of its 24h bucket (approximately 00:00 UTC), which is the observation timestamp. No declared
release lag; the profile-source PIT-lag check is advisory (`info` severity) and passes.

## Commands Used

```bash
# backfill (run from repo root)
PYTHONPATH=apps/engine python3 scripts/manage_data.py backfill polymarket_clob --days 730

# audit
PYTHONPATH=apps/engine python3 -m cosmu.ingest.profile_source \
    --altdata-root .cosmu/altdata polymarket MARKET pm_implied_prob
```
