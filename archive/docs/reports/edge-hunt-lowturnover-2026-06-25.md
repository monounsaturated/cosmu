# Edge-hunt experiment — low-turnover deadbanded market-neutral xsec momentum book (2026-06-25)

**EXPERIMENT ONLY. Zero production impact.** No Gate constant touched, no prod wiring, nothing persisted to any
store, nothing merged that changes runtime. One findings report + a disposable self-contained HTML table (with a
net-vs-turnover frontier plot) + the harness. Direct follow-up to **#391**
(`docs/reports/edge-hunt-mktneutral-2026-06-25.md`).

## The wall this attacks (the one lever #391 left open)

> #391 broke the beta wall (book corr-to-BTC ≈ 0) and the trade-count wall (3k–24k trades). The **gross**
> cross-sectional momentum spread is **real and large** (+53% to +89% over ~3.65 yr), confirming the premium exists
> on this universe. But every ~daily-rebalance config **netted deeply negative**: a realistic two-leg taker (10 bps)
> + liquidity-tiered slippage on the names that change basket each rebalance consumes 100%+ of the gross edge.
> **The only lever left is lowering turnover.**

So this experiment runs a **pre-registered** low-turnover grid and asks one question plainly:

> **Does ANY low-turnover deadbanded book net POSITIVE after the honest cost floor AND clear the Gate?**

## Answer: **0 / 16 clear the Gate. Crypto cross-sectional momentum is UNECONOMIC at our cost tier — a real reject.**

Lowering turnover does **not** rescue the book. The single best NET config nets positive **in-sample only** and dies
on the embargoed holdout + deflation; and pushing turnover lower (wider no-trade band) **starves the thin signal
faster than it saves cost** on this 12-name universe. There is **no turnover/return corner** where net flips positive
*and* survives. The signal is present (gross is large), but **no realizable net edge survives the cost floor + the
deflated, out-of-sample exam.** This is the honest, final-for-this-thesis reject — not a wiring or data gap.

## The pre-registered grid (no best-of-N cherry-pick)

