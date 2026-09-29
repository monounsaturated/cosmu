# Gate Design Audit — is it smart, dynamic, and evidence-accumulating *without* blocking exploration?

**Date:** 2026-06-26
**Scope:** READ-ONLY design audit. No engine code changed. The question is NOT "is the
Gate strict enough" — it is: **is the Gate SMART, DYNAMIC, and EVIDENCE-ACCUMULATING, and does
it avoid blocking creative exploration?**

**Operator framing (the lens this audit uses):**
- The Gate must **never block a creative exploration** from being backtested or paper-traded.
  Soon there will be MANY explorations; the system must stay **lenient for exploration**.
- The **FUNDING bar's statistical core stays LOCKED** — DSR `0.95` / BH-FDR `q=0.10` / PBO `0.50`
  / `min_trades` / holdout floor. These prevent self-deception and are NOT up for loosening.
- The opportunity is everything *around* that locked core: **routing, evidence accumulation, and
  non-disqualifying criteria** that INFORM without blocking.

**Verdict in one line:** The architecture is already much closer to the operator's goal than the
prompt assumed — it is a **two-(really three-)lane design that NEVER blocks exploration from
backtest/paper, only from FUNDING**, and it already carries two genuinely *dynamic* mechanisms
(regime-eligibility live gate + correlation-to-book exposure cap). The real gap is **not
over-blocking** — it is **under-surfacing**: a lot of per-cell evidence is computed and then
thrown away instead of persisted/displayed. The recommendations below are almost entirely
*additive evidence*, plus one routing widening. **Nothing here loosens the funding bar.**

---

## 1. Where a strategy can be BLOCKED vs merely FLAGGED

The single most important finding: **a creative strategy is never blocked from compute or from
paper observation — only from real capital.** The flow has three lanes, and "the Gate" people
worry about is only the third.

| Stage | What happens | Can a creative strategy be BLOCKED here? |
|---|---|---|
| **Author** (`lab/research.py`, `lab/author.py`) | LLM (or deterministic template) proposes N specs. A `novelty_gate` exists on the author path. | The novelty gate is the **only place upstream of compute that can drop a candidate** — it refuses near-duplicate *re-authoring*, not creativity. Worth keeping an eye on (see §5). |
| **Backtest / screen** (`data/backtest.py`) | EVERY authored spec is backtested over real bars — validation slice + purged/embargoed holdout, per-symbol runs, regime-tagged trades. | **NO.** Backtesting is unconditional. Killed candidates are still fully scored and land in the graveyard *with reasons*. |
| **Score** (`master/scorer.py::score`) | Deterministic verdict: `min_trades`, `max_drawdown`, `folds_positive`, `pbo`, `deflated_sharpe ≥ 0.95`, `holdout`, `beat-buy-and-hold`. | This produces a **verdict, not a wall.** A failing verdict does not delete the strategy or its evidence — it routes it. |
| **FDR cohort** (`master/cohort.py::promote_cohort`) | Benjamini-Hochberg across distinct candidates → `promoted` flag. | Same: produces a flag. |
| **Rejects-watch** (`master/rejects_lane.py`) | Gate-rejected-but-CLOSE candidates (DSR band `[0.80, 0.95)` **or** a strong OOS holdout) get a **zero-capital paper track** on the SAME SIM path survivors use. | This is a *catch*, not a block — it pulls rejected candidates back into forward observation. |
| **Fund** (`orchestrator/fund_tracks_from_survivors`) | A gate-passed survivor gets a **standalone paper track with real seed capital** (`sim_track_capital`, default $1000). | **This is the only real gate.** Failing it means "no capital," never "no existence / no evidence." |
| **Arm live** (`master/execution.py`) | Human clicks launch; live interlock checks forward evidence + caps + **regime eligibility**. | Manual + dynamic; not part of the exploration question. |

**Conclusion for §1:** Confirmed — **the funding bar is the ONLY hard block, and it blocks capital,
not exploration.** A creative strategy below the bar is: (a) fully backtested, (b) scored with
reasons, (c) graveyarded *with its evidence intact*, and (d) if it is a near-miss, **paper-tracked
at zero capital** so it keeps accumulating forward evidence. The design already honors "never block
exploration."

The one nuance: a candidate that lands **below the `0.80` rejects-watch floor** is killed and gets
**no forward paper track at all** — its evidence stops at the backtest. That is the only place the
"accumulate evidence on everything" goal is not met (see §4, addition E).

---

## 2. Evidence that is COMPUTED but NOT surfaced

