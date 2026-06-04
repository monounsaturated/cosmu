# Phase-0 Carry / Neutral Gate Verdict (P0.6)

> **The make-or-break.** Does the market-neutral funding-carry / cross-sectional-neutral edge
> survive the deterministic Gate on REAL Binance data, net of all cost? This report pre-registers
> the kill/keep criteria **before** running, then records the honest result. No manufactured PASS.

Status legend: **PASS** · **FAIL** · **INSUFFICIENT-DATA**.

---

## 1. Pre-registered criteria (written BEFORE running — do not edit after the run)

Pre-registered 2026-06-04. The Gate's statistical thresholds are the existing, untouched
`GateSettings` / `research.gate.PREREGISTERED_BAR` (min_trades=30, min_deflated_sharpe_prob=0.95,
max_pbo / max_cscv_pbo=0.50, max_drawdown=0.25, min_folds_positive_pct=0.60,
must_beat_buy_and_hold, holdout_min_deflated_sharpe>0, BH-FDR q=0.10). **None of these is changed
for this run.** The criteria below are the *interpretation rule* applied to the verdict the
existing Gate emits.

### PASS — all of the following must hold
1. **Net-of-all-cost positive** (real fees + slippage + funding) across **≥ 2 regimes**
   (`regimes_positive ≥ 2` in the verdict's `regime_returns`).
2. **Deflated Sharpe** clears the pre-registered bar: `deflated_sharpe_prob ≥ 0.95`
   (DSR against the trial-inflated benchmark — the existing scorer).
3. **CSCV-PBO < 0.50** (the existing `cscv_pbo` over a legitimate config population).
4. **Survives cohort BH-FDR** at q = 0.10 (the existing `promote_cohort` / `fdr.py`).
5. **`cost_ratio` healthy** — net edge is **not a thin sliver of gross**. Pre-registered floor:
   **`cost_ratio ≥ 0.40`** (≥ 40% of gross alpha survives costs). Below that the edge is fragile
   even if statistically "significant".
6. **corr-to-BTC ≈ 0** for the neutral arm — pre-registered band: **|corr| ≤ 0.30** on the
   traded-bar return series vs BTC daily returns (a directional book would show |corr| → 1).
7. **Trade count / data depth sufficient**: **≥ 30 trades** on the validation slice (the Gate's
   `min_trades`) AND the funding history is deep enough to actually generate them.

### KILL (FAIL) — any of the following
- None of (1)–(6) clear after honest attempts, OR
- net edge is a **sliver of gross** (`cost_ratio < 0.40`), OR
- the neutral arm does **not** beat both price-only and buy-and-hold net of the same costs, OR
- **tail/skew is unacceptable**: pre-registered as `max_drawdown ≥ 0.25` (the Gate bar) OR a
  validation-return **skew < −2.0** with that left tail driving the mean (carry's documented
  negative-skew failure mode — steady gains, rare violent loss).

### INSUFFICIENT-DATA (honest abstention, NOT a fail and NOT a fake pass)
- The funding history available (Binance `/fapi/v1/fundingRate`, max 1000 rows ≈ 333 days at 8h
  periods) is **too shallow** to produce **≥ 30 trades** on the carry arm, OR
- fewer than 2 regimes are spanned by the available window, OR
- the neutral pair cannot be marked because perp/funding data is missing for the symbols.
- In this case the verdict is **INSUFFICIENT-DATA** with the next action: **historical-funding
  backfill** (deeper than the 1000-row REST cap — e.g. paginated `endTime` walk or a vendor
  funding archive) before re-running P0.6. This thesis is then **neither confirmed nor falsified**.

### Arms to run (existing gate/scorer/FDR — no threshold changes)
- **Carry arm** — funding-carry short-perp leg (`funding-carry-short-perp.json`) and the long-spot
  leg, on real bars + real funding + PIT fees, single-asset.
- **Neutral-carry arm** — the delta-neutral long-spot/short-perp **pair** (price legs cancel;
  residual = funding carry − costs on both legs).
- **xsec-neutral arm** — cross-sectional long/short momentum (`xsec-neutral-momentum-*.json`),
  long-leader leg minus short-laggard leg, on the real universe.
- **Ablation baselines** — price-only (same entry, no funding/neutral) and buy-and-hold, all net
  of the **same** real costs.

---

## 2. Results

*(filled in by the deterministic harness below — `cosmu/research/carry_ablation.py`,
run offline on cached real Binance bars + real funding history.)*

<!-- RESULTS -->

## 3. Verdict

<!-- VERDICT -->
