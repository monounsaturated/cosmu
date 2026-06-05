# Phase-0 Funding-as-CROWDING Cohort Gate Verdict (P0.7)

> **The pivot after carry was falsified.** Spot funding-CARRY (harvesting the premium) is dead
> (see `phase0-carry-verdict.md` §2b/§3 — well-powered FAIL on deep data). This report tests the
> DIFFERENT thesis: funding as a **CROWDING / POSITIONING signal** — an extreme funding rate marks a
> lopsided, over-levered book (a precondition for a squeeze), and *low/uncrowded* funding marks a
> safer entry. We pre-register the kill/keep rule **before** running, route the family through the
> EXISTING deterministic Gate as ONE COHORT (so the multiple-testing correction applies across the
> family, not per-spec), and record the honest result. No manufactured PASS; no threshold was lowered.

Status legend: **PASS** · **FAIL** · **INSUFFICIENT-DATA**.

---

## 1. Pre-registered criteria (written BEFORE running)

The Gate's statistical thresholds are the existing, untouched `GateSettings` / scorer
(`min_trades=30`, `min_deflated_sharpe_prob=0.95`, `max_cscv_pbo=0.50`, `min_folds_positive`,
`max_drawdown=0.25`, `must_beat_buy_and_hold`, untouched holdout) **and** the cohort BH-FDR at
**q = 0.10** (`cosmu/master/cohort.py:promote_cohort` + `cosmu/master/fdr.py`). **None changed.**

