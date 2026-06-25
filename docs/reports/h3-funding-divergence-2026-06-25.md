# H3 — Cross-venue funding divergence (fade the outlier-funding venue)

**2026-06-25 · EXPERIMENT ONLY · ZERO production impact** — offline event-study, persists nothing to prod,
no Gate constant touched, no behaviour changed. Docs-only PR; code is the harness, not a wired strategy.

- Harness: `apps/engine/scripts/research/h3_funding_divergence_2026_06_25.py`
- Raw numbers: `apps/engine/scripts/research/h3_funding_divergence_results_2026_06_25.json`
- Self-contained table: `apps/engine/scripts/research/h3_funding_divergence_table_2026_06_25.html`

## TL;DR — KILL

**N = 597 pooled events · reversion sign WRONG (gross −19.8 bps) · gross edge ≪ 160 bps fee hurdle → KILL.**

Fading the perp venue whose 8h funding is the outlier vs the cross-venue median does **not** predict a
mean-reverting spot move on Kraken. The pre-registered fade returns a **gross −19.8 bps** mean across 597
events — i.e. the signal points the wrong way (if anything the outlier venue's price mildly *continues*),
and even the best-case flipped (continuation) read is +19.8 bps gross, far below a single 80 bps round-trip,
let alone the 160 bps thesis hurdle. Killed cleanly on checks (b) and (c) in <1 day. This is structurally
orthogonal to the failed single-venue funding-**level** set, so the negative result is genuinely new — and
it confirms the divergence axis is also dead, at least at this horizon/threshold on a spot-only fade.

## The thesis (pre-registered, no sweep)

Fade the venue whose 8h funding is the outlier vs the cross-venue median; the spread mean-reverts as
KYC-siloed arbs slowly close it. Direction: a venue funding **above** the median ⇒ its perp is over-long /
expensive ⇒ **SHORT** the Kraken-spot reference (and the mirror for below-median). Pre-registered knobs,
locked before any result was seen — **one** threshold, **one** horizon, **no** best-of-N:

| Knob | Value |
|---|---|
| Outlier threshold | \|z\| > 2.0 |
| Forward horizon | 1 day (proxy for ~3×8h) |
| Z-window | trailing 30 days (point-in-time: uses only data strictly before the entry day) |
| Universe | 10 majors on ≥2 of 3 venues: BTC ETH SOL XRP DOGE ADA AVAX LINK DOT LTC |
| Median basis | cross-venue median over venues-with-data (≥2 required) |
| Reference price | Kraken-spot daily close (keyless, closed candle) |
| Fee | real Kraken taker 40 bps/leg → 80 bps round-trip; **hurdle = 2× = 160 bps** |

## Data — REAL, point-in-time, 8h-normalized

Three funding providers, all verified PIT-honest (`available_at == ts == fundingTime`; the exchange
publishes the **realized** rate at the funding instant — no revision, no look-ahead). Confirmed against each
provider docstring in `cosmu/data/providers/funding.py` and re-verified live this run.

| Venue | Source | Cadence | History reached |
|---|---|---|---|
| Binance USDⓈ-M | operator's local funding cache | 8h (BTC/ETH 4h) | ~731 days |
| OKX swap | public `funding-rate-history` REST | 8h | **~94 days (hard API cap)** |
| Kraken-Futures | public `historical-funding-rates` REST | **1h** | ~366 days |

Normalization (so the median is apples-to-apples): each venue's rates are summed into the canonical
00/08/16 UTC 8h buckets (two 4h Binance rates, or eight 1h Kraken `relativeFundingRate` values, sum into one
8h-equivalent), then averaged to one daily per-(asset,venue) funding. The cross-venue median is taken over
venues present that day (≥2). The z-score is computed per (asset,venue) on the trailing-30d spread, strictly
before the entry day.

### Notable data findings (honest caveats)

- **OKX caps funding history at ~94 days.** The public endpoint returns ~3 months regardless of `startTime`.
  So the *3-venue* median only exists in the recent window; across the full ~1–2yr span the median is
  Binance + Kraken-Futures (2 venues). The KILL holds on both the full set and the 3-venue subset (below).
- **Heterogeneous cadence.** Binance moved BTC/ETH to 4h funding mid-history; Kraken-Futures settles hourly.
  Both are handled by the 8h-bucket sum, but the cadence mismatch produces a few extreme early-window
  z-values (|z| up to ~30). Capping to \|z\|∈(2,8] does not change the verdict.
- **In-tree provider bug found (not fixed here — experiment is read-only):** `KrakenFuturesFundingRateProvider`
  in `cosmu/data/providers/funding.py` points at the stale URL `…/api/v3/historicalfundingrates` (the live
  endpoint is `…/derivatives/api/v3/historical-funding-rates`) and parses `row["timestamp"]` as int-ms +
  `row["fundingRate"]` (the absolute USD premium) instead of the ISO-8601 `timestamp` + per-interval
  `relativeFundingRate`. It silently returns `[]` today. The experiment uses a corrected inline fetch and
  changes no production code; a follow-up chip is filed to fix the provider.

## Results

Pooled basket (597 events, long 309 / short 288):

| Metric | Value |
|---|---|
| Pooled events N | **597** |
| Gross mean (fade-signed) | **−19.8 bps** |
| Gross median | −16.5 bps |
| Net mean (after 80 bps round-trip) | −99.8 bps |
| Fraction positive (gross) | 47.9% |
| Reversion sign correct? | **No** (gross < 0) |
| Gross > 160 bps hurdle? | **No** |

### The three honest checks

| Check | Bar | Observed | Result |
|---|---|---|---|
| (a) ≥30 pooled entries | N ≥ 30 | 597 | **PASS** |
| (b) reversion sign correct | gross mean > 0 | −19.8 bps | **FAIL** |
| (c) gross edge > 2× round-trip fee | > 160 bps | −19.8 bps | **FAIL** |

Because (b)+(c) fail, the basket was **never promoted to the BRUT Gate** — no DSR/PBO/PSR was computed.
That is the design: kill on the cheap checks, in <1 day, without touching a Gate constant.

### Per-asset (uniform — not an outlier artifact)

Signed fade gross return, ranked most-against-thesis first. 9 of 10 assets have a negative mean; all have
fraction-positive ≤ ~0.5. The thesis fails *everywhere*, not on one name (operator rule: per-asset detail,
never a hiding pooled mean).

| Asset | Events | Mean bps | Median bps | Frac positive |
|---|---|---|---|---|
| DOT  | 45 | −51.9 | −61.7 | 0.467 |
| AVAX | 68 | −35.4 | −32.3 | 0.456 |
| ADA  | 57 | −35.2 | −36.3 | 0.456 |
| LINK | 63 | −20.6 | −21.8 | 0.476 |
| BTC  | 64 | −17.4 | −11.6 | 0.469 |
| SOL  | 60 | −12.7 | −34.8 | 0.483 |
| ETH  | 74 | −10.8 |   8.2 | 0.527 |
| DOGE | 54 |  −9.7 |  −8.5 | 0.481 |
| XRP  | 50 |  −9.1 | −25.8 | 0.460 |
| LTC  | 62 |  −1.9 |   0.0 | 0.500 |

### Robustness (not a sweep for a winner — disconfirmers)

| Cut | N | Gross mean | Frac positive |
|---|---|---|---|
| All events | 597 | −19.8 bps | 0.479 |
| 3-venue median only | 212 | −46.5 bps | 0.458 |
| \|z\| ∈ (2, 8] | 573 | −20.6 bps | 0.478 |
| Both | 210 | −46.9 bps | 0.457 |

The cleaner 3-venue-median subset is *more* negative, not less — the signal is genuinely wrong, not a
thin-data artifact. Flipping to the continuation direction yields only +19.8 bps gross, still below one 80 bps
round-trip — so neither fade **nor** continuation is tradeable on the Kraken-spot reference at this horizon.

## Verdict — KILL (clean, <1 day)

The cross-venue funding-divergence fade does not work as a spot-only strategy at \|z\|>2 / 1-day horizon.
Spread divergence between KYC-siloed perp venues does **not** translate into a mean-reverting move on the
Kraken-spot reference net (or even gross) of fees. Killed on checks (b) and (c); never reached the Gate.

What would have to change for a re-open (explicitly **not** pursued now, to avoid best-of-N): the edge — if
any — is more plausibly a **perp-vs-perp** convergence trade (long the cheap-funding venue's perp, short the
rich one, harvesting the funding *carry* + basis convergence) than a spot directional fade. That is a
different instrument (two perps, two fee schedules, funding P&L on both legs), a different hypothesis, and a
different harness. This experiment cleanly closes the spot-fade reading of H3.
