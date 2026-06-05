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

> ⚠️ **Superseded run (2026-06-04) below in §2a, kept for the record.** The make-or-break re-run on
> the deep data (2026-06-05) is §2b — read that for the live verdict.

### 2a. Original run — 2026-06-04 (SHALLOW DATA, superseded)

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

This run was blocked by three data problems (all now addressed in §2b): funding only ~333 days
(1000-row REST cap) → 3–15 carry trades; the authored `funding_floor` range `[1e-4, 5e-3]` sat
**above** realized funding (window p90 = 9.6e-5) so the spec barely entered; and the xsec universe
was only 5 assets. The 2026-06-04 verdict was therefore **FAIL with a carry-specific
INSUFFICIENT-DATA caveat** — neither confirmed nor falsified for carry.

### 2b. Re-run — 2026-06-05 (DEEP DATA, the binding verdict)

Same harness, same **untouched** scorer / GateSettings / PREREGISTERED_BAR. The only changes since
§2a are **data depth** (funding backfilled to ~730 days × 20 symbols via
`scripts/backfill_funding.py`; daily bars backfilled to the full ~30-symbol `PERP_UNIVERSE` via
`manage_data backfill bars:binance`) and a **data-driven recalibration of `funding_floor`** in the
two carry specs from `[1e-4, 5e-3]` to `[1e-5, 1.5e-4]` (plus `funding_exit_floor` → `[-1e-4, 5e-5]`
and the degenerate xsec long-leg `funding_ceiling` `[1e-3, 1e-2]` → `[1e-4, 5e-4]`, which previously
never excluded any bar because it sat above realized max funding 7.2e-4). **No Gate/scorer threshold
changed.**

**Realized funding distribution** (20-symbol universe, 730d, 46,205 8h points, measured from the DB
to set the floor from data not guesswork): mean **+2.3e-5**/period, p50 **+4.9e-5**, p90/p95 clamp at
**+1.0e-4** (Binance funding cap clustering), p99 **+2.9e-4**, max **+7.2e-4**, min **−1.18e-2**.
Positive 68% of periods (positive-only mean **+8.0e-5**). The recalibrated floor `[1e-5, 1.5e-4]`
**straddles** realized positive funding (below the median up to just above the cap) — exactly the
verdict's prescription. Annualized, the realized premium is ≈ **+2.5%/yr** gross across all periods.

**Data source:** `live-cached` (real Binance bars + real funding). **NOT synthetic.**
**Traded window:** `2024-08-07 .. 2026-06-05` (~668 days), clipped to the funding overlap.
**Regimes in window** (bar-labels summed across the universe): **chop 5136 · bear 8707 · bull 6197** —
all three present, and this window spans the deep 2024H2–2025 bear (B&H net only +3.0% over it).
**Funding depth used by the run:** **2000 8h points/symbol** for **20 symbols** (the per-symbol cache
holds 2190; the harness reads `len(bars)+1100 ≈ 2000` — well past the 1000-row cap that blocked §2a),
**0** for the 10 universe symbols lacking funding history (ATOM/SUI/SEI/TIA/AAVE/ETC/XLM/ICP/RUNE/GALA
— excluded from the carry arms, present only as extra bars for the xsec rank).

| Arm | net ret | gross ret | cost_ratio | deflated-Sharpe | CSCV-PBO | regimes+ | trades | maxDD | skew | corr-BTC | gate |
|---|---|---|---|---|---|---|---|---|---|---|---|
| carry_short_perp | +0.83% | +0.91% | 0.91 | 0.429 | 0.537 | 1 | 251 | 0.065 | +4.2 | 0.00 | STOP |
| carry_long_spot | +0.29% | +0.37% | 0.78 | 0.390 | 0.630 | 1 | 86 | 0.022 | +7.0 | 0.00 | STOP |
| **neutral_carry_pair** | **+0.56%** | +0.64% | **0.87** | **0.183** | 0.630 | **2** | **337** | 0.065 | 0.0 | **0.00** | **STOP** |
| price_only_short | 0.00% | 0.00% | – | 0.024 | 0.675 | 0 | 0 | 0.000 | 0.0 | 0.00 | STOP |
| **xsec_neutral_pair** | **+0.28%** | +0.30% | **0.91** | **0.073** | 0.651 | **1** | **110** | 0.128 | 0.0 | **0.00** | **STOP** |
| buy_and_hold | +3.03% | +3.23% | 0.94 | – | – | 3 | 30 | – | +1.3 | −0.02 | baseline |

Notes against the pre-registered criteria:

- **trade-count / data depth ✓ (RESOLVED)** — the recalibrated floor + deeper data take the carry
  arms from 3–15 trades to **86–337**, and xsec to 110. **Every neutral/carry arm now clears the
  `min_trades=30` bar.** The §2a INSUFFICIENT-DATA blocker is gone: this is now a **fully-powered,
  honest test**, not an abstention. (The harness emitted **no** INSUFFICIENT-DATA / carry-caveat
  note this run — confirming the depth condition is satisfied.)
