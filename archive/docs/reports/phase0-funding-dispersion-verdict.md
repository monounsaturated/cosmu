# Phase-0 Cross-Sectional Funding-Dispersion Verdict (P0.6 — perp cost surface)

> **The make-or-break for the dispersion path.** Does the dollar-neutral cross-sectional
> funding-dispersion pair (long bottom-quartile funding · short top-quartile funding) survive a
> grid of **REAL** perpetual-futures cost scenarios (OKX / Kraken-Futures taker fees × funding
> regimes) on **REAL** Binance USDⓈ-M funding history? This report records the honest result of the
> just-merged harness `cosmu/research/perp_gate_sweep.py`. **No threshold changes. No manufactured
> PASS.**

Status legend: **PASS** · **FAIL** · **INSUFFICIENT-DATA**.

Run date: **2026-06-05**. Harness: [`apps/engine/cosmu/research/perp_gate_sweep.py`](../../apps/engine/cosmu/research/perp_gate_sweep.py).
Specs: [`xsec-funding-dispersion-long-leg.json`](../../apps/engine/strategies/inbox/xsec-funding-dispersion-long-leg.json) ·
[`xsec-funding-dispersion-short-leg.json`](../../apps/engine/strategies/inbox/xsec-funding-dispersion-short-leg.json).

---

## 1. Pre-registered criteria (in the harness, unchanged for this run)

The harness ships its own pre-registered, in-code criteria. **None were edited for this run.**

- **Cost scenarios** (`SWEEP_SCENARIOS`): seven fixed venue×funding cells. The OKX (10 bps taker) and
  Kraken-Futures (5 bps taker) fees **match the real venue catalog** (`cosmu/spine/venue.py`:
  `okx.taker_fee_bps=10`, `kraken_futures.taker_fee_bps=5`).
- **`COST_RATIO_FLOOR = 0.40`** — net/gross below this = fragile (fees eat >60% of gross).
- **`SKEW_FLOOR = -2.0`** — pair return-skew below this = carry left-tail failure mode.
- **Verdict rule** (`_verdict`): **PASS** iff the cheapest realistic cell `kf_perp_no_fund`
  (a) `pair_net > 0`, (b) `cost_ratio ≥ 0.40` (not fragile), (c) `pair_skew ≥ −2.0` (no bad tail),
  **and** `kf_perp_typ_fund.pair_net > 0`. Any failure ⇒ **FAIL**. Empty funding cache ⇒
  **INSUFFICIENT-DATA**.

What this verdict **is**: a cost-surface robustness check — does the edge stay positive, non-fragile
and non-bad-tailed once realistic perp fees + funding are applied? What it is **NOT**: a fresh
statistical-significance gate on the pair. (Per-leg variant selection *does* use the real scorer
including the deflated-Sharpe / multiple-testing penalty — `_best_variant` → `score(...)` — but the
pair-level PASS asserts cost-robustness, not significance.) The full-Gate significance run on the
related carry/dispersion edge previously returned **STOP** — see
[`phase0-carry-verdict.md`](phase0-carry-verdict.md).

---

## 2. Data depth (honest)

- **Source:** `live-cached` — **NOT synthetic**. Real cached Binance daily spot bars + real cached
  Binance USDⓈ-M perp **funding** history. PIT taker fees from the venue catalog.
- **Funding depth:** **19 / 20** universe symbols carry **2000** 8h funding points each (the
  `fetch_series` limit; on-disk cache holds ~2190 ≈ **2 years**, 2024-06-04 → 2026-06-04).
  **`ATOMUSDT` has no funding file → it is silently dropped from the cross-section** (effective
  universe = **19 assets**, not 20). Honest gap, not a fake.
- **Traded window:** `2024-03-28 .. 2026-06-05` (~2.2 yr of daily bars; the first ~2 months precede
  funding history, so those bars are unranked — PIT-honest, no look-ahead).
- **Price proxy:** Binance **spot** bars stand in for perp price action (perp ≈ spot; basis ignored).
  A declared simplification, not a hidden one.

---

## 3. Results — verdict: **PASS** (cost-surface criteria) · but economically **trivial**

Harness output (`python -m cosmu.research.perp_gate_sweep`, run **locally** — see §5):

```
verdict       : PASS
data_source   : live-cached
window        : 2024-03-28..2026-06-05
gross pair ret: +0.0032  (frictionless; long-leg skew=+5.03)
```

| scenario | fee bps | fund bps/bar | pair_net | sharpe | skew | kurt | maxDD | cost_ratio | holds | flag |
|---|---:|---:|---:|---:|---:|---:|---:|---:|:--:|---|
| binance_spot_no_fund | 10 | 0 | +0.0029 | 0.253 | +3.53 | 211.8 | 0.0196 | 0.784 | YES | |
| okx_perp_no_fund | 10 | 0 | +0.0029 | 0.253 | +3.53 | 211.8 | 0.0196 | 0.784 | YES | |
| okx_perp_typ_fund | 10 | 3 | +0.1671 | 0.253 | +3.53 | 211.8 | 0.0196 | 45.51 | YES | ⚠ overlay |
| okx_perp_high_fund | 10 | 9 | +0.4956 | 0.253 | +3.53 | 211.8 | 0.0196 | 134.95 | YES | ⚠ overlay |
| kf_perp_no_fund | 5 | 0 | +0.0030 | 0.277 | +3.69 | 212.3 | 0.0196 | 0.823 | YES | |
| kf_perp_typ_fund | 5 | 3 | +0.1673 | 0.277 | +3.69 | 212.3 | 0.0196 | 45.55 | YES | ⚠ overlay |
| gross_frictionless | 0 | 0 | +0.0032 | 0.300 | +3.84 | 212.6 | 0.0197 | 0.862 | YES | |

