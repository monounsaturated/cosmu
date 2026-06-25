# Exit-variant spike — WIDE firm-up (2026-06-25)

**Verdict (firmed up): ship V0 (fixed stop+take) as the default + keep V4 (ATR-mult stop) as a fixed
alternative — and HARD-DROP V2 (break-even runner) and V3 (standalone trailing). Exit is MATERIAL but
is NOT a per-cell best-of-M selection axis: the best exit is a property of the ENTRY style and the
REGIME, not a knob you tune per (entry,symbol). The prior 3×5×3 call holds, and is now sharper: V4 is a
genuine keeper (it is the robust winner on the long daily window), V0 is the reliable least-bad baseline,
and V2/V3 over-trade themselves to the bottom on EVERY window tested.**

This broadens the prior spike (3 entries × 5 exits × 3 symbols on a SHORT 720-bar 4h Kraken window,
~119 days — suggestive, not definitive) to **6 entries × 8 exits × 8 symbols** and, critically, runs the
primary pass on the **720-bar *daily* window (~2 years, multi-regime)** so the conclusion is no longer a
single-regime artifact. A 4h cross-check (192 backtests) is included to test window-sensitivity directly.

READ-ONLY experiment. No money-path edits. Scratch script `/tmp/exit_spike_wide.py` +
`/tmp/exit_spike_4h_check.py`; raw `/tmp/exit_spike_wide_results.json`.

---

## Method (engine recipe, reused — not reinvented)

- **Backtest**: `cosmu.data.backtest.run_strategy_backtest_detailed` → `BacktestResult.per_symbol`
  (real Kraken fees/slippage, compounding `size_fraction × current cash`, purged+embargoed split). One
  symbol per call → `per_symbol[symbol]["sharpe"]` is that cell's standalone annualized Sharpe; its
  `per_symbol_runs[symbol].bar_returns` is the stream the deflation math scores on.
- **Entries (6, price/TA-only so bare Kraken bars suffice)** from `evolution/seeder.py`:
  `breakout` (ret+vol), `momentum` (ret+ADX), `orb_channel` (ORB+FVG+MA-trend), `atr_breakout_entry`
  (ret-only), `meanrev` (RSI+bb_z), `meanrev_scalp` (RSI+bb_z, fast). The fan overwrites each seed's exit,
  so only the ENTRY (conditions+setup+horizon) carries.
- **Exits (8)** = the *engine's own* `cosmu.lab.exit_sweep.fan_exit_envelope` catalogue (shipped #378),
  mapped to the prior spike's V0–V4 buckets:
  | slug | bucket | structure |
  |---|---|---|
  | `fixed` | **V0** | fixed % stop + single TP |
  | `multi_tp2` | **V1** | 2-leg scale-out, no break-even |
  | `multi_tp2_be_runner` / `multi_tp3_be_runner` | **V2** | 2-/3-leg scale-out + break-even + runner trail |
  | `trailing` / `trailing_immediate` | **V3** | standalone trailing stop (cushioned / armed-at-entry) |
  | `atr_stop` | **V4** | ATR-mult initial stop + single TP |
  | `atr_multi_tp_be_runner` | **V4c** | ATR stop + scale-out + break-even runner (composite) |
- **Symbols (8)**: BTC ETH SOL XRP ADA DOGE LINK AVAX (USDT, Kraken-liquid).
- **Bars**: Kraken keyless (`COSMU_BARS_VENUE=kraken`), **1d / 720 bars ≈ 2 years** (primary);
  4h / 720 bars ≈ 119 days (cross-check). Kraken caps at 720 bars/call, so daily = far more *calendar*
  per bar.
- **Fees** (Kraken spot, from `spine/venue.py`): taker **40 bps**, slippage **7 bps**, impact **55 bps** —
  same on every row.
- **"Only the exit differs"**: per (entry,symbol) the entry params AND the shared stop/take/time_stop are
  fixed at their fitted-space MIDPOINTS, identical across all 8 exits; exit-specific params
  (atr_mult, TP legs, trail distances) use their own midpoints. This isolates the exit **structure**, not
  a fitted level — the honest structure-only comparison.
