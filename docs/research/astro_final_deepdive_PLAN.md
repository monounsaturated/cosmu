# Astro final deep-dive — PREPARED PLAN (not executed)

_Prepared on request. NOT run yet. Goal: the single most exhaustive, definitive astro pass — every asset class,
every astro parameter — so the conclusion is unimpeachable, while building live-honest infrastructure that is
valuable regardless of the (near-certain null) astro outcome. Honest ETA + cost below. **No duplication** of what
the 32-asset daily / 152k-config / composite / event-study / lunar-vol work already covered._

## Honest expected outcome (read this first)
**~95% probability: a documented null.** More search → harder deflation (the math is `expected best raw Sharpe ≈
sqrt(2·ln N)/sqrt(T)`; the Deflated Sharpe charges exactly that). We already searched 152k configs and the one
candidate died under a proper null. The REAL value of this run is NOT finding astro gold — it's (a) closing astro
definitively across the full universe + full parameter space, and (b) building the **minute-bar + full-universe +
live-honest-data infrastructure** the *real* strategies need. If you only care about astro, the EV is ~0; if you
value the infra + definitiveness, it's worth it. I will not pretend otherwise.

## What is NEW vs already done (no duplication)
| Already done | NEW in this dive |
|---|---|
| 32 assets, DAILY bars | **400+ Binance pairs + small/micro-caps; ~1m & 1h bars** (100× the data) |
| crypto + equity ETFs | **+ individual stocks (S&P + small-cap), Polymarket, FX, commodities/futures** |
| 126 deterministic astro features, 5 schools | **full param space**: Vedic nakshatra(27)/dasha, Gann SQ9, Merriman signature-counts, sidereal toggle, ALL aspect angles {0..180} × orbs {1,3,6,10}, asteroids, planetary-hours, full cross-sectional **natal** |
| daily IC / backtest / deflation | **+ vol/turnover event-studies at intraday resolution; belief-attention layer** (Google-Trends astro terms, live social) |
| local + Modal | **Modal feature-tensor → R2 Parquet lake** (DuckDB columnar sweeps) |

## Data plan & volumes
- **Crypto 1m**: `data.binance.vision` bulk ZIPs, ~400 USDT pairs since listing. Raw ~50–100 GB CSV → **~10–15 GB Parquet/zstd** on R2. Checksummed, free download, no rate limit.
- **Crypto 1h + daily**: derived from 1m (cheap).
- **Stocks**: daily free (Stooq/Tiingo); minute needs **Polygon paid (~$30–200/mo)** — DECISION REQUIRED (skip if daily suffices).
- **Polymarket**: free Gamma+CLOB API; thin/short history (weeks–months per market) — exploratory only, ~MB.
- **Astro tensor**: keep **DAILY** (astro barely moves intraday; minute astro is wasteful). ~6,000 days × ~500 features ≈ **~25 MB**. Computed once on Modal, written to R2.
- **Belief layer**: Google-Trends astro terms (free, rate-limited, SLOW; snapshot append-only); live LunarCrush forward (NOT backfilled — see lesson below).

## Compute plan (Modal)
- Feature tensor: 1 Modal job, market-wide, embarrassingly parallel by date-range. ~minutes.
- Backtest sweep: market-wide signals are vectorized + cheap; the cost is the **cross-sectional natal** (per-asset × 400) + **permutation/phase-shuffle nulls** (B=1000) on candidates + the belief-ML.
- Estimate: **~30–80 Modal container-hours** (8-CPU/16 GB).

## ETA & COST (the numbers you asked for)
| Item | Estimate |
|---|---|
| **Wall-clock ETA** | ~1 day: data download ~3–6 h (bulk, parallelizable) · feature tensor ~15 min · full sweep ~2–4 h on Modal · analysis ~1 h |
| **Modal compute** | **~$30–100** (30–80 container-hrs @ ~$0.40/container-hr, 8-CPU; scale-to-zero idle = $0). Big-B nulls are the swing factor. |
| **R2 storage** | **~$0.25/mo** (~15 GB @ $0.015/GB-mo) + ~$5 one-time write ops. **Egress = $0** (R2's advantage). |
| **Supabase** | ~$0 incremental for compute, but the first pull of the real-alt panel for 400 symbols moves the ~13 GB `alt_data` over the pooler — **cache to R2 once** to avoid repeat egress; stays within plan. |
| **Stocks minute (optional)** | Polygon **$30–200/mo** — only if intraday equities matter; SKIP for daily. |
| **Total to run once** | **~$35–110 one-off + ~$1/mo storage** (Polygon optional, not included). |

## Pre-registered design (so it can't become a p-hack)
- Every config tagged `school`, `pure_astro` vs `wider_event`, asset-class, cap-bucket, regime.
- **Deflated Sharpe at the TRUE trial count** (every config × asset × encoding counted) — and report the count.
- Proper nulls: **phase-shuffle** (not fake-random) for cyclic features; shuffled-natal placebo for cross-sectional.
- OOS holdout + (if any survivor) a forward (paper) test before any claim.
- Pre-registered kill: if 0 survive deflation across the full universe (expected), astro is closed permanently.

## What I will NOT do
Run it now (you said prepare). Use backfilled/revising data as a *predictor* (look-ahead — see lesson). Loosen the
gate to manufacture a survivor. Trade real money.
