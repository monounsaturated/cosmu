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

Run via the deterministic harness `cosmu/research/carry_ablation.py`
(`python3 -m cosmu.research.carry_ablation`), offline on **cached real Binance daily bars + cached
real Binance USDⓈ-M funding history** + PIT taker fees from the venue catalog. The harness
grid-screens each authored spec's param space (Finder-faithful) and runs every arm through the
**existing, untouched** scorer (`master/scorer.py:score`) + trial ledger. Deterministic across runs.

**Data source:** `live-cached` (real Binance bars + real funding). **NOT synthetic.**
**Traded window:** `2025-05-01 .. 2026-03-29` — clipped to where real funding exists (~333 days).
**Regimes in window:** chop 605 · bull 455 · bear 605 bar-labels (all three regimes present; BTC net
**−30%** over the window — a genuine bear/chop test, not a bull-market freebie).
**Funding depth:** 1000 8h points/symbol = the hard `/fapi/v1/fundingRate` REST cap ≈ 333 days, **one
window**. Realized Binance funding over the window: mean ≈ **3.1e-5 / 8h period** (≈ **+0.7%/yr**
annualized) — a real but *very thin* premium.

| Arm | net ret | gross ret | cost_ratio | deflated-Sharpe | CSCV-PBO | regimes+ | trades | maxDD | skew | corr-BTC | gate |
|---|---|---|---|---|---|---|---|---|---|---|---|
| carry_short_perp | +0.03% | +0.05% | 0.51 | 0.117 | 0.653 | 1 | 12 | 0.007 | +5.8 | 0.00 | STOP |
| carry_long_spot | +0.84% | +0.86% | 0.98 | 0.504 | 0.645 | 1 | 3 | 0.014 | +2.5 | 0.00 | STOP |
| **neutral_carry_pair** | **+0.43%** | +0.46% | **0.95** | **0.049** | 0.653 | **1** | **15** | 0.014 | 0.0 | **0.00** | **STOP** |
| price_only_short | 0.00% | 0.00% | – | 0.050 | 0.675 | 0 | 0 | 0.000 | 0.0 | 0.00 | STOP |
| **xsec_neutral_pair** | **+2.26%** | +2.47% | **0.91** | **0.035** | 0.491 | **3** | **94** | 0.056 | 0.0 | **0.00** | **STOP** |
| buy_and_hold | +15.04% | +15.24% | 0.99 | – | – | 3 | 5 | – | +0.4 | −0.04 | baseline |

Notes against the pre-registered criteria:

- **corr-to-BTC ≈ 0 ✓** — both neutral arms show corr-BTC ≈ 0.00 (xsec) / 0.00 (carry pair). The
  market-neutrality construction works: beta cancels. This criterion *passes* for the neutral arms.
- **cost_ratio healthy ✓** — 0.91–0.98 on the deep arms. **Fees are NOT the killer.** Costs eat
  only 5–9% of gross. (carry_short's 0.51 is on a 12-trade sliver — noisy.)
- **deflated-Sharpe ✗** — the binding failure. Best neutral arm DSR = **0.049** (carry pair) /
  **0.035** (xsec) vs the **0.95** pre-registered bar. There is **no statistically significant
  edge** against the trial-inflated benchmark.
- **beats buy-and-hold ✗** — over this (recovery) window B&H returned **+15%**; the neutral arms
  returned **+0.4% / +2.3%** net. The neutral books did not beat passive holding.
- **regimes ✗ (carry) / ✓ (xsec)** — the carry pair was positive in only **1** regime; xsec was
  positive in all **3** but at a magnitude far below significance.
- **trade-count / data depth ⚠️** — the **carry-specific** arms (short-perp / long-spot / neutral
  pair) trade only **3–15** times (< 30) on the single ~333-day funding window. The realized carry
  premium (~0.7%/yr) is structurally too small for the spec's trade frequency to compound into
  significance in one window. **The carry thesis alone is INSUFFICIENT-DATA.** The xsec-neutral arm
  *does* clear the trade-count bar (94 trades) — and clearly FAILs the edge bar.
- **tail/skew ✓** — no unacceptable left tail (skews are positive or ≈0; the high +5.8 on
  carry_short is a small-sample artifact of 12 trades, not a fat left tail). maxDD ≤ 5.6%.

## 3. Verdict

### **FAIL** (with a carry-specific **INSUFFICIENT-DATA** caveat)

**Headline:** On real Binance data, net of all cost, **neither the funding-carry nor the
cross-sectional-neutral book survives the Gate.** The edge is not eaten by fees (cost_ratio
0.91–0.98) — there simply **is no significant net edge**: deflated-Sharpe ≈ 0.04–0.05 vs the 0.95
bar, and neither neutral book beats buy-and-hold (+0.4%/+2.3% vs +15%) over the window.

**Honest decomposition of the two theses:**

1. **Funding-carry — INSUFFICIENT-DATA.** Two compounding problems: (a) the authored
   `funding_floor` param range (`[0.0001, 0.005]` per period) sits **entirely above** realized
   Binance funding (window max = 0.0001, p90 = 9.6e-5), so the spec as authored barely enters; even
   at realistic low floors it produces only ~3–15 trades on the one ~333-day funding window; (b) the
   realized premium (~0.7%/yr) is too thin to clear DSR at that frequency. This is **not a clean
   falsification** — the carry sample is too shallow/thin to conclude. **Next action: historical-
   funding backfill** (deeper than the 1000-row REST cap — paginated `endTime` walk or a funding
   archive — to get multiple years / multiple funding regimes) AND **re-calibrate `funding_floor` to
   the realized scale**, then re-run P0.6. Until then the carry edge is **neither confirmed nor
   falsified**.

2. **Cross-sectional-neutral momentum — FAIL (on this data).** This arm has the depth to judge: 94
   trades, all 3 regimes positive, genuinely market-neutral (corr-BTC ≈ 0), healthy cost_ratio
   (0.91). But deflated-Sharpe = 0.035 (vs 0.95) and net +2.3% badly trails B&H's +15%. On the
   available real window there is **no exploitable cross-sectional edge** after costs at this small
   (5-asset) universe.

**Phase-0 GATE decision (per DERIVATIVES_PLAN §8):** Do **NOT** proceed to Phase 1 (live-small) on
these results. No live capital. The thesis is **not yet validated**; the cheap, honest learning is:
the 5-asset spot-funding universe with one ~333-day funding window cannot demonstrate the edge.

**Recommended next actions (in priority order):**
1. **Historical-funding backfill** — get multi-year funding (multiple funding regimes), then re-run
   the carry arm. This is the single highest-value unblock; the carry thesis is currently
   unfalsified, not dead.
2. **Re-calibrate the carry spec** — `funding_floor` range must straddle realized funding
   (~1e-5 .. 1e-4 per period), not 1e-4 .. 5e-3.
3. **Widen the xsec universe** — 5 assets is too few for a real cross-sectional rank; a 20–50 liquid-
   perp universe is where xsec-neutral momentum has documented headroom. Re-run with the wider
   universe before declaring xsec dead.

> **Reproduce:** `cd apps/engine && PYTHONPATH=. python3 -m cosmu.research.carry_ablation`
> (offline, deterministic, on the cached real bars + cached real funding under
> `.cosmu/market_data/`). Offline tests: `tests/test_carry_ablation.py`.
