# Negative-Control Empirical-Null Placebo Panel (2026-06-27)

> Playbook bridge **#1** (from pharmaco-epidemiology / GWAS — Schuemie/OHDSI), implemented. Turns the #1
> *unmeasurable* fear — leakage UPSTREAM of the Gate, which the Gate structurally cannot see — into a
> continuously-monitored instrument. **This VALIDATES the Gate; it loosens nothing** (the locked constants are
> read, never written).

## BLUF
- Built a **standing, re-runnable harness** (`cosmu/research/placebo_panel.py`) that runs **10 placebo specs**
  (5 time-shuffled real signals + 5 random-entry matched-turnover) through the **EXACT** finder→Gate per-combo
  BRUT path: `run_strategy_backtest_detailed` → `metrics_for_run` → `promote_brut` (the **locked**
  DSR/PBO/min-trades/folds/beat-B&H gate, `TrialStats(count=1)`). The **only** thing that differs from a real
  finder cell is the **signal content** (placebo); the gate, the fees, the slippage are byte-identical.
- **DID ANY PLACEBO CLEAR THE GATE? — NO.** 0 of 50 cells cleared on the primary panel, and **0 across 12
  independent seed×regime configs** (incl. regimes where the placebo DSR null reaches ~0.9999). The null is
  calibrated; the Gate is leak-free on these tapes.
- **Headline finding (a real monitorable result, not just a green check):** placebos routinely produce
  **DSR ≥ 0.95** — the gate's own DSR floor — *by chance*. On the primary panel **4 cells hit DSR 0.96–0.97 with
  PBO 0.02 and 35–44 trades**, and were caught **only by the beat-buy-and-hold leg**. **The DSR floor alone is
  NOT a sufficient per-cell leak guard — the gate's conjunction (PBO ∧ folds ∧ beat-B&H ∧ DSR) is load-bearing.**
  If `require_beat_buy_and_hold` were ever relaxed/dropped, those placebos would clear. The panel now *watches*
  exactly that.

## What it is
A real survivor is credible only if it sits in the **right tail of an EMPIRICALLY MEASURED null**. We measure
that null with placebos run through the same machinery. The two families (the playbook's exact prescription):

| Family | Construction | Why it's a negative control |
|---|---|---|
| **time_shuffled** (5) | a REAL leading signal (lagged momentum z-score) with its values **permuted in time** | marginal preserved, alignment destroyed → its IC **collapses** (verified) → an honest gate must reject |
| **random_entry** (5) | a **pure uniform-noise** entry signal, threshold = `1 − target_turnover` | trades enough (turnover 0.2–0.6) to be Gate-eligible and tempt the gate by chance, yet carries no edge |

The placebo signal is injected through the **same `alt_by_symbol` PIT join** the finder feeds funding/sentiment
through (carried under a registered feature so the spec compiles). Keyless + deterministic + offline — runs on
the repo's `permutation_null_market` (each symbol's returns also permuted, so there is **no edge anywhere**,
neither in the bars nor the signal — the strictest control; the only way a placebo could clear is a leak).

## Measured null (primary panel: corr=0, n=600, market-seed=11, placebo-seed=7)
```
PLACEBO NULL PANEL — CLEAN  (10 placebo specs, 50 cells, gate floor DSR>0.95)
  measured null DSR: mean=0.2027  p50=0.0087  p95=0.9666  MAX=0.9744
  measured null PBO: mean=0.4177  p50=0.5540  min=0.0200
  gate DSR floor 0.95 sits at the 92.0th percentile of the placebo null (headroom over null MAX = -0.0244)
  -> no placebo cleared the Gate: the null is calibrated, the Gate is leak-free here.
```
Rejection reasons across the 50 cells (a cell can fail multiple legs):
`deflated_sharpe×46 · folds_positive×40 · pbo×27 · buy_and_hold×10 · min_trades×2`.

The 4 cells that reached the DSR floor yet were rejected:

| family | symbol | DSR | PBO | trades | rejected by |
|---|---|---|---|---|---|
| random_entry | BTCUSDT | 0.9744 | 0.020 | 35 | **buy_and_hold** |
| random_entry | BTCUSDT | 0.9710 | 0.020 | 44 | **buy_and_hold** |
| random_entry | BTCUSDT | 0.9666 | 0.020 | 41 | **buy_and_hold** |
| random_entry | BTCUSDT | 0.9607 | 0.020 | 39 | **buy_and_hold** |

## Robustness (0 cleared across regimes × seeds)
Independent (`corr=0`) and correlated (`corr=1`) null markets, market-seeds {11,29,101}, placebo-seeds {7,23}:
every config → `any_cleared = False`. The placebo DSR null `p95`/`MAX` ranges from ~0.46 up to **0.9999**
depending on the tape — i.e. placebos frequently manufacture a near-perfect DSR by chance — and the **full**
locked gate still rejects every one.

## Survivor vs the null (worked example)
A DAA/VAA-class survivor with DSR≈0.97 against the primary null:
```
SURVIVOR vs PLACEBO NULL — RIGHT-TAIL (credible vs the empirical null)
  survivor DSR=0.9700  (null p95=0.9666, null MAX=0.9744)
  survivor sits at the 96.0th percentile of the placebo null, empirical p=0.0588  (beats null MAX: False)
```
Read: a 0.97 survivor clears the placebo p95 and the gate floor (right-tail), but its empirical p≈0.06 against
this particular null shows the **per-cell** DSR margin over a chance placebo is *thin* — the gate's other legs,
not DSR alone, are what separate it from a placebo. (Real DAA/VAA survivors are pooled multi-asset cohorts with
much larger margins; this single-cell offline comparison is the conservative read.)

## How to run it
```
python -m cosmu.research.placebo_panel --n 600 --seed 7 --demo-survivor 0.97
```
Exits non-zero iff a placebo cleared the Gate, so a CI/cron rider **fails loudly** on a caught leak. The real
cohort-rider passes the **same real bars the finder screened** (so the null is measured on the same tape the
survivors were found on) instead of the offline fixture.

## Interpretation
- **The Gate is leak-free on these tapes**, and the null is calibrated: the 0.95 DSR floor sits at the ~92nd
  percentile of the per-cell placebo DSR null, with the rest of the gate carrying the tail.
- **Actionable, monitorable:** the panel measures that **DSR-alone is not a sufficient per-cell leak guard** —
  `require_beat_buy_and_hold` (and PBO/folds) are doing real work. Any future change that touches the gate's
  conjunction should re-run this; a placebo clearing is a caught leak.
- **Next (out of scope here):** ride the panel on **every cohort** with the real screened bars + persist the
  measured null alongside the cohort verdict (a `placebo_null` payload), so each survivor's DSR is reported with
  its empirical-null percentile, not just the absolute 0.95.

## Files
- `apps/engine/cosmu/research/placebo_panel.py` — the harness (authoring · injection · panel run · survivor
  comparison · CLI).
- `apps/engine/tests/test_placebo_panel.py` — 13 tests (deterministic authoring · IC-collapse property · panel
  measures a real null · **no placebo clears the gate** + across regimes/seeds · survivor-vs-null math).