### PASS — per spec, ALL must hold (and it must survive the cohort FDR)
1. **Deflated Sharpe ≥ 0.95** net of all cost, across **≥ 2 regimes** (`regimes_positive ≥ 2`).
2. **CSCV-PBO < 0.50** (real PBO over the spec's own Finder grid streams).
3. **Survives cohort BH-FDR at q = 0.10** — judged together with the whole family, not alone.
4. **Beats buy-and-hold** net of the same costs.
5. **`cost_ratio` healthy** — net edge is not a thin sliver of gross (informative floor 0.40).

### KILL (FAIL)
- No spec clears (1)–(4) after an honest, fully-powered run, OR every spec is rejected by FDR.

### INSUFFICIENT-DATA (honest abstention)
- The funding/bar history is too shallow to produce ≥ 30 trades on the deepest spec, OR < 2 regimes
  spanned. (The carry re-run already established the data is deep enough for power — 86–337 trades.)

### Note on corr-to-BTC
corr-to-BTC was a PASS criterion for the **delta-neutral carry pair** (it tests that beta cancels).
These five specs are **long-only / single-direction DIRECTIONAL** books — a high corr-to-BTC is
*expected*, not a flaw — so the neutrality criterion **does not apply** here. Directional exposure
is instead disciplined by the regimes+ and beats-buy-and-hold criteria. (The harness reports
corr-to-BTC as `n/a` rather than a misleading number, because `val_returns` is a pooled
multi-symbol stream for which a single-series Pearson vs BTC is undefined.)

### The cohort (existing scorer/FDR — no threshold changes)
- `funding-contrarian-crash-filter.json` — SHORT (direction −1): fade a crowded-long funding extreme
  (`funding_rate > extreme_floor`) after a run-up, in a calm regime.
- `funding-reset-reversion-uncrowded-oversold.json` — LONG: buy oversold RSI **only when funding is
  uncrowded** (`funding_rate < ceiling`).
- `xsec-momentum-funding-gated.json` — LONG: weekly cross-sectional momentum gated by an uncrowded
  funding ceiling + a calm vol ceiling.
- `vol-regime-gated-momentum.json` — LONG: momentum that participates only inside a calm realized-vol
  regime band (no funding term — the vol-regime control arm).
- `funding-gated-momentum.json` — LONG: medium-term momentum with funding as a crowding FILTER +
  an MA trend filter (authored from `funding-gated-momentum.md` via the create-strategy path).

---

## 2. Results — 2026-06-05 (DEEP DATA, the binding verdict)

Run via the new deterministic harness `cosmu/research/funding_crowding_cohort.py`
(`cd apps/engine && PYTHONPATH=. python3 -m cosmu.research.funding_crowding_cohort`), offline on
**cached real Binance daily bars + cached real Binance USDⓈ-M funding** + PIT taker fees. For each
spec the harness builds the spec's coarse Finder GRID (`lab.finder.build_grid`, ≤ 64 variants),
screens every variant on the real bars/funding/fees, **records each variant as a trial** (so
deflation/FDR see the true count), takes the gate-best variant, and computes a gross (zero-cost) run
for `cost_ratio` and a real CSCV-PBO over the grid's validation streams. The five gate-best
representatives are then routed through `promote_cohort(..., fdr_q=0.10, register=False,
trials=trial_stats(store))` — **one cohort, BH-FDR across the family**. Deterministic; zero LLM.

**Data source:** `live-cached` (real Binance bars + real funding). **NOT synthetic.**
**Traded window:** `2024-08-07 .. 2026-06-05` (~668 days), clipped to the funding overlap.
**Regimes in window** (bar-labels summed across the universe): **chop 5136 · bear 8707 · bull 6197** —
all three present, spanning the deep 2024H2–2025 bear.
**Funding depth used:** 20/30 universe symbols carry funding (max 3000 8h points/symbol; 10 symbols
are bars-only and contribute to the xsec rank but not the funding filter). The deepest spec trades
**827** times — fully powered, no INSUFFICIENT-DATA abstention.

**Calibration (data-driven, no threshold lowered).** Three of the funding-ceiling param ranges had
their TOP end recalibrated to the realized funding scale, fixing the exact degeneracy the carry
verdict flagged (a ceiling sitting *above* realized max funding never excludes any bar, so the grid's
high points are no-op filters): `reset-reversion` `funding_ceiling [0, 5e-3] → [-1e-4, 1e-4]`;
`xsec-momentum` `funding_ceiling [1e-4, 1e-2] → [-2e-5, 1e-4]`; the new `funding-gated-momentum`
ceiling authored at `[-2e-5, 1e-4]`. Realized Binance funding (20 sym × ~730d, 45,421 8h points):
mean **+2.2e-5**, p50 **+4.9e-5**, p75/p90 clamp **+1.0e-4** (Binance cap), p99 **+2.9e-4**, max
**+7.2e-4**, min **−1.18e-2**; 68% of periods positive. The recalibrated ceilings straddle the
realized distribution so the crowding filter genuinely bites. The `crash-filter`'s extreme floor
`[1e-4, 5e-4]` already straddles p90→max (the crowded tail) and was left as-is.

| Spec | dir | net ret | gross | cost_ratio | deflated-Sharpe | CSCV-PBO | regimes+ | trades | maxDD | skew | corr-BTC | gate | FDR |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| funding-contrarian-crash-filter | −1 | +0.10% | +0.10% | 1.00 | 0.512 | 0.271 | 1 | 2 | 0.007 | +50.6 | n/a | STOP | ✗ |
| funding-reset-reversion-uncrowded-oversold | +1 | +1.41% | +1.48% | 0.96 | **0.714** | 0.000 | 1 | 61 | 0.048 | +6.3 | n/a | STOP | ✗ |
| xsec-momentum-funding-gated | +1 | +0.47% | +0.52% | 0.91 | 0.600 | 0.114 | 2 | 48 | 0.010 | +21.0 | n/a | STOP | ✗ |
| vol-regime-gated-momentum | +1 | +0.17% | +0.19% | 0.92 | 0.358 | 0.257 | 2 | 16 | 0.010 | +2.1 | n/a | STOP | ✗ |
| funding-gated-momentum | +1 | +0.33% | +1.19% | 0.28 | 0.062 | 0.100 | 1 | 827 | 0.077 | +0.6 | n/a | STOP | ✗ |

**Cohort BH-FDR (q = 0.10):** p-values `[0.488, 0.286, 0.400, 0.642, 0.938]`; BH cutoff **0.000** —
**no spec survives FDR.** Even the best (reset-reversion, p = 0.286) is an order of magnitude above
the cutoff. There is no near-miss to re-examine.

Notes against the pre-registered criteria:

- **deflated-Sharpe ✗ (the binding failure)** — best arm is reset-reversion at DSR **0.714**, then
  xsec 0.600, crash-filter 0.512, vol-regime 0.358, funding-gated-momentum 0.062 — **all below the
  0.95 bar.** With ~668 days and up to 827 trades, the test has the power to judge: there is **no
  statistically significant net edge** against the trial-inflated benchmark.
- **cost_ratio** — healthy (0.91–1.00) for the selective specs; **fees are NOT the killer** there.
  The one exception is `funding-gated-momentum` at **0.28** — its loose grid trades 827 times and
  bleeds 72% of gross to costs, the classic over-trading-an-absent-edge signature (DSR 0.062).
- **regimes** — only xsec and vol-regime reach **2** positive regimes; the rest are positive in 1.
  Moot given the DSR/FDR failures.
- **beats buy-and-hold ✗** — none of the net returns (+0.10%…+1.41%) clears a buy-and-hold baseline
  over this window.
- **CSCV-PBO** — mostly healthy (0.00–0.27), so the individual fits are not obviously overfit; the
  failure is a genuine *absence of edge*, not overfitting. (vol-regime 0.26, crash-filter 0.27 are
  fine; nothing exceeds 0.50.)
- **tail/skew ✓** — all skews positive; maxDD ≤ 7.7% (well under the 0.25 bar). No fat left tail.

**No false positive to chase.** The highest DSR anywhere is 0.714 — below the 0.95 bar even *before*
the FDR correction — so there is no survivor and no near-miss to re-audit for look-ahead.

## 3. Verdict

### **FAIL** — well-powered, on deep data; the cohort FDR rejects the whole family

**Headline:** Funding-as-crowding does not clear the Gate on Binance spot. Recalibrating the crowding
ceilings to the realized funding scale (so the filter genuinely bites) and running the five specs as
one cohort over ~668 days / all three regimes / up to 827 trades, **no spec survives** — best
deflated-Sharpe **0.714** (uncrowded-oversold reversion) vs the **0.95** bar, and the cohort BH-FDR
at q = 0.10 rejects every candidate (BH cutoff 0.000). It is **not** a fee problem for the selective
specs (cost_ratio 0.91–1.00) and **not** an overfit problem (PBO ≤ 0.27): there simply is **no
significant net directional edge** from conditioning on the funding-crowding signal here.

**Honest decomposition:**

1. **Funding-as-crowding (the contrarian/filter use) — FAIL.** Whether used to *fade* a crowded-long
   extreme (crash-filter, DSR 0.512, only 2 trades — the extreme is too rare even on deep data) or to
   *gate* a long entry to uncrowded funding (reset-reversion 0.714, xsec 0.600, funding-gated 0.062),
   the crowding condition does not lift a directional book above the deflated-Sharpe bar. The best
   single result is the uncrowded-oversold reversion (DSR 0.714, 61 trades, +1.41%) — real and
   positive, but not significant net of the trial-inflated benchmark, and rejected by FDR.
2. **Vol-regime-gated momentum (the no-funding control) — FAIL.** DSR 0.358 on 16 trades; the calm-vol
   gate alone (no funding term) is the weakest selective arm, confirming the funding gate is not the
   thing holding the others back — the directional momentum edge just isn't there net of cost.

**Phase-0 GATE decision:** Do **NOT** proceed to live. **No live capital.** This is a clean,
well-powered negative on real Binance spot data, net of cost: the funding-as-crowding/positioning
thesis — across both the contrarian-fade and the uncrowded-filter forms — **does not have an
exploitable edge** that clears the deflated-Sharpe bar and survives a family-wise FDR correction.

**Skeptic's checklist (applied because a near-survivor would be COSMU's first edge):** there is no
survivor. The top candidate (DSR 0.714) is below the bar and far above the FDR cutoff, so no
look-ahead re-audit is warranted. The features (funding_rate, ret_Nd, vol_realized, rsi) are joined
strictly point-in-time (`align_asof` — latest funding ≤ bar close; `funding_feature` null on the
momentum specs so no carry is double-counted). Trade counts are adequate (48–827) except the
crash-filter (2 — the crowded-long *extreme* is genuinely rare, an honest data-scarcity note, not a
fail driver). PBO ≤ 0.27 rules out single-regime overfit luck. The param spaces were tightened (not
loosened) toward the realized funding scale.

**Recommended next actions (priority order):**
1. **Retire funding-as-crowding for Phase-0 spot** — like carry, it is now falsified with power on
   the family, not merely unproven. The crowding signal is real in the data but too weak to lift a
   long-only / single-short spot book over the bar after costs. Do not keep re-running variants on
   more Binance spot funding.
2. **The single highest-value next action:** pivot to the **meta-labeling** direction (in the
   strategy-research notes) — instead of using funding as a standalone entry condition, train a
   meta-label on whether a primary momentum/reversion signal should be *taken*, with funding as one
   feature among several. That is the documented path with post-cost headroom that neither carry nor
   raw funding-crowding has shown. If that also fails the Gate, the spot-only-Phase-0 conclusion is
   essentially closed and the next move is the derivatives-plan (cross-venue / funding-dispersion),
   which is out of current scope.

> **Reproduce:** `cd apps/engine && PYTHONPATH=. python3 -m cosmu.research.funding_crowding_cohort`
> (offline, deterministic, on the cached real bars + cached real funding under
> `.cosmu/market_data/binance{,_funding}/`).