This is the audit's headline. The backtest computes a rich per-cell evidence bundle; the persistence
layer keeps a thin slice of it. `backtest_symbols` (the per-cell table that feeds the front) has only:

```
return_pct, sharpe, max_drawdown, trades, verdict, equity_curve_json, oos_window_days
```

Everything below is **computed in `data/backtest.py` / `master/scorer.py` and then dropped** before
it reaches a queryable row or the UI:

| Evidence (computed) | Where computed | Surfaced today? | Why it matters for "evidence per strategy" |
|---|---|---|---|
| **Per-regime PnL** (`regime_returns`: bull/bear/chop) | `backtest.py:364`, `:422` | Used internally (survival rank, live gate), **not stored per cell, not displayed** | The single richest "where does this edge live" signal. A strategy positive in 1 regime vs 3 is a totally different bet. |
| **Holdout deflated Sharpe** (purged+embargoed OOS) | `backtest.py:341` | Only a pass/fail bit; the **number** isn't shown | The most honest single number — "did it hold up out of sample." |
| **Beat-buy-&-hold delta** (oos_return − B&H) | `scorer.py:272` | Only a pass/fail reason | "How much edge over just HODLing" is a headline number, shown as a boolean. |
| **cost_ratio** (net/gross after fees) | `scorer.BacktestMetrics` | Routing/fragility only | "How much of the edge survives fees" — fragility-to-cost, never displayed per cell. |
| **profit_factor / recovery_factor / sortino** | `scorer.py`, `risk_metrics.py` | Partially in some routers | Drawdown- and tail-aware quality the Sharpe is blind to. |
| **rank_consistency** (IS→OOS Spearman) | `scorer.py:204` | Advisory, computed in grid path only | "Does the in-sample ranking transfer out of sample" — the single most diagnostic overfit check, per its own docstring. |
| **PBO + folds_positive_pct** | `scorer.py` | Pass/fail only | The actual overfit numbers behind the verdict. |
| **Per-symbol breakdown** (`per_symbol`, `per_symbol_runs`) | `backtest.py:117–128` | Partially (leaderboard/strat sheet) | Per-(strat × symbol × venue) is the project's core value; the full run streams exist but most diagnostics off them aren't shown. |
| **Crowding / correlation-to-book** | `master/crowding.py`, `strategy_correlation.py` | Used to cap exposure, **not shown as a strategy attribute** | "How redundant is this vs what I already run" — exists as a sizing factor, never as a displayed evidence column. |

**Conclusion for §2:** The engine is **evidence-RICH internally and evidence-POOR on the surface.**
The biggest, cheapest win available is **persisting and displaying what is already computed** — most
of all the **per-regime PnL** and the **holdout DSR / B&H-delta numbers** (today reduced to booleans).
This is pure additive plumbing: it never touches a gate threshold.

---

## 3. Is it DYNAMIC (regime-aware / context-adaptive) or static?

**More dynamic than the prompt assumed — in two real, wired places — but the core verdict math is
(correctly) static.**

**Dynamic mechanisms that already exist and are wired:**

1. **Regime-eligibility live gate** (`master/execution.py:204–229`). Before a *live* order routes,
   the engine reads the strategy's `proven_regimes` (regimes where it made positive backtest PnL),
   computes the **current** market regime from reference bars, and **blocks the live order if the
   current regime is not one the strategy proved in** (`regime_eligible`). It **fails closed** on a
   regime-check error. This is genuine context-adaptation: the same strategy is allowed or blocked
   *depending on live market state*.

2. **Correlation-to-book exposure cap** (`master/crowding.py` → `orchestrator/loop.py:232`). Each
   funding cycle, funded+candidate cells are clustered by realized-return correlation; within a
   redundancy cluster the best representative keeps full exposure and the rest are **vol-scaled down
   to ~1/cluster_size of capital** — re-derived every cycle, and **restored to 1.0 when the
   correlation decays**. Crucially it **caps CAPITAL, never paper participation**: every member keeps
   trading and proving itself. This is exactly the "dynamic, non-disqualifying" behavior the operator
   wants — and it already ships.

3. **Survival ranking** (`ml/survival.py`) ORDERS the validation queue using `regime_spread`,
   folds, PBO, etc. — it changes *the order compute is spent in*, and **never vetoes** (docstring is
   explicit). A soft, learned prioritizer that cannot block.

