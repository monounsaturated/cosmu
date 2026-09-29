# Edge-hunt experiment — cross-sectional momentum + funding-contrarian (2026-06-25)

**EXPERIMENT ONLY. Zero production impact.** No Gate constant touched, no prod wiring, nothing persisted to any
store, nothing merged that changes runtime. This is one findings report + a disposable self-contained HTML table.

## The money question

> Do our two LIVE strategy themes — cross-sectional momentum (xsec) and funding-contrarian — produce any combo
> that **survives or gets close to the locked Gate**, judged **BRUT per (strategy × symbol × venue)**, never pooled?

## Answer: 0 survivors. The machine is working.

**126 distinct (theme × symbol × venue × config) combos** scored on real bars. **Zero** clear the locked Gate
(DSR ≥ 0.95, PBO ≤ 0.50, folds-positive ≥ 0.60, ≥ 30 own trades, holdout DSR > 0, beat buy-and-hold). Zero even
pass the validation slice pre-holdout. This is the correct, honest empty result — the Gate is calibrated to refuse
exactly these (a long-only momentum/contrarian read on daily crypto in a bull tape that buy-and-hold dominates).

## Method (what was actually run)

- **Universe (12 liquid names):** BTC, ETH, SOL, AVAX, LINK, DOGE, ADA, DOT, LTC, XRP, BCH, ATOM.
- **Two venues, real fee axis (de-collapses S×A×V):**
  - **Binance** — operator's cached **real** daily bars (~1000 bars, 2023-09 → 2026-06) + cached **real** funding
    history (2024-06 → 2026-06). Taker **10 bps**. (The M2 is geo-blocked from Binance LIVE; the cache is PIT-honest.)
  - **Kraken** — **live keyless** public OHLC (the real LIVE spot venue), ~720 daily bars. Taker **26 bps** (2.6×).
- **Themes = the two shipped reference specs**, gridded over their fitted `param_space`:
  - `strategies/inbox/fiche-example-xsec-momentum.json` — long the relative-strength leaders (rank floor + vol ceiling).
  - `strategies/inbox/fiche-example-funding-contrarian.json` — long spot when funding is deeply negative (crowded
    shorts) + RSI oversold. Funding is a Binance-perp signal → Binance cell only.
- **Engine reuse (no reimplementation):** `data/backtest.run_strategy_backtest_detailed` (canonical PIT backtest),
  `metrics_for_run` (per-combo own-stream metrics), `master/scorer.score` with `GateSettings()` (the locked gate)
  and `TrialStats(count=1)` (no cross-combo family — BRUT). The xsec rank is built point-in-time across the whole
  venue panel via `research.carry_ablation._xsec_rank_alt`; funding via `_funding_alt` (level + summed accrual).
  Each combo's champion is confirmed on its OWN embargoed holdout. **Ranked by OUTLIER per symbol; never a pooled mean.**
- **Script:** `apps/engine/scripts/research/edge_hunt_experiment_2026_06_25.py` ·
  raw rows `…/edge_hunt_results_2026_06_25.json` · table `…/edge_hunt_table_2026_06_25.html`.

## The single best outlier

| field | value |
|---|---|
| combo | **ETHUSDT × Binance × xsec-momentum** (`lb30, rank_floor 0.70, vol_ceiling 0.07, stop 0.10, tp 0.19`) |
| deflated Sharpe (DSR) | **0.051** (gate bar = 0.95 — ~19× short) |
| annualized Sharpe (display) | 1.06 |
| trades | **36** (clears the 30 floor) |
| folds-positive | 0.75 |
| PBO | 0.43 |
| validation return | **+2.4%** |
| buy-and-hold (same window) | **+85.7%** |
| beat B&H? | **no** |
| holdout DSR | +0.26 |
| killed by | `deflated_sharpe`, `buy_and_hold` |

This is the **best combo that even reaches 30 trades.** The headline by raw DSR (LINK/Kraken, DSR 0.378) is a
**2-trade mirage** — statistically meaningless, killed by `min_trades`. The honest near-miss frontier is the ETH
row above, and it is nowhere near the line.

### Only 5 of 126 combos reach the 30-trade floor — all DSR ≤ 0.051

| theme | symbol | venue | DSR | trades | folds+ | PBO | ret | B&H | holdoutDSR | killed by |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| xsec | ETHUSDT | binance | 0.051 | 36 | 0.75 | 0.43 | +2.4% | +85.7% | +0.26 | dsr, buy_and_hold |
| xsec | BTCUSDT | binance | 0.010 | 32 | 0.25 | 0.72 | −2.6% | +236.5% | +0.49 | folds, pbo, dsr, buy_and_hold |
| xsec | BTCUSDT | binance | 0.005 | 49 | 0.25 | 0.66 | −5.4% | +236.5% | +0.24 | folds, pbo, dsr, buy_and_hold |
| xsec | BTCUSDT | binance | 0.003 | 32 | 0.25 | 0.68 | −7.8% | +236.5% | +0.33 | folds, pbo, dsr, buy_and_hold |
| xsec | BTCUSDT | kraken | 0.001 | 34 | 0.25 | 0.72 | −8.5% | +38.0% | +0.38 | folds, pbo, dsr, buy_and_hold |