- **corr-to-BTC ≈ 0 ✓** — both neutral arms (and both carry legs) show corr-BTC = 0.00. The
  delta-neutral construction still cancels beta. This criterion passes.
- **cost_ratio healthy ✓** — 0.78–0.91 across the deep arms. **Fees are still NOT the killer** —
  costs eat only 9–22% of gross.
- **deflated-Sharpe ✗ (the binding failure)** — best arm is carry_short_perp at DSR **0.429**, then
  carry_long 0.390, neutral pair **0.183**, xsec **0.073** — all far below the **0.95** pre-registered
  bar. With ~668 days and hundreds of trades, the test now has the power to judge, and there is **no
  statistically significant net edge** against the trial-inflated benchmark.
- **CSCV-PBO ✗** — 0.54–0.65 on the neutral/carry arms, above the 0.50 max (overfit-prone).
- **beats buy-and-hold ✗** — even though this window's B&H is weak (+3.0%, it includes the bear), the
  best neutral book (+0.56%) still does not beat it.
- **regimes** — neutral_carry_pair positive in **2** regimes (clears the ≥2 sub-criterion), but the
  carry legs and xsec are positive in only **1**; moot given the DSR/PBO/B&H failures.
- **tail/skew ✓** — skews positive or ≈0 (no fat left tail); maxDD ≤ 12.8% (< the 0.25 bar).

**No false positive to chase.** The highest DSR anywhere is 0.429 — less than half the 0.95 bar — so
there is no near-miss to re-examine for look-ahead. The result is unambiguously below threshold.

## 3. Verdict

### **FAIL** — well-powered, on deep data (no longer INSUFFICIENT-DATA)

**Headline:** With funding deepened to ~730d × 20 symbols, the carry universe widened to ~30 assets,
and `funding_floor` recalibrated to the realized funding scale (data-driven, not guessed), the carry
arms now trade **86–337 times** and the test is **fully powered** — and **the edge still does not
survive the Gate.** It is not eaten by fees (cost_ratio 0.78–0.91); there simply **is no significant
net edge**: best deflated-Sharpe **0.429** (carry short perp) vs the **0.95** bar, CSCV-PBO 0.54–0.65
(> 0.50), and no neutral book beats buy-and-hold. The 2026-06-04 carry-specific **INSUFFICIENT-DATA**
caveat is now **resolved into a FALSIFICATION on this data**.

**Honest decomposition of the two theses:**

1. **Funding-carry — FAIL (now falsified on the deep window, not abstained).** The realized Binance
   funding premium is real but tiny (≈ +2.5%/yr gross, mean +2.3e-5/8h, p90 clamped at the +1e-4 cap)
   and after the carry-entry filter + fees it does not compound into a statistically significant edge
   even with 251 short-perp / 86 long-spot / 337 pair trades over ~668 days spanning all three
   regimes. Best DSR 0.429, PBO 0.54–0.63. The thin premium that §2a *suspected* would not clear is
   now *measured* not to clear with adequate power.
2. **Cross-sectional-neutral momentum — FAIL.** With the universe widened from 5 → ~30 assets it
   still scores DSR **0.073** (PBO 0.65), net +0.28% — the widened rank did not unlock an edge. Of the
   verdict's three §3 next-actions, widening the universe is now done and did **not** rescue xsec.

**Phase-0 GATE decision (per DERIVATIVES_PLAN §8):** Do **NOT** proceed to Phase 1 (live-small). **No
live capital.** Unlike 2026-06-04, this is a clean, well-powered negative: on real Binance spot data,
net of cost, the funding-carry and cross-sectional-neutral theses **do not have an exploitable edge**.
The cheap, honest learning: the Binance funding premium is structurally too thin (capped near +1e-4,
≈ +2.5%/yr) for a spot-only carry book to clear the deflated-Sharpe bar, and 30-asset xsec-neutral
momentum is not significant after costs over this window.

**Recommended next actions (in priority order):**
1. **Retire the spot-funding-carry thesis for Phase-0** — it is now falsified with power, not merely
   unproven. Do not keep re-running it on more Binance spot data; the binding limit is the realized
   premium (the per-period funding cap), which more history cannot raise. The only way carry could
   pay is leveraged perp-vs-perp basis (cross-venue / funding-dispersion), which is **out of the
   spot-only Phase-0 scope** — log it as a future derivatives-plan item, not a Phase-0 retry.
2. **Pivot research effort off carry/xsec-neutral** toward a thesis with documented post-cost
   headroom on spot (the meta-labeling + funding-contrarian-filter direction in the strategy-research
   notes), rather than spending more compute on this falsified pair.
3. (Superseded) The §2a actions — funding backfill, floor recalibration, universe widening — are all
   **done**; none changed the verdict.

> **Reproduce:** `cd apps/engine && PYTHONPATH=. python3 -m cosmu.research.carry_ablation`
> (offline, deterministic, on the cached real bars + cached real funding under
> `.cosmu/market_data/binance{,_funding}/`; the funding cache is materialized from the DB backfill —
> 20 symbols × ~2190 8h points). Offline tests: `tests/test_carry_ablation.py`.
