# Point-in-time honesty audit — are the REAL signals tradeable live?

_For each real alt-data metric in prod `alt_data` (READ-ONLY): availability lag (available_at−ts), whether history was back-filled (ingested long after it was 'available'), and whether the source revised (same ts → multiple available_at / value). This decides whether a backtest edge could actually be traded live or is a look-ahead mirage. `pit_audit.py`._

| metric               |       n | ts                     |   lag_med_d |   lag_max_d | ingest_span            |   ingest_lag_med_d |   rev_ts_aa |   rev_ts_val | verdict                                                                                        |
|:---------------------|--------:|:-----------------------|------------:|------------:|:-----------------------|-------------------:|------------:|-------------:|:-----------------------------------------------------------------------------------------------|
| fear_greed           |    1007 | 2023-09-05..2026-06-08 |           1 |           1 | 2026-06-01..2026-06-08 |              502.3 |           0 |            0 | REVIEW — history backfilled (values may differ from what was live; ok if source never revises) |
| funding_rate         |   98836 | 2023-09-12..2026-06-08 |           0 |           0 | 2026-06-01..2026-06-08 |              463.3 |           0 |            0 | REVIEW — history backfilled (values may differ from what was live; ok if source never revises) |
| galaxy_score         | 1042191 | 2020-01-01..2026-06-06 |           1 |           1 | 2026-06-06..2026-06-06 |              843.5 |           0 |            0 | REVIEW — history backfilled (values may differ from what was live; ok if source never revises) |
| social_volume        | 1336313 | 2020-01-01..2026-06-06 |           1 |           1 | 2026-06-06..2026-06-06 |              790.6 |           0 |            0 | REVIEW — history backfilled (values may differ from what was live; ok if source never revises) |
| social_sentiment     | 1023393 | 2020-01-01..2026-06-06 |           1 |           1 | 2026-06-06..2026-06-06 |              629.5 |           0 |            0 | REVIEW — history backfilled (values may differ from what was live; ok if source never revises) |
| vix_level            |     988 | 2022-08-04..2026-06-03 |           1 |           1 | 2026-06-05..2026-06-05 |              701   |           0 |            0 | REVIEW — history backfilled (values may differ from what was live; ok if source never revises) |
| dxy                  |     958 | 2022-08-01..2026-05-29 |           1 |           1 | 2026-06-05..2026-06-05 |              705   |           0 |            0 | REVIEW — history backfilled (values may differ from what was live; ok if source never revises) |
| fed_funds_rate       |    1000 | 2023-09-08..2026-06-03 |           1 |           1 | 2026-06-05..2026-06-05 |              501   |           0 |            0 | REVIEW — history backfilled (values may differ from what was live; ok if source never revises) |
| btc_hashrate         |    6368 | 2009-01-03..2026-06-13 |           1 |           1 | 2026-06-14..2026-06-14 |             3187.2 |           0 |            0 | REVIEW — history backfilled (values may differ from what was live; ok if source never revises) |
| btc_active_addresses |    6342 | 2009-01-03..2026-06-13 |           1 |           1 | 2026-06-14..2026-06-14 |             3178.2 |           0 |            0 | REVIEW — history backfilled (values may differ from what was live; ok if source never revises) |
| defi_tvl             |    1003 | 2023-09-10..2026-06-08 |           1 |           1 | 2026-06-05..2026-06-08 |              500.3 |           0 |            0 | REVIEW — history backfilled (values may differ from what was live; ok if source never revises) |


## The decisive layer — does the SOURCE revise? (backfill is only safe for immutable sources)

The whole history was back-filled in one ~June-2026 scrape, all stamped available_at = ts+1d. The `read_asof`
join is therefore mechanically PIT-correct (no future row leaks). The ONLY remaining risk is whether the stored
(2026-scraped) value differs from what the source actually published live at ts+1. That depends entirely on
whether the **source revises history**:

| Signal | Source | Revises history? | Live-tradeable? |
|---|---|---|---|
| **fear_greed** | alternative.me | **No** (daily index fixed once published) | ✅ **YES** — backfill = live value |
| **funding_rate** | Binance | **No** (realized settlement, immutable) | ✅ **YES** |
| **vix_level / dxy** | market prices (FRED) | **No** (a close is a close) | ✅ **YES** |
| **fed_funds_rate** | policy rate (FRED) | **No** | ✅ **YES** |
| **galaxy_score / social_volume / social_sentiment** | **LunarCrush** | **YES — vendor backfills/rewrites social history** | ⚠️ **NO — look-ahead suspect**; the scraped value is the *revised* one |
| **defi_tvl** | **DefiLlama** | **YES — re-states recent days as chains re-sync** | ⚠️ **REVIEW** |
| **btc_hashrate / btc_active_addresses** | blockchain.com | **Mildly** (estimates smoothed as late blocks settle) | ⚠️ **REVIEW** (the +1d lag absorbs most) |

**Bottom line for trading:** `fear_greed`, `funding_rate`, `vix`, `dxy`, `fed_funds` are **genuinely live-tradeable** — you could have acted on those exact values at the bar. The **LunarCrush social signals are the trap**: they had some of the highest backtest IC, but their history is back-filled *and* the vendor revises, so that "edge" is partly look-ahead and is **NOT tradeable as stored**. To use social honestly: ingest it **live going forward** (available_at = actual fetch time, append-only) and **discount/exclude the back-filled social history** from any backtest. This is precisely the "post-date-created metric we can't trade on" risk — and it lives in the social feed, not in fear&greed.

## How to read it

- **TRADEABLE-LIVE / LAGGED-OK** — available_at is honest (settlement value, or a real publication lag); a backtest using read_asof would only ever see values knowable at the bar. Safe to trade.
- **REVIEW** — either back-filled history (we didn't capture it live, so trust it only if the source NEVER revises) or stamped available_at≈ts (confirm the publisher truly has zero lag).
- **SUSPECT** — revised history AND/OR instant-stamp = silent look-ahead. An edge built on these is NOT tradeable live; the backtest saw values that didn't exist yet. Do NOT trade on these without fixing the available_at stamping (LunarCrush social is the classic offender — vendor backfills/revises).


_Funding is settlement-stamped (available_at==ts is CORRECT). fear_greed/FRED should carry a +1d/release lag. LunarCrush social is the one to scrutinize — if it shows instant-stamp + revisions, the social edge in the composite is partly look-ahead and must be discounted._