## What actually kills the combos (deduped, n=126)

| disconfirmer | combos killed |
|---|---:|
| `deflated_sharpe` (DSR < 0.95) | 126 / 126 |
| `folds_positive` (< 0.60) | 123 |
| `min_trades` (< 30) | 121 |
| `pbo` (> 0.50) | 117 |
| `holdout` (DSR ≤ 0) | 98 |
| `buy_and_hold` (didn't beat hold) | 88 |

Read this as **two independent walls**, both fatal:

1. **The frequency-vs-significance wall (xsec).** With the rank-floor + vol-ceiling double gate on **daily** bars, a
   single symbol's leadership window only opens a handful of times in ~2 years. Tighten the thresholds → high
   per-trade quality but **< 30 trades** → DSR collapses (the expected-max-Sharpe benchmark and the n_obs term both
   punish thin evidence). Loosen them → 30+ trades, but the edge dissolves into beta and the combo **loses to
   buy-and-hold** and fails PBO/folds. There is **no threshold setting where both hold** — the 5 combos that reach
   30 trades all have DSR ≈ 0 and lose to hold by 30–230 percentage points.
2. **Funding-contrarian is structurally non-firing.** The `funding_floor < deeply-negative AND rsi < oversold`
   conjunction fires at most **4 times** over the full 2-year funding history on any symbol (19 of 31 combos
   trade at all; max 4 trades). It is too thin to be judgeable — not a near-miss, a **non-event** on this universe
   at the daily horizon. (Deeply-negative funding + oversold RSI co-occurring is genuinely rare in a bull tape.)

## The venue axis — a real, honest artifact (not an edge)

The S×A×V split surfaced a tempting-but-fake signal: on **Binance** only 2 xsec combos "beat B&H," on **Kraken**
**30** did. This is **not** Kraken being a better venue (its 26 bps fee is 2.6× Binance's, strictly worse). It is
the **own-window discipline working**: Kraken's keyless history is shorter (720 vs 1000 bars), so its B&H baseline
starts later and spans a flatter stretch (e.g. LINK B&H −19.5% on the Kraken window vs strongly positive on the
longer Binance window). The "beat B&H" flips entirely on the **window**, not the alpha — exactly why the BRUT model
forbids comparing a combo to a sibling's window and annualizes each cell on its own. A pooled view would have hidden
this; per-combo surfaced it as a data-coverage caveat, not a discovery.

## Sharpest next hypothesis — what would actually move a combo over the line

The binding constraint is **not compute and not the Gate** — it is **trade frequency at a horizon where the edge
isn't just beta.** Two concrete, falsifiable moves, ranked:

1. **Go market-neutral, not long-only (highest leverage).** Every kill here ultimately routes through
   `buy_and_hold`: a long-only crypto basket in a bull tape can't out-return holding it. A **cross-sectional
   long-leaders / short-laggards** spread (the xsec rank already computes both ends) removes the beta the B&H
   hurdle measures — the combo is then judged on *dispersion* (does the top decile beat the bottom decile?), which
   is what the momentum premium actually is. This directly attacks the single disconfirmer that kills 88/126.
   *Disconfirmer for the hypothesis:* if the short-leg's borrow/funding cost on perps eats the spread, or the
   long-short still fails PBO, it's a real reject, not a wiring gap. (Venue note: shorting needs perps — Binance/HL
   USDⓈ-M — not spot.)
2. **Drop to a denser bar to break the frequency wall, then re-impose the cost-realism floor.** The 30-trade floor
   is unreachable for daily xsec on a single name in 2 years. A **4h or 1h** xsec rank gives 6–24× the bars, so a
   tight high-quality threshold can still book 30+ own trades and earn a non-degenerate DSR — *provided* the
   liquidity-tiered slippage floor (already in `backtest._liquidity_floor_bps`) and per-fill fees are charged, so a
   denser-bar edge that's really just paying-the-spread is correctly killed. Run this as the next experiment before
   authoring any spec.

A weaker third lever — **funding-contrarian only becomes testable** if it moves off the rare daily double-gate:
either a single continuous funding-percentile signal (no hard RSI conjunction) or a denser bar, so it fires often
enough to score. As specified today it is un-judgeable on this universe.

## Honest caveats

- Free equity/keyless crypto bars are **survivorship-biased** (no delisted names); this proves signal *presence*,
  not deployable capacity — declared, not hidden.
- The xsec rank's lookback was pinned to the spec mid-value to keep the panel build lean (the grid still varied the
  rank/vol thresholds + stops); the duplicate rows that collapses into were de-duplicated for all stats above.
- Holdout is each combo's OWN embargoed last-fifth, confirmed once (no re-pick) — same physics the finder uses.