`rebalance ∈ {weekly = 42×4h, bi-weekly = 84×4h}` × `rank no-trade band ∈ {0.00, 0.10, 0.20, 0.30}` ×
`lookback ∈ {30, 60} 4h bars`, quantile fixed at 0.20 (top/bottom 20%, #391's best gross corner). **16 configs.**
Each book is judged **BRUT** on its OWN net equity curve through the **locked** `GateSettings()`. Costs are the
**identical** honest floor production charges (`backtest._liquidity_floor_bps` + 10 bps two-leg taker, funding on
both legs). Ranked by **outlier (net return)**; **every config emitted — never a pooled mean.**

The no-trade band is a **fixed-basket-size hysteresis**: each leg always holds k = round(0.2·m) names, but a held
name is swapped out for a higher-ranked candidate **only when the candidate's rank beats it by more than `band`** —
so a name oscillating near the k-th boundary is not churned each period. `band = 0` reduces to #391's hard top-k /
bottom-k membership.

## The net-vs-turnover frontier (the whole grid, ranked by net)

| config (4h, q0.20) | **net** | gross | turnover/reb | trades | rebal | DSR | folds+ | PBO | holdout DSR | maxDD | corr-BTC | killed by |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| lb60 reb84 **band0.0** | **+0.658** | +0.885 | 1.50 | 559 | 95 | 0.784 | 0.60 | 0.47 | **+0.007** | 0.63 | +0.09 | maxDD, **DSR** |
| lb30 reb42 band0.3 | +0.026 | +0.239 | 1.06 | 790 | 190 | 0.612 | 0.60 | 0.47 | +0.206 | 0.79 | +0.06 | maxDD, DSR |
| lb60 reb84 band0.1 | −0.136 | −0.032 | 1.35 | 500 | 95 | 0.544 | 0.60 | 0.47 | −0.000 | 0.65 | +0.10 | maxDD, DSR, holdout, B&H |
| lb30 reb42 band0.2 | −0.255 | −0.089 | 1.15 | 861 | 190 | 0.483 | 0.60 | 0.47 | +0.393 | 0.78 | +0.05 | maxDD, DSR, B&H |
| lb60 reb42 band0.1 | −0.436 | −0.303 | 1.16 | 864 | 189 | 0.377 | 0.40 | 0.47 | +0.341 | — | +0.05 | maxDD, folds, DSR, B&H |
| lb60 reb84 band0.3 | −0.470 | −0.421 | 1.06 | 392 | 95 | 0.334 | 0.40 | 0.47 | +0.012 | 0.68 | +0.11 | maxDD, folds, DSR, B&H |
| lb60 reb84 band0.2 | −0.478 | −0.423 | 1.19 | 440 | 95 | 0.333 | 0.60 | 0.47 | +0.046 | 0.70 | +0.09 | maxDD, DSR, B&H |
| lb60 reb42 band0.0 | −0.457 | −0.309 | 1.29 | 965 | 189 | 0.368 | 0.40 | 0.47 | +0.28 | — | +0.06 | maxDD, folds, DSR, B&H |
| … (8 more, all net −0.53 to −0.72) | <0 | <0 | — | — | — | <0.31 | — | 0.47 | — | — | ≈0 | maxDD, DSR, B&H |

(Full 16 rows + the frontier scatter in
`apps/engine/scripts/research/edge_hunt_lowturnover_table_2026_06_25.html`.)

**Only 2 of 16 configs net positive at all.** Both fail the Gate. The cloud sits mostly below the cash hurdle.

## Why lowering turnover does NOT save it — the band cuts signal faster than cost

The decisive evidence is the **band sweep at the slowest cadence** (bi-weekly, lb60 — the lowest-turnover corner):

| band | net | gross | trades | DSR | holdout DSR |
|---:|---:|---:|---:|---:|---:|
| 0.00 | **+0.658** | +0.885 | 559 | 0.784 | +0.007 |
| 0.10 | −0.136 | −0.032 | 500 | 0.544 | −0.000 |
| 0.20 | −0.478 | −0.423 | 440 | 0.333 | +0.046 |
| 0.30 | −0.470 | −0.421 | 392 | 0.334 | +0.012 |

Widening the band cuts trades 559 → 392 (a real ~30% turnover reduction) but **the gross return collapses from +88%
to −42%** — the band evicts the very rank-leaders that carry the momentum premium far faster than it saves the
~30% of cost. On a **12-name** universe each leg holds only ~2 names, so a band wide enough to matter for cost
inevitably starves the signal. **There is no sweet spot.**

The mirror story at the **faster weekly cadence (lb30 reb42)** confirms it's genuinely about economics, not one knob:
there the band *helps* (band0.0 net −72% → band0.3 net **+2.6%**) because at weekly churn the cost term dominates and
trimming it recovers ground — but the best it reaches is **+2.6% net, DSR 0.612**, still nowhere near the 0.95 bar.
Whichever way you trade the band, **you land short of a survivor.**

## The single best NET book, examined — an in-sample mirage

`bybit:4h lb60 q0.20 reb84 band0.0` is the grid's outlier: **net +65.8%** over ~3 yr validation (gross +88.5%),
genuinely market-neutral (corr-BTC +0.09), 559 trades (clears `min_trades` ~19×). But:

- **DSR 0.784 ≪ 0.95** — once deflated for the 16-config grid it is not a confident edge.
- **Holdout DSR +0.007 ≈ 0** — on the embargoed last fifth the edge **vanishes**. The +66% lives entirely in-sample.
- **max-drawdown** also trips the gate (0.63).

It beats the cash hurdle in-sample, but it is exactly the kind of book the Gate exists to reject: a large in-sample
number with **no out-of-sample persistence**. The Gate is working.

## The honest economic verdict, plainly

- **0 survivors / 16.** Correct and expected — the Gate is working.
- **Lowering turnover is the right lever to test, and it was tested honestly** (weekly + bi-weekly × 4 band widths ×
  2 lookbacks, BRUT, identical production cost floor). It does **not** produce a net-positive *and* Gate-clearing book.
- The gross cross-sectional momentum spread **is real** (best book gross **+88.5%**), but on this universe at this
  cost tier **no realizable, deflation-and-holdout-surviving net edge exists.** Either you rebalance often enough to
  keep the signal (and the two-leg taker + slippage eats it), or you deaden turnover enough to matter (and the thin
  12-name signal dies first).

**Verdict: crypto cross-sectional momentum (this universe, this cost tier) is genuinely UNECONOMIC — a real reject of
the thesis, not a data/wiring gap.** This pins #391's "capacity wall" conclusion with a clean low-turnover sweep:
the wall does not move when you slow the book down.

## What is (and isn't) the next move

This thesis is **closed at our cost tier on this universe.** The only honest levers that remain are *structural*, not
more signal/turnover tuning, and each must be tested as its own pre-registered experiment — never as a way to
manufacture a pass:

1. **Fee tier is the whole gap.** The entire net = gross − (taker × turnover). A **maker-rebalance / VIP-tier** fee
   assumption (e.g. post-only limit rebalancing) is the one knob that could flip the bi-weekly no-band book — but only
   if a passive fill is realistic for these names, and the slippage of *not* getting filled must be modeled honestly.
   This is a venue/execution question, not a signal one.
2. **A bigger, delisted-inclusive universe** (the R2 price-archive lane) would let the band act as a real hysteresis
   without starving the signal — k = 0.2·m grows with the universe. The 12-name survivorship-biased keyless set is
   the binding constraint on the *band* lever specifically. This is the same R2 follow-up #391 already flagged.

Both are **structural plumbing**, not strategy iteration. Until one of them lands, **stop adding cross-sectional
momentum / range / turnover variants** — the premium is real but uneconomic here, and that is now measured twice.

## Method (reproducible, BRUT, zero prod impact)

- **Universe (12 liquid names):** BTC, ETH, SOL, AVAX, LINK, DOGE, ADA, DOT, LTC, XRP, BCH, ATOM.
- **Data:** Bybit v5 keyless spot kline, **paginated** → 7,999 × 4h bars common window, 1,333 d ≈ 3.65 yr. Real
  Binance funding from the operator's `.cosmu` cache, PIT 4h accrual, charged on both legs (ATOM funding absent →
  declared, 0 accrual, never fabricated). **Identical** data + funding + cost code to #391 (imported verbatim from
  `edge_hunt_mktneutral_2026_06_25.py`); the only new code is the deadbanded book constructor and the slow-cadence grid.
