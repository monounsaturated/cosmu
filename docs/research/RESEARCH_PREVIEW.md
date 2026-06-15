# Research preview — everything we tested, and the smart stuff we learned

_Auto-generated from the standardized Research Registry (14 experiments). Every future exploration logs here in the SAME format — `research_registry.record(ResearchExperiment(...))`. Source of truth: R2 `cosmu-lake/research_registry/`._

## Scoreboard — 14 experiments

- **Tradeable edges found:** 1 (see EDGE rows).
- **Verdicts:** NO_EDGE=11 · CANDIDATE=1 · ARTIFACT=1 · INFRA=1
- **By family:** astro=11 · calendar=1 · geomag=1 · real-signal=1

## Every experiment (sortable)

| date | family | experiment | verdict | tradeable | headline |
|---|---|---|---|---|---|
| 2026-06-14 | astro | Astrology vs markets — single-signal IC | **NO_EDGE** | — | 0 / 4,092 IC tests survive BH-FDR; astro-only weekly p≈0.72. |
| 2026-06-14 | astro | Deep astro vs the REAL alt-data baseline | **NO_EDGE** | — | IC 0/32,372 survive FDR; astro DEGRADES OOS AUC by -0.015 (h1)/-0.042 (h5), p=1.0. |
| 2026-06-15 | astro | Multi-signal composite + cross-sectional natal | **NO_EDGE** | — | train→OOS ranking INVERTS (best-train group = worst-OOS) — the fingerprint of noise; astro dilutes. |
| 2026-06-15 | astro | Vol/turnover around named astro events | **CANDIDATE** | — | Apparent full-moon/eclipse realized-VOL effect: 3/76 survive BH-FDR — flagged as candidate. |
| 2026-06-15 | astro | Lunar realized-vol candidate — decisive vetting | **ARTIFACT** | — | phase-shuffle p=0.33, flat profile (contrast 1.011), outlier-driven (drop top-2% → 0.98) → artifact. |
| 2026-06-15 | astro | 152k astro strategy trials (all schools/segments) | **NO_EDGE** | — | Raw best Sharpe 1.85 → 0 survive Deflated-Sharpe (expected best-of-N noise = sqrt(2 ln N)/sqrt(T)). |
| 2026-06-15 | geomag | Geomagnetic storms (Krivelyova-Robotti) | **NO_EDGE** | — | -25bps post-storm (RIGHT sign!) but p≈0.10 under proper nulls and DECAYS OOS (-43→-8bps). |
| 2026-06-15 | astro | Hierarchical-Bayes partial pooling | **NO_EDGE** | — | jupiter-saturn pooled z=6.6 — but it's the cross-asset-CORRELATION-inflated pooling artifact (DL SE wrong). |
| 2026-06-15 | astro | Mutual information / transfer entropy | **NO_EDGE** | — | A few raw-significant (z up to 5.2) but 0 survive BH/Bonferroni across the grid. |
| 2026-06-15 | astro | Bradley / Gann / Merriman turn-dates | **NO_EDGE** | — | Merriman CRD +1.0pp hit-rate (97.6 vs 96.6%) p=0.001→Bonf 0.048: near-saturation, NOT economic. |
| 2026-06-15 | calendar | SAD / daylight seasonality | **NO_EDGE** | — | p≈0.10, FDR-fail (slopes look big in bps but not significant). |
| 2026-06-15 | astro | Spectral / Lomb-Scargle (returns + vol) | **NO_EDGE** | — | Slow planetary features correlate with vol — but a SYNTHETIC control scored equally → trend artifact. |
| 2026-06-15 | astro | Tail / extreme-event clustering | **NO_EDGE** | — | Clustering dies under the within-year permutation null (low-freq masks need the right null). |
| 2026-06-15 | real-signal | PIT honesty audit of the real signals | **INFRA** | ✅ | fear_greed/funding/vix/dxy/fed_funds = LIVE-TRADEABLE; LunarCrush social = backfilled+revised → LOOK-AHEAD trap. |

## The smart lessons (distilled across all experiments)

- **[astro]** Only calendar (turn-of-month/Halloween) is literature-durable; lunar weak; planets folklore.
- **[astro]** Adding a known-null feature block to a real model DILUTES it — incremental test is the cleanest question.
- **[astro]** train→OOS rank consistency is THE single most diagnostic check; inversion = noise.
- **[astro]** A fake-RANDOM-date null is TOO WEAK for autocorrelated vol — it manufactured these 3 'hits'.
- **[astro]** The proper null (phase-shuffle) KILLED what the weak null passed. Chase a candidate, then try HARD to break it.
- **[astro]** More search DEFLATES harder, never 'finds' the edge. Raw Sharpe alone is the false-positive machine.
- **[geomag]** The 'least dead' candidate: right sign + a real mechanism, but not significant + decays. Worth a forward watch, not capital.
- **[astro]** Pooling assumes independent studies; correlated crypto returns inflate the pooled z — spurious.
- **[astro]** Nonlinear estimators still need multiple-testing correction; raw z lies.
- **[astro]** A +1pp uplift on a 97% saturated base is statistically marginal and economically meaningless.
- **[calendar]** Big-looking annualized bps ≠ significant; FDR over latitude classes kills it.
- **[astro]** A planted synthetic slow control matching the 'signal' = it's trend, not astronomy.
- **[astro]** A circular-shift null on a low-frequency mask UNDER-estimates variance; use within-year.
- **[real-signal]** A predictor is usable only if knowable BEFORE the move AND identical live vs backtest. Backfilled+revising = mirage.

## The honest bottom line

Across every experiment, **0 tradeable edges** survived an honest gate (proper null + OOS + economic + deflation). The closest was the geomagnetic −25bps (right sign, but p≈0.10 + decays). The value produced is (a) a *definitive* falsification of astro across every dimension a top quant/physicist/astronomer would check, (b) the live-honest data + R2 infra, and (c) the reusable honesty pipeline + these lessons. The next lucrative move is NOT astro — it is the real-signal / funding / cross-sectional-momentum directions the gate already half-believes, ingested live-forward.

