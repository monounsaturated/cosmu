# Edge-hunt experiment — market-neutral xsec book + continuous funding percentile (2026-06-25)

**EXPERIMENT ONLY. Zero production impact.** No Gate constant touched, no prod wiring, nothing persisted to any
store, nothing merged that changes runtime. This is one findings report + a disposable self-contained HTML table +
the harness script. Follow-up to #390 (`docs/reports/edge-hunt-experiment-2026-06-25.md`).

## The hypothesis (the sharpest next move #390 proposed)

> #390's long-only daily xsec-momentum died on **two walls**: (1) it loses to **long buy-and-hold beta** in a bull
> tape (killed 88/126 combos), and (2) **daily bars fire < 30 trades** so DSR collapses. The proposed fix:
> go **market-neutral** (long top-momentum / short bottom-momentum — removes the beta the B&H hurdle measures) AND
> drop to **denser bars** (4h — breaks the trade-count floor). Does either wall break?

## Answer: 0 survivors — but **both walls broke**. The binding limit moved to **turnover cost (capacity)**.

The two walls #390 hit are genuinely gone. What kills the book now is a **third, deeper** wall the long-only
experiment never reached: the gross cross-sectional momentum spread is **real and large**, but it is **entirely
consumed by transaction cost** on a high-turnover crypto long/short book. This is a sharper, more economically
honest reject than "0 survivors, gate working" — it tells us exactly where the next dollar of effort goes.

## What actually happened (each wall, with the numbers)

### Wall 1 — DATA DEPTH (keyless history): **not a wall at all once you paginate.**

#390 reported a 720-bar keyless cap and flagged it as a possible blocker pointing at the R2 archive lane. That was a
**single-page artifact**. Bybit v5 public spot kline paginates freely via `end=`: walking it back 8 pages gives
**7,999 × 4h bars = 1,333 days ≈ 3.65 years** of REAL bars for the **full 12-name universe**, common-windowed. So:

- **The densest keyless bar with deep history is 4h, ~3.65 yr — no key, no R2 needed for this depth.**
- 1h keyless is shallow per page (Bybit 999 × 1h ≈ 41 d; Kraken 720 × 1h ≈ 29 d) but also paginates; 4h was the
  right density/depth trade-off for a multi-day-hold momentum book, so the run used 4h.
- This is a real correction to #390's "DATA is the wall" worry: for a market-neutral book judged on **rebalance
  cadence** (not per-name daily trades), keyless 4h is plenty. The R2 price-archive lane is still the right call for
  **1h/1m depth and delisted-name survivorship**, but it is NOT what blocks this experiment.

### Wall 2 — TRADE COUNT (< 30): **broken, by ~100–800×.**

Every book config fires **3,122–24,573 leg trades** across **1,323–7,938 rebalances**. The `min_trades` floor — the
#390 killer for 121/126 combos — is never even close to binding. Denser bars + a rebalanced book demolish it.

### Wall 3 — B&H BETA: **removed as a hurdle (the book is genuinely neutral)** — but the book loses anyway.

The neutral book's **correlation to BTC is ≈ 0.00–0.04** on every config: the long-leaders and short-laggards legs
cancel market beta exactly as designed. So the long-only B&H hurdle that killed 88/126 in #390 **no longer applies** —
a market-neutral book's honest benchmark is **cash / 0**, which we scored it against (and we report long-only B&H only
for contrast). **The beta wall is gone.**

But the book still fails, on a different and more fundamental reason:

### Wall 4 (the real one) — TURNOVER COST eats the entire gross spread.

The gross (cost-free) cross-sectional momentum spread **is real**:

| config (4h) | **gross** ret | **net** ret (fees+slip) | rebalances | trades | corr-BTC |
|---|---:|---:|---:|---:|---:|
| `lb12 q0.20 reb6` (rebalance ~daily) | **+89.2%** | −60.4% | 1,331 | 6,036 | −0.00 |
| `lb60 q0.20 reb6` | **+53.0%** | −31.4% | 1,323 | 3,122 | +0.04 |
| `lb60 q0.33 reb6` | +7.9% | −39.9% | 1,323 | 4,410 | +0.02 |
| `lb60 q0.20 reb1` (every 4h) | −33.0% | −94.4% | 7,938 | 8,382 | +0.03 |

