# Orthogonal-data edge hunt — 2026-06-14

**TL;DR:** Acted on the handoff's "need orthogonal data, not more sweeps." Established ground-truth prod
coverage (the orthogonal buckets were genuinely empty), deep-backfilled BTC on-chain (27k points,
2009→2026), authored + honestly gated 3 never-before-tested bounded-feature capitulation specs, and
re-ran the correlation scan with the new data. **Result: 0 survivors.** The famous Fear & Greed
contrarian has negative OOS edge net of fees; on-chain fundamentals carry *less* apparent information
than the astro non-causal control. The binding constraint is confirmed: **regime depth (one cycle) +
the spot taker-fee wall**, not search effort or missing data.

## 1. What was actually empty (ground truth, not local cache)
`manage_data.py verify --json` against **prod Postgres** (the recon agents had read the 536K local
cache, which is misleading). Populated, deep: funding (95k), FRED macro (6.6k), stooq cross-asset (7k),
fear&greed (1k), defillama (1k), polymarket (1.1k), astro control (5k). **Zero rows** (registered but
never ingested): open_interest, perp_spot_basis, **blockchain.com on-chain**, **coingecko dominance**,
coinglass, lunarcrush (under venue-pair symbols), gdelt, cryptopanic, reddit, xai. So several surfaces
the prior campaign called "exhausted" were in fact **DATA-BLOCKED, never gated**.

Bridge limitation found: the ingest bridges for on-chain / coingecko / etf_flows / stablecoin_flows are
**snapshot-only** (`_snapshot` → one latest point), so the scheduled `fetch` forward-accrues and never
backfills — which is why these stayed at 0 rows. The *providers themselves* can return full history
(`OnchainBlockchainSource.fetch_raw_series`, `timespan="all"`).

## 2. Deep on-chain backfill (new durable asset)
`scripts/_deep_onchain_backfill.py` — one-off honest-PIT deep pull (`available_at = ts + 1 day`,
idempotent `_append_fresh`, reversible by `provider="blockchain.com"` tag):

| metric | points | span |
|---|---|---|
| btc_hashrate | 6,368 | 2009-01 → 2026-06 |
| btc_tx_count | 6,354 | 2009-01 → 2026-06 |
| btc_active_addresses | 6,342 | 2009-01 → 2026-06 |
| btc_mempool_size | 8,000 | 2026-03 → 2026-06 (short endpoint) |

**27,064 points total**, now in the prod alt-store. Follow-up (clean): wire a proper `backfill=` on the
`onchain_blockchain` SourceSpec so it stays fresh idempotently (mirror the wikipedia/weather pattern),
instead of the one-off script.

## 3. Three new specs, honestly gated (pooled grid, 10bps taker, real holdout)
Authored to respect the bounded-feature discipline (a fitted threshold on a *bounded, mean-reverting*
feature genuinely binds — raw drifting levels like defi_tvl/on-chain/credit_spread are the
always-true/false trap, and credit_spread is registry-tagged equity-only). All low-turnover → low fee
drag (the shape that fits the spot fee wall). Each gated as a **pooled grid** across 8 crypto majors
(market-wide signal → real trade count), reusing `build_grid` + `run_strategy_backtest_detailed` +
`promote_cohort` (`scripts/_gate_new_specs.py`).

| spec | best in-sample dSR | honest holdout (champion) | verdict |
|---|---|---|---|
| Fear & Greed extreme-fear long | 0.474 | **−0.487** | dead — buy-the-dip reverses OOS |
| VIX-spike capitulation long | 0.744 | **−0.464** | overfit decay (best-holdout +0.37 = snooping across 96 variants) |
| F&G + VIX composite | 0.626 | thin (≤31 trades) | trade-starved, insufficient evidence |

**0 promoted.** The headline negative: the canonical retail **Fear & Greed contrarian has no
out-of-sample edge net of fees** — it's "buy the dip" that worked in the 2023-25 bull and reversed in the
held-out recent slice.

## 4. Quantifying the new data (correlation scan, round 2)
`correlation_scan` with on-chain populated: **972 tests, 64 survived BH-FDR (q=0.10)** — but the
survivors are dominated by **h=20 level features over a single 2023-26 cycle**. The decisive control:

- `btc_hashrate` IC **−0.35** @ h=20 (n=49), **did NOT survive FDR**, 0 on-chain tests survived.
- `astro_jupiter_longitude` (NON-CAUSAL control) IC **−0.36** @ h=20 — *larger* than on-chain.

On-chain fundamentals carry **less apparent information than a known-false astrology baseline**. Because
astro's h=20 IC is pure single-cycle co-trending, on-chain at the same magnitude is the **same artifact,
not signal**. This also re-frames the scan's 64 "survivors" (defi_tvl, spx/ndx, gold) as largely
**single-cycle position proxies** — exactly what the Gate's purged holdout kills (§3 confirmed it).

## 5. Conclusion + the real levers
The daily-level orthogonal-data axis — **including genuinely-new deep on-chain** — hits the **same wall**
the prior campaign found: regime depth (one cycle) + the spot taker-fee wall. More daily features won't
break it; the astro control proves the high-IC ones are cycle artifacts.

**Where the money actually is (unchanged, now re-confirmed):**
1. **True intraday microstructure** (order-flow / book imbalance / volume-profile) — a *different
   information regime*, not daily levels. The binding daily-thinness unlock.
2. **A short-capable venue** (Hyperliquid perps / IBKR) for the **market-neutral xsec signal that was
   real (dSR 0.25, genuinely neutral) but killed by spot-only** — the one validated direction.
3. **Deeper / cross-market regime history** — the single 2023-26 crypto cycle is the statistical
   bottleneck; a PIT survivorship-free equity dataset unblocks the equity-factor lane.
4. **The deploy-lane TAA fleet remains the real compounding floor** (PAA 1.09 / DAA 1.23 Sharpe OOS).

The machine refused everything honestly again — that disposition is the durable asset.