**What is static (and should stay static):** the verdict math itself — DSR/PSR, CSCV-PBO, BH-FDR,
the gate thresholds. This is correct: a *funding* bar that drifts with regime would be exactly the
self-deception the locked core exists to prevent. **Do not make the funding thresholds regime-adaptive.**

**Where MORE dynamism would help (without touching the bar):** the dynamism today is concentrated at
the **live** and **capital-allocation** stages. It is **absent at the evidence/routing stage** — e.g.
the rejects-watch band is a fixed `[0.80, 0.95)` constant rather than, say, a band that adapts to the
measured Type-II rate the lane itself reports. That's an enhancement, not a defect.

---

## 4. Non-disqualifying criteria to ADD (critères non-rédhibitoires — INFORM, never block)

These are the operator's explicit ask. All are **additive evidence columns or advisory scores** —
none gates funding, none blocks exploration. Ordered by leverage.

**A. Per-regime PnL as a first-class, displayed evidence column** *(highest leverage, lowest cost)*
Persist `regime_returns` onto `backtest_symbols` (one JSON column) and show a bull/bear/chop
breakdown + a `regime_spread` badge per cell. The number already exists; it's discarded at persist
time. This single addition does more for "maximum evidence per strategy" than anything else.

**B. Surface the holdout DSR and beat-B&H delta as NUMBERS, not booleans**
Today a strategy "failed buy_and_hold" or "passed holdout" is a reason string. Store and show the
actual `holdout_deflated_sharpe` and `oos_return − buy_and_hold` so a near-miss reads "holdout DSR
0.41, +3.2% over HODL" instead of a red X. This reframes the Gate from a bouncer into an evidence sheet.

**C. Correlation-to-existing-book as a displayed strategy attribute**
The crowding detector already computes pairwise correlation to the live book; expose it per strategy
as "redundancy: 0.82 vs your QQQ-momentum cell" — an **informational novelty/crowding score**, not a
block. (The capital cap that USES it already exists; this just shows the number to the human.)

**D. Capacity / liquidity headroom estimate**
`cost_ratio` and venue depth (`Venue.cost_inputs`) already exist; combine them into a displayed
"capacity headroom" / "edge-survives-to-$X" attribute. Pure information — how big can this get before
fees/impact eat it — never a gate.

**E. Data-provenance / source-health badge per strategy**
For alt-data strategies, surface the freshness/coverage/PIT-lag of the sources the spec depends on
(the `profile-source` machinery already computes these). A strategy leaning on a stale or thin feed
should *say so* on its evidence sheet — informational, not disqualifying.

**F. (Routing, not a column) Widen forward observation below the rejects-watch floor**
Today a candidate below DSR `0.80` is killed with no forward track. Given "never block exploration +
accumulate maximum evidence," consider **opening a zero-capital paper track for a wider band** (or all
individually-clean, profitable, non-risk-floor rejects) so even weak-but-creative ideas keep accruing
forward evidence. This **costs only sim compute, moves zero money**, and directly serves the goal.
It widens *observation*, not the funding bar. (This is the one item that is routing rather than a column.)

**G. A standardized disconfirmer record per strategy**
Memory notes a "standardized disconfirmer harness" as staged but not in the production gate path. A
creative-exploration engine benefits from each strategy carrying its **own falsification test result**
(lead-lag symmetry, shuffle/permutation null, regime-rotation null) as displayed evidence. Advisory —
it informs trust, never blocks. This is the highest-rigor addition and the most work; flag for a
dedicated build, not a quick column.

---

## 5. Anything to REMOVE (a structural limit that needlessly blocks exploration)?

Very little — the design is already permissive. Two items to *review*, not necessarily delete:

1. **The author-path `novelty_gate` is the only pre-compute drop.** It refuses near-duplicate
   re-authoring. That is healthy (it stops the LLM re-proposing the same spec), but it is also the
   single chokepoint that *can* stop a creative idea from ever being backtested if it reads as a
   near-duplicate. **Recommendation:** don't remove it, but make it **log what it dropped and why**
   (so a creative idea wrongly judged "duplicate" is visible), and consider letting a borderline
   novelty case through to compute anyway (compute is the operator's stated cheap/abundant resource).

2. **The hard `0.80` rejects-watch floor** (`rejects_lane.identify_rejects`, `band_min`). This is not
   a *funding* limit, but it IS the line below which a candidate gets **no forward evidence**. Per the
   "accumulate maximum evidence" directive, this floor is the main thing standing between the current
   design and "observe everything clean." See §4-F — widen rather than remove.

**Do NOT remove or loosen:** DSR `0.95`, BH-FDR `q=0.10`, PBO `0.50`, `min_trades`, the holdout floor,
the risk-floor reasons (`max_drawdown` / `min_trades` / `holdout`) that correctly mark TRUE negatives.
These are the locked core and they are calibrated correctly.

---

## 6. Final verdict — is it "laxist-for-exploration + evidence-rich," and is it "pushed to the max"?

**Is it lenient-for-exploration? — YES, by design and already.** Three lanes ensure a creative
strategy is always backtested, always scored-with-reasons, and (if a near-miss) always paper-tracked
at zero capital. The only hard block is **capital**, gated by a locked statistical core that is
correctly strict. The system already separates "validate the edge" (locked) from "never block
exploration" (open) — exactly the distinction in the operator's framing.

**Is it dynamic? — PARTIALLY, in the right places.** Genuine context-adaptation exists at the **live**
stage (regime-eligibility gate) and the **capital-allocation** stage (correlation-to-book exposure
cap, re-derived every cycle). The verdict math is static — **correctly**, because a drifting funding
bar would reintroduce self-deception. The missing dynamism is at the *evidence/routing* layer
(e.g. a Type-II-adaptive rejects band), which is an enhancement, not a flaw.

**Is it evidence-rich? — INTERNALLY yes, ON THE SURFACE no.** This is the real finding. The backtest
computes per-regime PnL, holdout DSR, B&H-delta, cost_ratio, rank_consistency, per-symbol streams, and
crowding correlation — and then **persists a thin slice** (`return / sharpe / maxDD / trades /
verdict / equity_curve`). The evidence exists; it's discarded before it reaches a row or a screen.

**Is it "pushed to the max"? — NOT YET, but the gap is the OPPOSITE of over-blocking.** It is
**under-surfacing**. The Gate does not need to become more lenient (it already never blocks
exploration); it needs to become **more transparent and more accumulative** — keep and show what it
already knows, and widen *observation* (not funding) below the current near-miss floor.

**The three moves, in priority order:**
1. **Persist + display the computed-but-dropped evidence** — per-regime PnL first (addition A), then
   holdout DSR / B&H-delta as numbers (B). Cheap, pure plumbing, biggest evidence gain.
2. **Add the non-disqualifying informational columns** — correlation-to-book (C), capacity headroom
   (D), source-health (E). All advisory, none gating.
3. **Widen forward observation, not the funding bar** — open zero-capital paper tracks for a wider
   band of clean rejects (F), and make the author novelty-gate log its drops (§5). Routing, zero money.

The funding core stays exactly where it is. Everything recommended here makes the system *smarter and
more informative* without making it *more lenient about spending money* — which is precisely the
operator's distinction between "loosen the funding bar" (NO) and "never block exploration + accumulate
more evidence" (YES).

---

## Appendix — key files cited

- `apps/engine/cosmu/master/scorer.py` — the locked verdict math (DSR/PSR, CSCV-PBO, `score()`),
  plus computed-but-advisory `rank_consistency`, `cost_ratio`, `profit_factor`, `recovery_factor`.
- `apps/engine/cosmu/master/cohort.py` — `promote_cohort` (FDR family) and `promote_brut` (per-cell
  BRUT, no FDR/family); both produce *verdicts*, not deletions.
- `apps/engine/cosmu/master/rejects_lane.py` — the zero-capital observe lane; band `[0.80, 0.95)`,
  risk-floor reasons, OOS-strong PATH 2, empirical Type-II report.
- `apps/engine/cosmu/data/backtest.py` — where `regime_returns`, `holdout_deflated_sharpe`,
  `buy_and_hold`, per-symbol runs are computed (and then mostly dropped at persist).
- `apps/engine/cosmu/knowledge/schema.sql` — `backtest_symbols` columns (the thin persisted slice).
- `apps/engine/cosmu/master/execution.py` — the DYNAMIC regime-eligibility live gate.
- `apps/engine/cosmu/master/crowding.py` + `orchestrator/loop.py` — the DYNAMIC correlation-to-book
  exposure cap (caps capital, never paper participation).
- `apps/engine/cosmu/ml/survival.py` — the soft survival ranker (orders, never vetoes).
- `apps/engine/cosmu/knowledge/lifecycle_status.py` — SCREENED → PAPER → LIVE / KILLED vocabulary.
- `apps/engine/cosmu/config/settings.py` — `GateSettings` (the locked constants).
- `apps/engine/cosmu/master/scheduler.py` — the autonomous tick orchestration (author → gate →
  fund survivors → rejects Type-II readout).
