# Combo-axes research — what else could refine a combo? (2026-06-25)

**Question (operator):** today a "combo" is `strategy × symbol × venue` (the S×A×V triple, judged BRUT per cell).
What OTHER criteria/axes could we add to find BETTER combos?

**READ-ONLY research. No code changes. One report.**

---

## TL;DR — the headline the operator needs

There is exactly **one** axis that is a genuine edge-*finder* rather than an overfitting amplifier, and we
already shipped its template: the **exit envelope** (PR #378). The reason it is safe is the reason that decides
*every* candidate axis on this list:

> An axis adds value **only if** it (1) changes the *bet itself* — a structural/thesis distinction, not just
> another continuous knob to maximize over — **and** (2) flows through the existing per-combo machinery so each
> variant is judged BRUT on its OWN data (`promote_brut`, the locked DSR/PBO gate, the forward/paper gate),
> rather than re-pooled and funded best-of-M-raw.

The trap, in one line: **anything you can sweep and then keep the winner of is a multiple-testing amplifier.**
Picking the best of N exit-stops, N regimes, N entry-timings inflates the in-sample Sharpe by chance. The
just-run exit spike taught this; it survived the lesson only because it is **propose-only** — it fans distinct
*specs* into the same unchanged Gate (FarmLoop → BH-FDR / brut), it never selects a champion on raw in-sample PF.

### The crucial mechanical distinction (verified in code)

Two very different things both look like "an axis":

1. **A SPEC FIELD that fans into distinct, independently-gated specs.** Each variant is a *different hypothesis*
   that gets its OWN per-combo deflation. Adding more of these can only ever find MORE real edges — it cannot
   manufacture a false one, because no cross-variant selection happens. This is how **symbol** and **venue**
   already work (`cosmu/evolution/loop.py:947-949` says it explicitly: every extra symbol is one more
   independently-judged cell the gate absorbs, never a loosening), and how the **exit envelope** now works.

2. **A KNOB you optimize over inside one cell, then keep the best.** This rides the `trials=grid_size`
   param-grid deflation in `metrics_for_run` — which only protects you if the realized grid count is honestly
   fed. The moment a new axis is swept and the *best variant per cell* is promoted **without** its variant-count
   landing in `trials_counted` (or its correlated siblings haircut via `effective_trials`), the deflation is
   bypassed and you are funding noise. `cosmu/master/scorer.py::expected_max_sharpe` + `effective_trials` is the
   ONLY thing standing between us and best-of-N inflation; an axis that doesn't route through it is a trap by
   construction.

**Verdict key:** `ADD-AS-DEFLATED-AXIS` (information-adding AND it rides existing deflation) ·
`KEEP-AS-SPEC-FIELD` (belongs as a fanned spec variant, NOT a new optimizer dimension) ·
`TRAP-DONT` (pure knob / re-pools / funds best-of-M-raw).

---

## What axes already exist (so we don't reinvent them)

| Axis | Where | How it's deflated today |
|---|---|---|
| **Param variants** | `lab/finder.build_grid` (grid) / `evolution/loop` (mutation) | `trials=grid_size` baked into `trials_counted` → `expected_max_sharpe(N_eff)`. The legitimate own-overfit deflation. |
| **Symbol** | `_market` / `_crypto_cells` per-cell panel | BRUT: each cell judged alone, `TrialStats(count=1)`, NO pooling. More symbols = more independent cells. |
| **Venue** | venue-tagged `universe_pairs`, per-cell fee/depth overlay | BRUT per cell, real per-venue fees (`build_cost_context`). The fee axis of S×A×V. |
| **Direction** | `spec.direction` (+1/−1/0) | A spec field; long vs short is a different bet, gated independently. |
| **Timeframe / horizon** | `spec.horizon` (`1h`/`4h`/`1d`, min/max hold) | A spec field today (one value per spec), not a swept axis. |
| **Entry setup** | `spec.setup` (MA filter / ORB / FVG) | Spec field; ParamRefs fit inside the cell's grid. |
| **Exit envelope** | `spec.exit` + `lab/exit_sweep.fan_exit_envelope` (#378) | **Propose-only fan → distinct specs → unchanged Gate.** The template. |
| **Meta-label** | `spec.meta_label` (triple-barrier logistic) | Sizes/skips inside a cell; PIT, expanding-window; can only subtract trades. |
| **Funding leg** | `spec.funding_feature` | Spec field; PIT alt-join. |
| **Data / alt features** | `config/feature_registry.py` (~50 features, tier0/tier1) | Entry/exit conditions; tier1 down-weighted; "must earn its place OOS"; non-causal controls wired to be KILLED. |
| **Regime** | `ml/regime.py` `proven_regimes` | NOT a selection axis — a live-eligibility **passport** (may only trade live in a regime it was positive in). A blocking filter, not a tunable selector. |

The data axis (the social/LLM/niche lane the operator keeps asking about) is **already the largest axis we
have** and it already flows the right way: as PIT-joined features inside entry/exit conditions, gated per
combo, with the honesty discipline (tier1 down-weight, known-false controls). The bottleneck there is
**hypothesis quality + running the sweep**, not a missing axis.

---

## Candidate NEW axes — assessed

| Candidate axis | Information-adding vs knob? | Survives deflation? | Leverage | Verdict |
|---|---|---|---|---|
| **Exit envelope** (stop/scale-out/trail/ATR structure) | INFO — a different *risk shape* is a different bet (asymmetric trail ≠ fixed TP). | YES — #378 fans distinct specs through the unchanged Gate; propose-only. | HIGH (orthogonal to entry, barely explored) | **KEEP-AS-SPEC-FIELD (shipped #378)** |
| **Holding-period / horizon** | INFO at the *structural* level (a 1-day reversal ≠ a 30-day trend = different thesis). | YES **iff** fanned as discrete spec variants like the exit envelope; TRAP if swept continuously and best-kept. | MED-HIGH | **KEEP-AS-SPEC-FIELD** (fan a few discrete horizons; never a continuous optimize-and-keep) |
| **Bar-size / timeframe** (`1h`/`4h`/`1d`) | INFO — different sampling = genuinely different signal, not a reparam of one. | YES iff fanned as separate specs (each its own grid + its own bars + its own data window). | MED | **KEEP-AS-SPEC-FIELD** (3 discrete values, fan don't sweep) |
| **A NEW data source** (social / LLM-index / niche OSINT) | INFO — orthogonal information, the highest-ceiling lane. | YES — already routes through tier-weighting + per-combo gate + known-false controls. | HIGH (but diminishing: ~50 features already wired, mostly thin/un-edged) | **ADD-AS-DEFLATED-AXIS** (it already is one) — the constraint is hypotheses+depth, not plumbing |
| **Regime-conditioning** (only-trade-in-regime-X as a *selectable* filter) | KNOB — "pick the regime that backtested best" is textbook conditioning; the regime that fit best in-sample is the one most likely to be luck. | NO if selected; the `proven_regimes` passport already captures the honest version (block-only, never promotes). | LOW (net-negative if turned into a selector) | **TRAP-DONT** (keep the block-only passport; do NOT add a "best regime" selector) |
| **Entry-timing** (which bar/offset after the signal to fill) | KNOB — a pure micro-optimization over fill offset; classic best-of-N on in-sample noise. | NO — sweeping fill-offset and keeping the best is exactly the inflation `expected_max_sharpe` is meant to punish, and an offset sweep rarely lands in `trials_counted`. | LOW + leakage risk (touches the prior-bar/next-bar discipline) | **TRAP-DONT** |
| **Entry-density / liquidity-tier** | MIXED — as a *capacity/cost* property it's INFO (already in `universe_pairs` tiers + depth schedule); as a *selection* axis ("trade only the tier that backtested best") it's a KNOB. | Cost side already deflated via real depth/fees; selection side is not. | LOW-MED | **KEEP-AS-SPEC-FIELD** (a universe-membership / capacity guard, not a swept selector) |
| **Market-cap / sector bucket** | MIXED — a cross-sectional *grouping* can be a real structural cut (large vs small-cap momentum differ); but "fund the bucket that won in-sample" is conditioning. | NO if best-bucket-selected; YES only if each bucket is its own independently-gated universe (= just more symbols, which we already do brut). | LOW (subsumed by per-symbol brut + `xsec_momentum_rank`) | **TRAP-DONT** as a selector (redundant with per-symbol brut) |

---

## Top 3 (ranked by real, mission-aligned leverage — autonomous profit net of fees)

1. **A new orthogonal DATA source — the social / LLM-index / niche-OSINT lane.** This is the only axis that adds
   *genuinely new information* rather than reshaping price we already have, and it already flows through the
   correct deflation (per-combo gate, tier1 down-weight, known-false controls to falsify against). It is the
   highest ceiling and the most aligned with the edge thesis (weak signals + cheap social/frontier data that NY
   can't be bothered with). **Caveat that keeps it #1 and not a free lunch:** ~50 features are already wired and
   most are thin or un-edged — so the leverage is in *hypothesis quality and history depth*, not adding more
   half-empty feeds. Add depth and a sharp prior, not breadth for its own sake.

2. **The exit envelope (already shipped, #378) — keep mining it, it's the correct template.** "Fix one validated
   entry, fan the exit structure" is the clean win: orthogonal to the entry, barely explored before #378,
   propose-only, and it cannot inflate because each exit variant is a distinct spec the unchanged Gate disposes.
   This is the *shape* every future axis should copy. Highest *near-term* leverage because the machinery is live
   and the space is fresh.

3. **Discrete bar-size / horizon fanning (as spec variants, never a sweep).** A 4h-reversal and a daily-trend
   are different theses on the same pair; fanning 2-3 discrete timeframes per validated entry — exactly like the
   exit fan — searches a real structural dimension cheaply and honestly. Strictly `KEEP-AS-SPEC-FIELD`: each
   timeframe gets its own bars, its own grid, its own per-combo deflation. The instant it becomes a continuous
   "optimize the bar-size" knob it flips into a trap.

---

## The honest "these are traps" list (do NOT add as a selectable/optimized axis)

- **Regime-conditioning as a selector** ("trade only in the regime that backtested best"). The best-fitting
  in-sample regime is the most likely to be luck; selecting it is conditioning. We already have the *honest*
  version — `proven_regimes` blocks live trading outside a proven regime but never promotes anything. Leave it
  block-only. Adding a "pick the best regime" selector is net-negative.

- **Entry-timing / fill-offset sweep.** Pure micro-optimization over in-sample noise, the canonical best-of-N
  amplifier, and it doesn't land in `trials_counted`. It also risks the prior-bar-signal / next-bar-fill
  leakage discipline. Don't.

- **Market-cap / sector "best-bucket" selection.** Funding the cross-sectional bucket that won in-sample is
  conditioning; the legitimate version (each bucket judged independently) is just *more symbols*, which the brut
  per-cell model already handles. `xsec_momentum_rank` already captures the cross-sectional structure honestly.

- **Liquidity-tier as a selector.** Tiers are a real capacity/cost property (already priced via depth + fees);
  "trade only the tier that backtested best" is a knob. Keep it as a universe/capacity guard.

- **General rule for future axes:** if you can imagine writing "keep the variant with the best in-sample
  Sharpe" for the axis, it is a TRAP unless that variant's count flows into `trials_counted` / `effective_trials`
  OR each variant is a distinct, independently-gated spec. Otherwise you are funding the maximum of a noise
  distribution. The exit envelope passes this test; a fill-offset sweep does not.

---

## Mission tie-in

The north star is autonomous profit **net of fees**, found by testing wide and honestly. The axes that serve it
are the ones that widen the *space of distinct bets* the unchanged Gate can falsify — new data, exit structure,
discrete horizons — because the brut/FDR machinery turns "wider" into "more real edges found," never "more
false positives funded." The axes that *appear* to serve it but actually erode it are the optimizable knobs
(regime/timing/bucket selection): they trade a locked, honest gate for an in-sample maximum, which is precisely
the #1 blow-up risk (a leakage/over-selection bug upstream of the Gate). Add information, never knobs.