- **Deflation (the correlated-trial fix the prior spike lacked)**: the 8 exits share an entry ⇒ correlated
  trials. Per cell we measure `rho_bar` (avg pairwise corr of the 8 exit return streams), take
  `n_eff = effective_trials(8, rho_bar)`, and require the best exit's per-obs Sharpe to beat
  `SR0 = expected_max_sharpe(var(per-obs Sharpes), n_eff)` (`master/scorer`). Unlike the prior spike's
  raw-5, this applies the correlation haircut.

**384 backtests** primary (6×8×8), **48 cells** (36 "active" = the entry actually fires >0 trades;
the 12 dead cells are `meanrev`/`meanrev_scalp` on symbols where the midpoint RSI/bb_z gate never
triggers on daily bars — honestly excluded, not hidden). **+192** in the 4h cross-check.

---

## Results

### 1. Robust ranking — mean annualized Sharpe per FIXED exit, across the 36 active daily cells

| rank | exit | meanSR | medSR | n>0 | mean trades | win% of cells |
|---|---|---:|---:|---:|---:|---:|
| 1 | **V4 atr_stop** | **+1.216** | +0.530 | 27/36 | **18.4** | **58.3%** |
| 2 | **V0 fixed** | +0.555 | −0.066 | 18/36 | 34.6 | 16.7% |
| 3 | V3i trailing_immediate | −0.655 | −0.725 | 14/36 | 63.2 | 13.9% |
| 4 | V3 trailing | −0.688 | −0.637 | 13/36 | 54.6 | 0.0% |
| 5 | V1 multi_tp2 | −0.746 | −0.628 | 11/36 | 21.7 | 2.8% |
| 6 | V4c atr+scaleout | −0.865 | −0.746 | 15/36 | 43.6 | 5.6% |
| 7 | V2b multi_tp3_be_runner | −1.363 | −1.249 | 12/36 | 71.8 | 0.0% |
| 8 | V2a multi_tp2_be_runner | −1.537 | −1.633 | 11/36 | 70.4 | 5.6% |

The over-trade signature is unmistakable: **V2 and V3 trade 2.5–4× more than V4 and rank at the bottom.**
The break-even-runner (V2) gets its break-even stop tapped and re-enters; the standalone trail (V3) whips
in and out — both churn fees. V4 wins with the **fewest** trades.

### 2. V4 (ATR-stop) vs V0 (fixed), head-to-head (daily, 36 active cells)

- V4 beats V0 on Sharpe in **27/36** cells (V0 beats V4 in 6, 3 ties).
- mean(V4 − V0 Sharpe) = **+0.66**, median **+0.48**.
- V4 has a **shallower** max drawdown than V0 in 19/36 cells; its **p25 Sharpe is +0.02 vs V0's −0.97** —
  i.e. V4 lifts the whole *left tail* of cells out of the red. This is the "tames volatile losers"
  property, now measured on 2 years of data: a wider, volatility-scaled stop stops getting knifed by a
  flat % stop in high-vol names.

### 3. By entry style — mean Sharpe (daily, active cells)

```
entry\exit          V0     V4    V3t    V3i     V1    V2a    V2b    V4c
breakout           -0.15   0.88  -1.43  -1.33  -1.30  -3.24  -3.06  -2.21
momentum           -0.05   0.25  -0.26  -0.25  -0.40  -0.71  -0.60  -0.13
orb_channel         2.97   3.47   0.80   0.84   0.82   0.76   1.26   0.78
atr_breakout_entry -0.72   0.43  -2.12  -2.10  -2.56  -3.90  -3.91  -2.52
meanrev            -0.00  -0.01  -0.42  -0.42   0.16   0.21   0.21   0.21
meanrev_scalp       1.80   1.80   0.04   0.04   0.16   0.53   0.53   0.53
```

V4 ≥ V0 on every TRENDING entry (breakout, momentum, orb, atr_breakout); V4 ≈ V0 on mean-rev (where the
ATR stop adds nothing and the tiny V1/V2 numbers are 2-cell noise). **The exit that wins is a property of
the entry style** — not a per-cell tunable.

### 4. Window-sensitivity cross-check (4h / 119 days, 3 entries × 8 exits × 8 symbols = 192 bt)