**Decisive cell** `kf_perp_no_fund`: `holds=True · fragile=False · bad_tail=False`, and
`kf_perp_typ_fund.holds=True` ⇒ the harness emits **PASS**. The criteria were applied verbatim; the
verdict was not altered.

---

## 4. Honest reading — why this PASS does **not** clear the bar to deploy

1. **The surviving edge is economically negligible.** The only cells that reflect *realized* P&L are
   the no-funding rows: **+0.30 %** total over **~2.2 years** at Kraken-Futures 5 bps (≈ **+0.14 %/yr**),
   net of real fees and real PIT funding. Gross (frictionless) is **+0.32 %**. This is noise-level — a
   rounding error, not a money machine. The pre-registered cost-surface criteria contain **no minimum
   economic-magnitude floor**, so a statistically-positive-but-trivial result passes them.

2. **The headline funded rows (+16.7 %, +49.6 %) are a double-count — do not read them as alpha.**
   The backtest **already accrues real PIT funding** as cash P&L on the open leg
   (`_accrue_funding`, [`backtest.py:305`](../../apps/engine/cosmu/data/backtest.py:305)) because both
   specs set `funding_feature: funding_rate`. The perp-sweep's `_apply_funding_cost` then layers a
   **second, synthetic, constant** funding overlay (3 or 9 bps/bar × 5 bars × num_trades) on top of
   already-accrued real funding. The give-away is `cost_ratio` of **45×–135×** (net ≫ gross is
   impossible for a real cost — it only happens when fake income is added). These rows measure a made-up
   constant-funding regime, **not** the strategy. They are flagged ⚠ above and must be discounted.
   *(Verdict impact: the double-count does not by itself flip the PASS — the clean `kf_no_fund` row
   already clears the three sub-checks — but it makes the `kf_typ_fund` "survives typical funding"
   gate vacuous, and the headline numbers misleading. **Fix recommended: drop `_apply_funding_cost`;
   real funding is already in the backtest.**)*

3. **Tail-dominated, low Sharpe.** Pair **kurtosis ≈ 212** means the return series is driven by a
   handful of extreme bars, not a stable premium; pair **Sharpe ≈ 0.25–0.30**. Skew is *positive*
   (+3.5, so `bad_tail=False` — this is not the carry left-tail failure mode), but a +0.3 %/2 yr
   return carried by lottery-like bars is not an exploitable, capacity-bearing edge.

4. **Cost-surface ≠ significance.** This pass is a necessary-but-not-sufficient robustness screen. The
   full Gate (deflated-Sharpe ≥ 0.95, CSCV-PBO < 0.50, cohort BH-FDR) **STOPped** the related
   carry/neutral edge ([`phase0-carry-verdict.md`](phase0-carry-verdict.md)); nothing here overturns
   that.

---

## 5. Compute lane — Modal attempted, **failed**; ran locally instead

The task asked to offload to Modal. Two independent blockers make the Modal lane unusable for this
harness *as wired*, both verified empirically this run:

1. **Binance geo-block (HTTP 451).** From Modal's datacenter IP, `api.binance.com/api/v3/exchangeInfo`
   returns `451 Service unavailable from a restricted location`. The job crashes at live bar-fetch
   (Modal cannot reach Binance; the M2 home IP can).
2. **No funding cache in the image.** The Modal image copies only `apps/engine`; the `.cosmu/`
   funding cache lives at repo root and is **not** shipped, so `CachedFundingRateProvider` would read
   empty → `INSUFFICIENT-DATA`. (`ingest` populates Supabase, not the on-disk cache the harness reads.)

Note also that `pnpm modal:gate` maps to the **full autonomous cycle** (`--job gate_sweep`), *not* the
perp sweep; the correct job is `--job perp_gate_sweep` (which is what failed above).

The sweep was therefore run **locally on the M2** against the real 2-year cache — **deterministic**,
which matches the local-by-default compute policy (cloud only to isolate/parallelize, not for a
single-VM deterministic job). Determinism means the local result *is* the result a fixed-cache cloud
run would reproduce.

**Harness fix applied to run at all:** the merged `_main` called
`fetch_bars(sym, interval="1d", ...)` but the provider API is `fetch_bars(sym, "1d", ...)` — a
`TypeError` that crashed the entrypoint (the harness had never been run end-to-end). Corrected to the
positional `timeframe` arg. No logic, threshold, or scenario change.

---

## 6. Verdict & next action

- **Harness verdict (pre-registered cost-surface criteria, unchanged):** **PASS** — the dispersion
  pair stays positive, non-fragile and non-bad-tailed across the OKX/KF fee grid on real funding.
- **Honest assessment:** a **weak / trivial** pass. The real surviving edge is **~+0.3 % over 2.2
  years**, tail-dominated (kurt ≈ 212, Sharpe ≈ 0.3), and the eye-catching funded rows are a
  funding-overlay **double-count**, not alpha. This is *not* a deployable edge.
- **Recommendation: DO NOT promote to forward-test on this result.** The cost-surface screen is
  necessary but not sufficient; the binding constraints — economic magnitude and the full-Gate
  significance that already STOPped the carry/dispersion family — are not cleared. Two concrete
  harness fixes before any re-run: (1) **remove the `_apply_funding_cost` double-count**; (2) add a
  **minimum economic-magnitude floor** (e.g. annualized net) to the cost-surface verdict so a
  noise-level positive cannot read as PASS.