- **The book:** each rebalance ranks the universe by trailing momentum (PIT), longs top-k / shorts bottom-k with a
  **fixed-basket rank no-trade band** (held names swapped only when a candidate's rank beats them by > band); per-bar
  return = mean(long fwd) − mean(short fwd) + funding on each leg − amortized round-trip turnover cost (10 bps taker +
  `_liquidity_floor_bps` slippage) on names changing basket. Scored BRUT through `master/scorer.score` with the
  **locked** `GateSettings()` and `TrialStats(count = 16-config grid, sr_correlation = cross-config rho)` — the
  legitimate per-book own-overfit deflation. PBO = true CSCV across the grid's per-bar config streams. Champion
  confirmed on its OWN embargoed last-fifth holdout. Hurdle = cash/0 (the right benchmark for a neutral book).
  **Ranked by outlier (net); every config emitted — never a pooled mean.**
- **Script:** `apps/engine/scripts/research/edge_hunt_lowturnover_2026_06_25.py` ·
  raw rows `…/edge_hunt_lowturnover_results_2026_06_25.json` ·
  HTML + frontier `…/edge_hunt_lowturnover_table_2026_06_25.html`
  (generator `…/edge_hunt_lowturnover_make_html.py`).

## Honest caveats

- Free keyless crypto bars are **survivorship-biased** (no delisted names) — this proves signal *presence* and the
  *uneconomic* verdict on this universe, not the verdict on the true (delisted-inclusive) universe. The band lever in
  particular is constrained by the 12-name size (caveat 2 above). Declared, not hidden.
- A spot short pays no borrow here; a perp short would also pay/receive funding (modeled) and a borrow spread (not
  modeled) — so the net is, if anything, **slightly optimistic**, which only *strengthens* the uneconomic conclusion.
- The turnover/rebalance metric is fraction-of-book-changed; with k≈2 per leg the denominator is small, so values
  near/above 1.0 are expected and reflect real churn — the *trade-count* column is the unambiguous churn measure.