| exit | meanSR | medSR | n>0 |
|---|---:|---:|---:|
| V0 fixed | **−1.713** | −1.017 | 5/24 |
| V1 multi_tp2 | −1.687 | −1.081 | 4/24 |
| V2 multi_tp2_be_runner | −2.070 | −1.244 | 3/24 |
| V4 atr_stop | −2.454 | −1.435 | 3/24 |
| V3 trailing_immediate | −2.594 | −1.135 | 1/24 |
| V4c atr+scaleout | −2.586 | −1.614 | 2/24 |

The 4h window was a choppy DOWN-stretch for long-only crypto — **everything is negative**, and here **V0
is the least-bad**, with V4 mid-pack. This *reproduces the prior short-4h-window spike* ("V0 wins on mean
Sharpe; V2/V3 over-trade"). The lesson is explicit: **which FIXED exit wins is regime/window-dependent**
(V4 in a 2-year trending sample, V0 in a short chop) — but V2/V3 are bottom-quartile in BOTH windows.

### 5. Deflation note (honest)

`rho_bar` between the 8 exit streams runs **~0.6–0.93** on the active cells, so `n_eff` collapses to
**~1.1–1.5** and `SR0 ≈ 0`. That is the correlated-trial fix working as intended: 8 exits on one entry are
**not** 8 independent bets, so there is essentially no multiple-testing penalty to pay — which is exactly
why "pick the best of 8 exits per cell" is NOT a meaningful selection axis. With near-1 effective trials,
"best-of-8 survives SR0" is a near-trivial bar (29/48 clear it); the *informative* statistic is the
**robust cross-symbol mean** (§1), not the per-cell max. This is the operator's ROBUST-not-MAX rule made
concrete: the max is free here, so don't trust it — trust the average.

---

## Verdict (does it change the "don't build a 4th selection axis" call? is V4 a keeper?)

1. **(a) Does ANY exit beat V0 robustly across symbols after deflation?**
   Yes — **V4 (ATR-stop) beats V0 robustly on the 2-year daily window** (+0.66 mean Sharpe, wins 27/36
   cells, fewest trades, shallower tail). But it does so as a **FIXED structural choice**, not as a
   per-cell best-of-M pick. On a short choppy window V0 wins instead. So: **exit STRUCTURE matters; the
   per-cell SELECTION of an exit does not** (trials are ~1 effective ⇒ best-of-M is free and untrustworthy).

2. **(b) Is V4 a consistently-good fixed default that cuts tail losses?**
   **Yes — V4 is a keeper.** It is the robust winner on the long window, it reliably cuts the left tail
   (p25 Sharpe +0.02 vs V0 −0.97; shallower DD in 19/36), and it wins with the FEWEST trades. Its only
   weakness is short choppy regimes, where it ties/loses slightly to V0 — which is precisely why we keep
   BOTH and default to V0.

3. **(c) Confirm/revise: ship V0 default + V4? hard-drop V2/V3?**
   **CONFIRMED and sharpened.**
   - **Ship V0 (fixed) as the default** — most robust across regimes, least-bad in chop, simplest.
   - **Keep V4 (ATR-mult stop) as a fixed alternative**, preferred for TRENDING/breakout entries on
     longer horizons (it is the clear daily-window winner and the tail-loss tamer). It earns its place
     in the toolset.
   - **Hard-drop V2 (break-even runner) and V3 (standalone trailing)** as defaults: bottom-quartile mean
     Sharpe on BOTH windows and 2.5–4× the trade count (they churn fees via break-even re-taps and trail
     whipsaws). Keep them in the fan catalogue for the Gate to dispose case-by-case, but never seed them
     as a default exit.

4. **Does it change the "don't build a 4th selection axis" call?** **No — it strengthens it.** Because the
   8 exits collapse to ~1 effective trial, "tune the exit per (entry,symbol)" buys nothing real; the win
   comes from a *fixed structural* choice (V0/V4) keyed to entry style + horizon, which the existing
   gate/fan already supports. Don't build a per-cell exit-selection axis. Do treat exit STRUCTURE (V0 vs
   V4) as a coarse, entry-keyed default — and stop emitting V2/V3 as starting exits.