Read the first two rows: a daily-rebalanced long-leaders/short-laggards book on 4h crypto earns **+53% to +89%
gross**, confirming the cross-sectional momentum premium exists on this universe. Net of a realistic **10 bps taker +
liquidity-tiered slippage on both legs**, charged on the ~2.4 names that change basket per rebalance, **every config
nets deeply negative**. The drag scales monotonically with rebalance frequency (reb1 ≫ reb6 turnover → reb1 is even
gross-negative, because churning every 4h converts the slow momentum premium into noise the spread can't pay for).

**This is the capacity wall, not a gate-calibration wall.** The Gate (DSR, folds, holdout, beat-cash) all correctly
fail a book whose net equity curve falls 30–99%. The cost model is the SAME liquidity-tiered floor the production
backtest charges (`backtest._liquidity_floor_bps`), so this is not a pessimistic re-typed cost — it is the cost the
live book would actually pay.

## Theme B — funding-contrarian as a continuous percentile signal: **#390's funding wall also broke.**

#390's funding-contrarian fired **≤ 4 trades** because of the hard `negative-funding AND oversold-RSI` conjunction —
it was un-judgeable. Replacing the conjunction with a single **rolling funding-percentile** trigger (long the names in
the most-negative funding percentile = crowded shorts) on 4h bars makes it **fire often and become judgeable**:

| combo (4h) | DSR | trades | folds+ | net ret | own B&H | holdout DSR | killed by |
|---|---:|---:|---:|---:|---:|---:|---|
| **LTCUSDT** pct0.10 lb60 | **0.620** | **185** | 0.80 | **+61.3%** | −45.2% | −0.21 | dsr, holdout |
| BTCUSDT pct0.20 lb60 | 0.530 | 182 | 0.60 | +38.1% | −8.8% | −0.17 | dsr, holdout |
| XRPUSDT pct0.20 lb120 | 0.520 | 284 | 0.60 | +68.1% | +106.9% | −0.44 | dsr, holdout, B&H |
| BTCUSDT pct0.10 lb120 | 0.459 | 153 | 0.80 | +28.1% | −8.8% | −0.01 | dsr, holdout |

The LTC combo is the **single best outlier of the whole experiment**: 185 trades (vs #390's ≤4), DSR 0.620, and it
**beats its own buy-and-hold** (+61% vs −45%) — it broke the trade-count wall AND the beat-B&H wall. But it still
misses the 0.95 DSR bar and its **holdout DSR is negative** (−0.21): the edge is in-sample only and does not survive
the embargoed exam. Honest reject, not a near-funded survivor. (ATOMUSDT had zero funding cache → correctly produced
no judgeable rows, declared not hidden.)

## The honest verdict, plainly

- **0 survivors.** Correct and expected — the Gate is working.
- **Market-neutral removed the B&H-beta wall** (book corr-to-BTC ≈ 0). ✅
- **Denser bars (4h, paginated to 3.65 yr) removed the trade-count wall** (3k–24k trades). ✅
- **Continuous funding-percentile removed the funding firing wall** (≤4 → 150–320 trades). ✅
- The gross cross-sectional momentum spread **is real** (+53% to +89% gross), but it is **entirely eaten by
  turnover cost** — every neutral-book config nets negative. **The binding limit is now CAPACITY / cost-per-turnover,
  not DATA and not SIGNAL.**

This matches the project's prior finding that the L/S neutral lane is "**real-but-uneconomic**"
(`docs/decisions/`, edge-hunt wave 2) — and now pins *why* with a clean gross-vs-net decomposition: it is the
**turnover**, not the signal, that's missing an edge.

## DATA vs SIGNAL verdict

**Neither is the binding limit anymore — COST is.**
- DATA: keyless 4h paginates to 3.65 yr across 12 names → **not the wall** (corrects #390's worry).
- SIGNAL: the gross L/S momentum spread is present and large (+53–89% gross) → **signal exists**.
- COST: a realistic two-legged taker+slippage charge on ~daily rebalancing **consumes 100%+ of the gross edge** →
  **this is the wall.**

## The single sharpest next move

**Test whether the cross-sectional momentum premium survives at LOW turnover** — the one lever that directly attacks
the cost wall. Concretely, before authoring any spec:

1. **Slow the rebalance and widen the hold.** Re-run the SAME neutral book at **weekly/bi-weekly rebalance with a
   no-trade band** (only swap a name when its rank crosses a hysteresis margin, not every bar). The gross +53–89%
   came from `reb6` (~daily); a 5–10× slower book with a rank-deadband keeps most of the slow premium while cutting
   turnover ~5–10×, which is the only thing that can flip net positive. If even a weekly, deadbanded book nets
   negative after the same honest cost floor, the cross-sectional crypto momentum edge is **genuinely uneconomic at
   our cost tier** — a real, final reject for this thesis (not a wiring gap).
2. **If (1) shows promise, the second lever is fee tier, not signal.** The whole gap is ~taker bps × turnover; a
   maker-rebalance / VIP-tier fee assumption is the honest knob to test next, but only AFTER the low-turnover book
   proves the premium clears *some* realistic cost — never as a way to manufacture a pass.

The funding-percentile lane is a **weaker** second priority: it is now judgeable and the LTC combo is the closest
near-miss, but its negative holdout says the in-sample edge doesn't generalize — it needs a cross-symbol /
cross-period robustness pass before it's worth a spec, not more single-combo tuning.

## Method (what was actually run) — reproducible, BRUT, zero prod impact

- **Universe (12 liquid names):** BTC, ETH, SOL, AVAX, LINK, DOGE, ADA, DOT, LTC, XRP, BCH, ATOM.
- **Data:** Bybit v5 keyless spot kline, **paginated** (the provider single-pages; the harness walks `end=`) →
  7,999 × 4h bars common window, 1,333 d. Real Binance funding from the operator's `.cosmu` cache, PIT 4h accrual,
  charged on both book legs and the funding-percentile signal. ATOM funding absent → declared.
- **The neutral book (a genuine equity curve, not the `_pad` proxy in `carry_ablation`):** each rebalance bar ranks
  the universe by trailing momentum (PIT), longs the top quantile, shorts the bottom quantile; per-bar book return =
  mean(long fwd) − mean(short fwd) + funding on each leg − amortized round-trip turnover cost (10 bps taker +
  `_liquidity_floor_bps` slippage) on names changing basket. Scored BRUT through `master/scorer.score` with the
  **locked** `GateSettings()` and `TrialStats(count = realized grid size, sr_correlation = cross-config rho)` — the
  legitimate per-book own-overfit deflation. PBO is the true CSCV across the grid's per-bar config streams. Champion
  confirmed on its OWN embargoed last-fifth holdout. **Both benchmarks reported** (cash/0 = the right neutral hurdle;
  long-only B&H = the old wrong one, for contrast). **Ranked by outlier; every config emitted — never a pooled mean.**
- **Variant 3:** funding-contrarian as a rolling funding-percentile long (no RSI conjunction), per (symbol × venue),
  judged BRUT exactly like #390 so the two are directly comparable.
- **Script:** `apps/engine/scripts/research/edge_hunt_mktneutral_2026_06_25.py` ·
  raw rows `…/edge_hunt_mktneutral_results_2026_06_25.json` ·
  HTML `…/edge_hunt_mktneutral_table_2026_06_25.html` (generator: `…/edge_hunt_mktneutral_make_html.py`).

## Honest caveats

- Free keyless crypto bars are **survivorship-biased** (no delisted names) — this proves signal *presence* and the
  *cost* verdict, not deployable capacity on the true (delisted-inclusive) universe. Declared, not hidden.
- Bybit spot taker (~10 bps) is used as the cost on the keyless Bybit bars; the price thesis is venue-agnostic and
  the fee is the real axis. A perp short would also pay/receive funding (modeled) and a borrow spread (not modeled on
  spot bars) — so the net is, if anything, slightly OPTIMISTIC, which strengthens the "uneconomic at this turnover"
  conclusion.
- The book amortizes turnover cost across the basket gross notional; a finer per-name capital-weighting would shift
  the magnitude a few points but not the sign — the cost dominates by a wide margin at every cadence tested.
