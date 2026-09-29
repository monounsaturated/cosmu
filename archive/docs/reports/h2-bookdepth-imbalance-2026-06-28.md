# H2 — Resting book-depth imbalance (FOLLOW the wall) on small-cap perps

**2026-06-28 · EXPERIMENT ONLY · ZERO production impact** — offline kill/confirm experiment, persists nothing
to prod, no Gate constant touched, no behaviour changed. The code is the harness + a reusable keyless
bookDepth fetcher, not a wired strategy. DO NOT MERGE as a strategy; this is an autonomous-run experiment.

- Harness: `apps/engine/scripts/research/h2_bookdepth_imbalance_2026_06_28.py`
- Fetcher (new, reusable): `apps/engine/cosmu/data/intraday_bookdepth.py`
- Raw numbers: `apps/engine/scripts/research/h2_bookdepth_imbalance_results_2026_06_28.json`

## TL;DR — KILL

**0/7 cells cleared the BRUT Gate · gross edge ≈ 0 with the WRONG sign (mean −0.53 bps/trade) · real net edge
is statistically INDISTINGUISHABLE from the rotation-null (mean real−null = −0.22 bps) → KILL.**

Resting book-depth imbalance within ±2% of mid carries **no usable directional information** about the
short-horizon (5-minute) forward return on these small-cap perps. The pre-registered "follow the wall"
strategy (long a bid-dominant book, short an ask-dominant book) is **negative or ~zero GROSS on every one of
the 7 cells before a single basis point of fees** (mean gross −0.53 bps/trade), so there is nothing for even a
zero-fee book to harvest, let alone a maker round-trip. The disconfirmer is decisive: each cell's real net
edge sits right on top of its own circular-rotation null (which preserves the imbalance's full distribution +
autocorrelation but breaks its alignment to price) — the depth→price relationship is **absent**, not merely
fee-bound. At both the locked Gate fee (30 bps round-trip) and the realistic perp-maker sensitivity (14 bps
round-trip), every cell is deeply loss-making.

This is a **valid, valuable negative result on a genuinely distinct mechanism**. H1/H1b found executed
aggressive trade flow is a real-but-too-weak signal (~2 bps/min, shuffle-confirmed). H2 finds the *resting
passive* book imbalance is **not even a real signal** on this universe/horizon — weaker than H1's flow,
not stronger. That closes the resting-book-depth-imbalance branch.

## The hypothesis (pre-registered, no sweep)

A GENUINELY DISTINCT mechanism from H1/H1b (which faded executed AGGRESSIVE trade flow): H2 trades the
standing PASSIVE limit-order liquidity. Mechanism, stated before any result was seen:

> When resting **bid** depth dominates resting **ask** depth within a tight ±band of mid, the book carries a
> support wall + queue pressure that the microstructure literature (Cont–Kukanov–Stoikov 2014, *"The Price
> Impact of Order Book Events"* — order-book imbalance positively predicts the next price move) says drifts
> price **up** on a short horizon. So H2 trades **WITH** the depth imbalance (long a bid wall, short an ask
> wall) — directionally **opposite** to H1's executed-flow fade, matching the documented OBI sign. This is
> hypothesis diversity, not a re-spin of the killed flow-fade.

Pre-registered knobs, locked before any return was computed — **one** config, **no** best-of-N sweep:

| Knob | Value |
|---|---|
| Book band | ±2% of mid (Vision publishes ±1..±5%; ±2% = near-touch but stable) |
| Imbalance | (mean within-band BID depth − mean within-band ASK depth) / total, base-asset qty |
| Signal | trailing **15-minute mean** of the per-minute imbalance (smooths transient pulled walls) |
| Entry threshold | \|imbalance\| ≥ **0.20** (one threshold) |
| Direction | **FOLLOW**: imbalance ≥ +0.20 → LONG; ≤ −0.20 → SHORT |
| Horizon | **5 minutes** fixed-time exit; no overlapping positions (min-gap = 5m) |
| Universe | same 7 small-cap perps as H1: SEI ARB FIL GALA RUNE JUP OP |
| Window | 2025-02-01 … 2025-03-31 (~59 days, ~85k 1m bars/cell) |
| Disconfirmer | circular-rotation null on the imbalance series, K=200 |
| Fee (gate) | Binance catalog maker 10 bps + 5 bps slippage = **30 bps round-trip** |
| Fee (sensitivity) | realistic perp maker 2 bps + 5 bps slippage = **14 bps round-trip** (NOT the gate number) |

> **Pre-registration note on the threshold.** The raw ±2% imbalance is structurally slightly bid-biased on
> perps (an inspected ARBUSDT day had mean +0.11, std ~0.05, range ≈ [−0.13, +0.28]). 0.20 was chosen *before*
> any return was scored as "the upper tail of a typical day's trailing-mean imbalance" — it is not a swept
> value. Because the bias is positive, entries skew long; the rotation-null preserves this bias exactly, so
> the disconfirmer remains a fair test of *alignment*, not of the marginal.

## Data — REAL, keyless, point-in-time

Binance Vision **bookDepth** (USDⓈ-M futures tree), the only keyless historical resting-book series, joined to
the parallel **1m perp klines** on the minute (bookDepth carries no price). Both are knowable at the minute's
close — PIT-clean. Coverage was essentially complete (join kept ~84.8k of ~85.0k theoretical 1m bars per cell;
the small shortfall is genuine Vision snapshot gaps, never zero-filled).

| Field | Detail |
|---|---|
| bookDepth schema | `timestamp, percentage, depth, notional`; 10 rows/snapshot at pct ∈ {±1..±5} |
| bid/ask | percentage < 0 = bid band (below mid); > 0 = ask band (above mid) |
| depth / notional | cumulative resting base-qty / USD out to the band (we read the outermost row ≤ band) |
| cadence | ~30s snapshots (≈2880/day), resampled to 1m (mean over the minute's snapshots) |
| price | `intraday_binance_vision.fetch_1m_bars(market="perp")` — same USDⓈ-M instrument |
| revision safety | immutable daily zips, no revision (matches the #462 feasibility spike finding) |

## Per-cell results (the BRUT Gate, priced at the locked 30 bps fee)

All numbers are mean **per-trade** unless noted. `net30` is the GATE number (catalog fee); `net14` is the
realistic-perp-maker SENSITIVITY (clearly NOT the gate number — see below). `shuf_mean` = mean net edge over
the K=200 rotation-null; `p` = one-sided P(null ≥ real); `DSR` = deflated-Sharpe probability (Gate floor 0.95).

| Symbol | trades | gross (bps) | **net30 (bps)** | net14 (bps) | shuffle null (bps) | p | DSR | promoted |
|---|---:|---:|---:|---:|---:|---:|---:|:--:|
| SEIUSDT  |  3,139 | −1.18 | **−31.18** | −15.18 | −30.35 | 0.891 | 0.000 | ❌ |
| ARBUSDT  |  1,689 | −0.29 | **−30.29** | −14.29 | −30.27 | 0.527 | 0.000 | ❌ |
| FILUSDT  |  7,717 | −0.25 | **−30.25** | −14.25 | −30.29 | 0.433 | 0.000 | ❌ |
| GALAUSDT | 14,447 | −0.62 | **−30.62** | −14.62 | −30.37 | 0.995 | 0.000 | ❌ |
| RUNEUSDT |    397 | −0.67 | **−30.67** | −14.67 | −30.12 | 0.572 | 0.000 | ❌ |
| JUPUSDT  | 14,880 | −0.42 | **−30.42** | −14.42 | −30.47 | 0.363 | 0.000 | ❌ |
| OPUSDT   | 16,836 | −0.27 | **−30.27** | −14.27 | −30.32 | 0.040 | 0.000 | ❌ |

- **Anything cleared the BRUT Gate?** No — **0/7**. Every cell fails on `max_drawdown`, `folds_positive`,
  `pbo`, `deflated_sharpe`, AND `buy_and_hold` simultaneously. (The compounded net total return is ≈ −100% per
  cell: thousands of overlapping −30 bps round-trips drain the book — the fee drag alone, since gross ≈ 0.)
- **Gross sign.** 0/7 cells have positive gross edge. Mean gross = **−0.53 bps/trade**. The "follow the wall"
  direction is, if anything, mildly wrong — heavy resting bid depth does **not** precede an up-move here.
- **Disconfirmer.** Mean (real net − rotation-null) = **−0.217 bps** across the 7 cells: the real strategy is
  *worse* than its own alignment-broken null on average. The depth→return relationship is absent.

### The one p≤0.05 cell is NOT a survivor (honest read of OPUSDT)

OPUSDT shows p=0.040. This is a **false positive of the per-cell p-test, not an edge**: its real net edge
(−30.27 bps) is only **0.05 bps** above its rotation-null mean (−30.32 bps) — i.e. it "beats" the null by a
rounding-error margin while still losing 30 bps/trade. It does **not** clear the Gate (DSR 0.000, promoted
False). The pre-registered survivor rule requires `promoted=True AND p≤0.05 AND real>null` — OPUSDT fails the
first clause, so `survivor_cells = []` and the verdict is **KILL**. Reporting it transparently rather than
torturing it into a "1/7 distinguishable" headline.

## 30 bps vs 14 bps fee sensitivity (the gate fee vs the realistic perp maker)

The locked Gate prices Binance perps at the **spot** catalog (maker 10 bps + 5 bps slippage = 30 bps
round-trip). The realistic USDⓈ-M perp maker is ~2 bps (→ 14 bps round-trip). **The Gate verdict uses 30 bps;
14 bps is reported only as a transparent sensitivity — the Gate is never loosened.** It does not matter here:

| Fee scenario | round-trip | mean net edge (bps/trade) | cells profitable gross? | cells clearing Gate |
|---|---:|---:|---:|---:|
| Gate (catalog, spot schedule) | 30 bps | ≈ −30.5 | 0/7 | 0/7 |
| Sensitivity (realistic perp maker) | 14 bps | ≈ −14.5 | 0/7 | n/a |
| **Even a fictional 0 bps** | 0 bps | **≈ −0.53 (still negative)** | **0/7** | n/a |

The kill is **not a fee story**. Because the GROSS edge is negative/zero on every cell, the strategy loses
even at a zero fee. The 30-vs-14 distinction (which mattered for H1b's "real but too weak to pay the maker
round-trip") is moot here — there is no gross edge to pay any fee with.

## Verdict & wall

**KILL.** The specific wall: **signal absent / indistinguishable from null.** Resting book-depth imbalance
(±2% band, 15-min trailing mean, 5-min follow horizon) has no measurable directional relationship to
short-horizon forward returns on these 7 small-cap perps — gross edge ≈ 0 with the wrong sign, and the real
net edge collapses onto a circular-rotation null. This is a stronger kill than H1: H1's flow signal was *real
but sub-fee*; H2's depth signal is *not real* at this horizon.

### Is a fuller Modal run warranted?

**No.** A bounded Modal confirmation (more symbols / 6 months / other bands or horizons) is **not** warranted,
because the kill is on the *gross* sign + the rotation-null, not on power or sample size:
- 7 cells × ~85k bars × hundreds-to-thousands of trades each is already ample power; the rotation-null over
  K=200 is decisive per cell.
- The gross edge is ≈ 0 with the wrong sign on *every* cell — widening the universe or window cannot
  manufacture a sign that the mechanism doesn't have, and sweeping band/threshold/horizon to find a
  passing combo would be exactly the best-of-N overfit the locked discipline forbids.
- Spend the Modal budget on a *different axis*, not on torturing this one.

### State of the intraday-microstructure axis (for us)

The two reachable keyless intraday microstructure series are now both tested on small-cap perps:

| Series | Object | H-experiment | Result |
|---|---|---|---|
| aggTrades | executed AGGRESSIVE flow | H1 / H1b | real (~2 bps/min, shuffle-confirmed) but **too weak to pay the maker round-trip** → KILL |
| bookDepth | resting PASSIVE liquidity | **H2 (this)** | **no measurable signal** at this horizon → KILL |

**The intraday-microstructure axis is now exhausted-for-us on the maker-only, daily-cadence-Vision lane.**
Both the executed-flow and the resting-book branches are killed. What remains genuinely *untested* and
distinct is **not** another variant of these two signals (that would be p-hacking) but a different lane
entirely: a **taker/latency** lane (which we deliberately do NOT play — it needs colocation and is outside the
solo-bot edge thesis), or a **cross-venue book/flow divergence** (one venue's resting/aggressive imbalance vs
another's — a relative, not absolute, microstructure signal), which would need a *second* keyless intraday
source to pair against Binance Vision. Absent a new intraday data axis, the maker-only intraday-microstructure
space looks closed; the higher-leverage move is a new data axis (paid positioning / cross-venue), per the
2026-06-21 data-wall finding.

## Honesty checklist

- Gate untouched (`GateSettings()` defaults: DSR ≥ 0.95, min_trades ≥ 30, max_dd ≤ 25%, folds ≥ 60%, PBO ≤
  0.50, beat-B&H). Verdict routed per-(symbol×venue) through `metrics_for_run → promote_brut` (BRUT, no pooling).
- One pre-registered config, no sweep. Direction + threshold + horizon + band + exit locked before any return.
- Fees real, from `spine/venue.py`; gate at the catalog 30 bps, 14 bps shown only as a labelled sensitivity.
- Disconfirmer required + reported: circular-rotation null (preserves the imbalance marginal + autocorr,
  breaks only its price alignment), K=200, per-cell empirical p-value.
- Data keyless + PIT + revision-safe; gaps skipped, never zero-filled.
- No production side effects: reads keyless Vision zips, writes only a local bar cache + the results JSON.

---
🤖 Generated with [Claude Code](https://claude.com/claude-code)
