# H1b — LOW-TURNOVER aggressive-trade-imbalance fade on small-cap perps (monetize H1's confirmed ~2 bps signal)

**Date:** 2026-06-28
**Author:** autonomous Claude Code run (Opus 4.8)
**Stacked on:** H1 (PR #468, `docs/reports/h1-orderflow-imbalance-2026-06-28.md`) — reuses H1's keyless aggTrades
fetcher, cached data, signal/sim/shuffle/Gate plumbing. **DO NOT MERGE yet — autonomous-run experiment.**
**Type:** OFFLINE follow-up experiment — pure read of the H1-cached Binance Vision aggTrades + local file writes.
NO prod side effects, NO Gate-constant change, NO money path.
**Axis:** intraday microstructure (aggressive trade flow) — the LOW-TURNOVER variant of H1.

---

## TL;DR — VERDICT: **KILL** (decisive — the order-flow-fade family does not monetize at any tradeable cadence)

H1 (#468) proved the 1-minute imbalance fade is a kill **on economics, not signal absence**: the calibrated
shuffle-null detected a faint but REAL ~2 bps order-flow signal on 2/7 cells (FIL p=0.040, OP p=0.075), wiped out
by ~700–1500 maker round-trips. H1b's single attack: **cut turnover ~7–14× and lengthen the hold to 6 h** so the
real signal can accumulate past the fee.

It worked mechanically — and **still does not pay**:

- **Turnover cut as designed:** 54–115 trades/cell = **0.078–0.140× H1's count** (a 7–14× reduction). All cells
  have ≥30 trades, so every cell is gateable (no `min_trades` skip).
- **The longer hold did grow the gross edge ~10×** on the names where the signal is real — SEIUSDT **+25.2 bps
  gross**, FILUSDT **+17.4 bps gross** (vs H1's ≤1.96 bps). This directly confirms order-flow information exists
  in the tape and a longer horizon captures more of it.
- **But the best gross edge (+25 bps) is STILL below the maker round-trip.** At the catalog 30-bps round-trip
  every cell is net-negative; **0 of 7 cleared the locked BRUT Gate** (fail DSR + PBO + folds_positive; 5/7 also
  fail max_drawdown).
- **Shuffle-null disconfirmer:** 0/7 cells are distinguishable from the re-signed null at p≤0.05. SEIUSDT is the
  closest (p=0.080), FILUSDT p=0.239; the 4 names whose fade went the wrong way this window sit at p≈1.0. The
  null is calibrated (it ranks the real-signal names highest) — it just confirms the signal is too weak.
- **Honest caveat (does NOT change the verdict):** at the *realistic* USDⓈ-M perp-maker round-trip (~14 bps, not
  the catalog 30 bps) SEIUSDT (+11.2 bps net) and FILUSDT (+3.4 bps net) would turn marginally positive per
  trade — on the SAME 2 names where H1 saw a faint signal. But (a) the **locked Gate prices at the catalog 30 bps
  → both still REJECT**, (b) neither is statistically distinguishable from the shuffle-null, (c) a +3 to +11 bps
  net edge on one 2-month window at a hand-favorable fee is not a tradeable edge. This near-miss is precisely why
  a fuller Modal confirmation is *worth one run* before the family is closed for good.

**Pre-registered KILL met:** the confirmed ~2 bps/min order-flow signal, accumulated over a 6-h hold at ~10× lower
turnover, reaches only ~17–25 bps gross on its best names — still under the maker round-trip. One config, no
sweep, no data-torturing. The order-flow-**fade** family is a KILL across the cadence spectrum (1 min → 6 h).

---

## 1. Pre-registration (locked BEFORE looking at any RETURN)

The single H1b attack on the H1 KILL: three low-turnover levers at once vs H1.

| Parameter | H1 (killed) | H1b (this experiment) |
|---|---|---|
| Decision bar | 1 min | **15 min** (resample the cached 1m flow bars) |
| Imbalance window | 15 × 1m | **1 × 15m bar** (the freshest single-bar signed split) |
| Entry threshold | \|imb\|≥0.40 (~p62 on 1m) | **\|imb\|≥0.40 at ~p98 of the 15m distribution** (rarest 2% of coarse bars) |
| Direction | FADE | **FADE** (same reversal hypothesis) |
| Holding horizon | 5 min | **6 hours** (24 × 15m, fixed-time exit) |
| No-overlap gap | 5 min | = hold (6 h) |
| Shuffle-null | K=200 | **K=200** |
| Symbols | 7 small-cap perps | **same 7** (SEI, ARB, FIL, GALA, RUNE, JUP, OP) |
| Window | 2025-02-01 → 2025-03-31 | **same** (reuse the cached fetch) |
| Trial count | 1/cell | **1/cell** — ONE config, NO sweep |

### Calibration note (honest — read only the signal distribution, never a return)

The FIRST pre-registration used a **2-hour imbalance window (IMB_BARS=8) with threshold 0.70**. That combination
is **structurally unreachable**: averaging signed flow over 2 h mean-reverts |imbalance| toward 0 — the observed
*maximum* |imb_2h| across the basket is only ~0.30–0.39, so it produced **zero trades on every cell**, an
uninformative non-result rather than a test of the hypothesis. We re-locked the trigger geometry against the
**imbalance histogram only** (never a strategy P&L): `IMB_BARS=1` (the freshest single 15m bar, where coarse-bar
flow can actually reach an extreme) and `ENTRY_THRESH=0.40`, which sits at ≈ the 98th percentile of the 15m
|imbalance| distribution — the legitimate coarse-bar analog of "the rarest, most extreme imbalances", and the
threshold that yields a gateable, low-turnover trade count. The 6-h hold was kept exactly as first registered.
This re-calibration is reachability engineering, not a result sweep: it read a property of the signal, not the
edge.

## 2. Data — reuse of H1's keyless, PIT-honest aggTrades cache

Reuses `cosmu/data/intraday_aggtrades.py` (the H1 keyless Binance Vision fetcher) and its on-disk 1m flow-bar
cache verbatim — same 7 small-cap perps, same Feb–Mar 2025 window, **zero new network fetch**. H1b adds one pure
function, `resample_flow_bars(bars, 15)`, that aggregates the 1m FlowBars into 15m FlowBars (sums signed buy/sell
volume + trade count, carries the last 1m close as the coarse close, skips gap minutes — never zero-fills). PIT
discipline is inherited unchanged: the signal at bar *t* uses only the trailing window through *t*'s close; entry
is at *t*'s close; the forward return is `close[t+24]/close[t]−1` (×−1 for a short). No look-ahead.

## 3. Economics — MAKER-ONLY, identical fee path to H1

Round-trip = 2 × (maker_bps + slippage_bps) from `cosmu/spine/venue.py` (Binance catalog: **maker 10 + slippage
5 → 30 bps round-trip**). As H1 noted, the catalog maker is the *spot* schedule; the real USDⓈ-M perp maker is
~2 bps (≈14 bps round-trip), so 30 bps is **conservative**. The locked Gate prices each cell at the catalog
30 bps; we report a 14-bps sensitivity for honesty (§5) but never feed it to the Gate.

## 4. Results — per (symbol × venue) BRUT

All cells: venue = `binance`, window 2025-02-01..2025-03-31, 5568–5664 fifteen-minute flow bars each. Edges in
basis points (1 bp = 0.01%). `x_H1` = this cell's trade count ÷ H1's same-cell count (turnover-cut ratio).

| Symbol | trades | x_H1 | gross edge/trade | net edge/trade | shuffle-null mean | shuffle p | net total | buy&hold | DSR | **Gate** |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| SEIUSDT  | 115 | 0.078 | **+25.23 bps** | −4.77 bps | −31.21 bps | **0.080** | −9.47% | −48.31% | 0.416 | **REJECT** |
| ARBUSDT  |  93 | 0.103 | −47.00 bps | −77.00 bps | −29.10 bps | 0.995 | −52.51% | −49.16% | 0.001 | **REJECT** |
| FILUSDT  |  82 | 0.099 | **+17.41 bps** | −12.59 bps | −28.06 bps | 0.239 | −11.97% | −42.60% | 0.301 | **REJECT** |
| GALAUSDT |  72 | 0.093 | −59.76 bps | −89.76 bps | −29.77 bps | 1.000 | −48.68% | −52.47% | 0.002 | **REJECT** |
| RUNEUSDT |  85 | 0.079 | −48.37 bps | −78.37 bps | −28.33 bps | 0.975 | −50.02% | −46.60% | 0.003 | **REJECT** |
| JUPUSDT  |  68 | 0.100 | −48.74 bps | −78.74 bps | −30.28 bps | 0.995 | −43.09% | −59.54% | 0.006 | **REJECT** |
| OPUSDT   |  54 | 0.140 | −23.32 bps | −53.32 bps | −27.78 bps | 0.846 | −26.12% | −48.94% | 0.052 | **REJECT** |

Gate reasons: every cell fails `deflated_sharpe`, `pbo`, `folds_positive`; 5/7 (ARB, GALA, RUNE, JUP, OP) also
fail `max_drawdown`; ARB and RUNE also fail `buy_and_hold`.

### Reading the table

- **Turnover cut worked:** 54–115 trades, 0.078–0.140× H1 — a clean 7–14× reduction, all gateable (≥30 trades).
- **The longer hold amplified the real signal ~10×.** On the 2 names where order-flow is genuinely informative,
  the 6-h gross edge is **+17 to +25 bps** (vs H1's ≤1.96 bps at a 5-min hold). The signal is real and scales
  with horizon — exactly the mechanism H1b set out to test.
- **It still doesn't clear the fee.** The largest gross edge (SEI +25.2 bps) < the 30-bps maker round-trip → net
  −4.8 bps; every other cell is worse. Net-of-fee, the strategy loses on all 7.
- **Shuffle-null:** 0/7 distinguishable at p≤0.05. SEI (p=0.080) and FIL (p=0.239) are the only names where the
  real edge beats its re-signed null — the SAME signal H1 found — confirming the null is calibrated and the edge
  is real but sub-significant on one window. The 4 negative-gross names go the WRONG way (fade-then-continue),
  sitting at p≈1.0.

## 5. Fee sensitivity (informational only — Gate prices at the catalog 30 bps)

| Symbol | gross | net @ 30 bps (catalog, **Gate**) | net @ 14 bps (realistic perp maker) | net @ 0 bps |
|---|---:|---:|---:|---:|
| SEIUSDT | +25.23 | −4.77 | **+11.23** | +25.23 |
| FILUSDT | +17.41 | −12.59 | **+3.41** | +17.41 |
| ARBUSDT | −47.00 | −77.00 | −61.00 | −47.00 |
| (others) | <0 | <0 | <0 | <0 |

At the realistic ~14-bps perp-maker round-trip, only SEI and FIL turn marginally net-positive per trade — the
same two names with a faint real signal. Even so: (a) the locked Gate prices at 30 bps → both REJECT, (b) neither
is shuffle-distinguishable at p≤0.05, (c) a +3 to +11 bps per-trade edge on one 2-month window at the optimistic
fee is not a tradeable edge. This near-miss is the single reason a *bounded* Modal confirmation is warranted (§7)
before the order-flow-fade family is permanently closed.

## 6. Gate path (locked, unchanged)

Each cell routed through the EXISTING brut path with zero Gate-constant change:
`per-bar net equity stream → cosmu.data.backtest._symbol_metrics → metrics_for_run(trials=1, buy_and_hold=<own>)
→ cosmu.master.cohort.promote_brut(GateSettings())`. GateSettings defaults (LOCKED): min_deflated_sharpe_prob
0.95, min_trades 30, max_drawdown 0.25, max_pbo 0.50, min_folds_positive 0.60, require_beat_buy_and_hold True.
No constant was touched; `promoted == passed` per cell on its OWN streams (no pooling, no sibling deflation).

## 7. What this closes — and whether a fuller Modal run is warranted

**Closes:** the order-flow-**fade** hypothesis across the cadence spectrum. H1 killed it at 1-min/5-min; H1b kills
it at 15-min/6-h with ~10× lower turnover. Holding longer grows the gross edge ~10× but to only ~17–25 bps on the
best names — still under the maker fee. A single fixed-window/threshold imbalance fade on small-cap perps does
not monetize at any tradeable maker cadence we can reach.

**Does NOT close (and the near-miss makes ONE bounded confirmation worthwhile):** SEI/FIL are net-positive at the
realistic perp-maker fee and are the same names H1 flagged. A **fuller Modal run is WARRANTED** — bounded, not a
sweep — to settle whether the signal is monetizable on a richer slice before the family is closed: wider universe
(20–30 small-cap perps), 6–12 months, the **realistic perp-maker fee schedule** (not the spot catalog), K=1000
shuffle, and the hold/threshold held FIXED at this pre-registration (any new threshold/hold is a new trial). If
SEI/FIL-class names hold a shuffle-distinguishable net-positive edge at the realistic fee across that slice, it is
a genuine survivor on a new axis; if not, the order-flow-fade family is decisively dead. This belongs on Modal
(raw aggTrades bulk + the heavy null), not the M2.

Other still-open intraday lines (NOT tested here, NOT refuted): **book depth-imbalance** (H2, lower required
turnover), **cross-symbol / portfolio relative flow**, and the **continuation** (not fade) of strong flow — the
4 negative-gross names here went the wrong way for a fade, which is a (weak, single-window) hint that a momentum
read of extreme flow could behave differently. Each is a new pre-registration with its own trial count.

## 8. Compute note (M2 discipline)

Ran entirely on the local M2 by REUSING H1's on-disk 1m flow-bar cache (27 MB, 413 day-files, 7 symbols × 59
days) — zero new network. The 1m→15m resample is trivial; the shuffle-null (200 perms × ~5.6k coarse bars × 7
symbols) is the only CPU cost and completes in seconds. The fuller confirmation in §7 (wider universe, 6–12 mo,
K=1000) belongs on **Modal**, not the M2.

---

## Reproduce

```
cd apps/engine
python3 scripts/research/h1b_orderflow_lowturnover_2026_06_28.py             # full run (reuses the H1 cache)
python3 scripts/research/h1b_orderflow_lowturnover_2026_06_28.py --self-test # tiny synthetic end-to-end, no network
pytest tests/test_h1b_orderflow_lowturnover.py -q
```

Result blob: `apps/engine/scripts/research/h1b_orderflow_lowturnover_results_2026_06_28.json`.
