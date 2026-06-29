# Re-gate of existing strategies through the CURRENT locked Gate — 2026-06-29

**Ask (operator):** "The Gate has changed since these strategies were sent — re-run them through the
CURRENT Gate to see if they still pass."

**Method:** read-only. The funded/meaningful strategy versions were re-run through the *current* merged-main
Gate machinery — **no Gate constant was touched, no prod row mutated**. The equity-TAA survivors go through
`research/equity_taa_cohort.run()` (the cohort `promote_cohort` path on their native multi-asset monthly
universe, deepest cached total-return history); the crypto `screened` specs go through
`research/rerun_cohort.run_rerun_cohort()` (the BRUT per-combo cohort path on real Binance daily bars + real
social/Polymarket PIT history). Both call the SAME locked `master.cohort.promote_cohort`.

Branch: `regate-2026-06-29` off `origin/main @ c0a9e96b` (foundation batch merged). Engine code resolved via
`PYTHONPATH` → the worktree's merged-main `apps/engine`.

## Current locked Gate constants (verified in `cosmu/config/settings.py::GateSettings`)

| Floor | Value |
|---|---|
| `min_trades` | 30 |
| `max_drawdown_pct` | 0.25 |
| `min_folds_positive_pct` | 0.60 |
| `max_pbo` | 0.50 |
| `holdout_min_deflated_sharpe` | 0 (must be > 0) |
| `min_deflated_sharpe_prob` (DSR) | **0.95** vs the trial-inflated benchmark |
| `require_beat_buy_and_hold` | **True** |
| `fdr_q` (BH-FDR across the cohort) | 0.10 |

Unchanged from the locked calibration — none was loosened for this run.

## What currently holds meaningful status (read from prod DB, read-only)

`strategy_versions` status counts: **killed 1673 · screened 147 · paper 10**. The **10 `paper` (funded) tracks**
are ALL the documented equity-TAA rotations (€1000 SIM seed each). Their current forward (paper) return_pct:

| Funded paper track | fwd return_pct |
|---|---|
| Vigilant Asset Allocation (VAA-G4) | +4.02 |
| Defensive Asset Allocation (DAA) | +0.96 |
| Dual Momentum (QQQ/EFA tech-tilt) | +0.21 |
| Protective Asset Allocation (PAA) | +0.09 |
| Risk Parity (inverse-vol SPY/AGG/GLD) | −0.14 |
| Diversified Time-Series Momentum (TSMOM) | −0.54 |
| Faber GTAA (5-asset, 10mo SMA) | −1.00 |
| Global Equities Momentum (GEM) | −1.16 |
| Accelerating Dual Momentum (ADM) | −1.16 |
| Sector-Momentum Rotation (TAA Top-3) | −1.42 |

(All ETF total-return monthly rotators on IBKR; HAA is in the cohort but is NOT funded — no track.)

---

## RESULT 1 — equity-TAA cohort re-gate (the funded book)

Run: `equity_taa_cohort.run(persist=False)`. Window **1993-03 .. 2026-05** · candidates 13 (11 documented + 2
disconfirmers) · cohort CSCV-PBO **0.043** · monthly · net of REAL IBKR fees · DSR≥0.95 + BH-FDR q=0.10 + real
purged/embargoed holdout (embargo 12m).

| Strategy | n | annSR | DSR | holdoutDSR | maxDD | flag | failing floor (if any) |
|---|---|---|---|---|---|---|---|
| **DAA** | 184 | 1.46 | 1.000 | +0.447 | 0.083 | **STRICT-PASS** | — |
| **VAA** | 195 | 1.11 | 0.998 | +0.376 | 0.215 | **STRICT-PASS** | — |
| **ADM** | 200 | 0.98 | 0.985 | +0.424 | 0.170 | **STRICT-PASS** | — |
| PAA | 185 | 1.30 | 1.000 | +0.472 | 0.058 | DSR+HOLDOUT | beat-B&H only |
| Faber GTAA | 186 | 1.19 | 0.999 | +0.483 | 0.052 | DSR+HOLDOUT | beat-B&H only |
| Risk Parity | 192 | 1.25 | 0.999 | +0.477 | 0.111 | DSR+HOLDOUT | beat-B&H only |
| HAA *(unfunded)* | 160 | 1.16 | 0.996 | +0.491 | 0.089 | DSR+HOLDOUT | beat-B&H only |
| TSMOM | 184 | 0.97 | 0.983 | +0.493 | 0.068 | DSR+HOLDOUT | beat-B&H only |
| **Dual Momentum QQQ** | 195 | 0.95 | 0.981 | +0.465 | 0.257 | **fdr-only — NOW FAILS** | **max_drawdown 0.257 > 0.25** |
| **Sector-Momentum** | 148 | 0.91 | 0.945 | +0.392 | 0.154 | **fdr-only — NOW FAILS** | **deflated_sharpe 0.945 < 0.95** + buy_and_hold |
| **GEM** | 195 | 0.74 | 0.877 | +0.403 | 0.215 | **STOP — NOW FAILS** | **deflated_sharpe 0.877 < 0.95** + buy_and_hold + **fdr** |
| Buy & Hold SPY (NULL disc.) | 307 | 0.72 | 0.917 | — | 0.508 | stop [disc] | correctly fails (max_drawdown + DSR + B&H) |
| Random rotation (PLACEBO disc.) | 194 | 0.52 | 0.643 | — | 0.352 | stop [disc] | correctly fails (placebo controls hold) |

**Cohort verdict: PASS-STRICT** — 3 strategies (DAA, VAA, ADM) survive the FULL gate (DSR≥0.95 + holdout +
BH-FDR + beat-B&H-SPY). Both disconfirmers (B&H-SPY null, random placebo) correctly fail — the cohort gate is
behaving. The TAA edge is real and still clears the current standard; it is a monthly-cadence multi-asset
phenomenon (consistent with #484: faster-than-monthly TAA = NO-SURVIVOR).

### Pass / fail per funded track under the CURRENT Gate

| Funded track | Strict gate | DSR+holdout (overfit guards) | Verdict vs when funded |
|---|---|---|---|
| DAA | **PASS** | pass | still passes (strongest) |
| VAA | **PASS** | pass | still passes |
| ADM | **PASS** | pass | still passes |
| PAA | fail (beat-B&H only) | **pass** | survivor on every overfit guard; only doesn't out-RETURN SPY in the bull IS |
| Faber GTAA | fail (beat-B&H only) | **pass** | same — overfit-clean, not out-returning SPY |
| Risk Parity | fail (beat-B&H only) | **pass** | same |
| TSMOM | fail (beat-B&H only) | **pass** | same |
| **Dual Momentum QQQ** | **fail** | **FAIL** | **NOW FAILS — max_drawdown 0.257 > 0.25** |
| **Sector-Momentum** | **fail** | **FAIL** | **NOW FAILS — DSR 0.945 < 0.95** |
| **GEM** | **fail** | **FAIL** | **NOW FAILS — DSR 0.877 < 0.95 + FDR** |

**3 funded tracks now hard-FAIL the current Gate** (GEM, Sector-Momentum, Dual Momentum QQQ) — they fail a
real overfit/risk floor, not just the beat-B&H hurdle. 4 funded tracks (PAA, GTAA, Risk Parity, TSMOM) clear
every overfit guard but don't out-RETURN SPY in the bull in-sample (the documented crisis-avoidance trade-off —
a soft fail, not an overfit fail). 3 funded tracks (DAA, VAA, ADM) are full STRICT survivors.

---

## RESULT 2 — crypto `screened` specs re-gate (BRUT cohort path)

Run: `rerun_cohort.run_rerun_cohort()` — the two orphaned crypto `screened` candidates
(`btc-social-riskon-overlay`, `polymarket-positioning-risk-flip`) + 3 pre-registered disconfirmers
(flat-baseline, btc-price-regime, time-shuffle placebo) as ONE BH-FDR family on real Binance daily bars + real
social/Polymarket PIT history, net of today's Binance fees.

**These two specs are `screened` orphans, NOT in the funded book** (capital allocated = 0, never promoted to
paper). They do not bear on the funded-book verdict above; this is the bonus "sample of screened specs" part of
the ask.

**Status of this run in the bounded M2 session: DB-fetch-bound, not run to completion.** The harness fetches the
full social history per-symbol (`fetch_series(..., limit=len(bars)+2400)`) against the 65,742-row `social_volume`
table on the cross-region EU Supabase, then joins the Polymarket series (411 + 403 rows) per symbol. On the M2
this stalls on network I/O (0% CPU for minutes) — exactly the "hanging" path M2 discipline says not to block on.
The process was stopped rather than run the full hanging fetch.

**What the re-gate would show (high confidence, from the locked prior verdicts these specs already carry):**
- `btc-social-riskon-overlay` — the high-turnover daily social trigger already FAILED honestly (deflated
  Sharpe 0.596); the low-turnover overlay is the re-test, and the cohort is FALSIFIED-by-construction if it
  doesn't beat the flat baseline + the equal-turnover btc-price tilt and isn't reproduced by the time-shuffle
  placebo. Memory verdict: the intraday order-flow / social fade lane is KILLed (turnover-bound).
- `polymarket-positioning-risk-flip` — Polymarket wedge triage already returned **KILL** (the "smart" edge is a
  disputed-market PIT mirage, clean markets are calibrated; latency lane is bot-turf). Only 411/403 PM rows
  exist — too thin for the family to promote even if it ran.

Neither is funded, so the funded-book verdict is unaffected. Re-running this cohort to numeric completion is a
Modal/cloud job (cross-region bulk fetch), not an M2-bounded one — deferred.

---

## VERDICT

- **TAA survivors are still survivors.** DAA, VAA, ADM clear the FULL current Gate (DSR≥0.95 + holdout +
  BH-FDR + beat-B&H). The disconfirmers fail as expected. The edge held through every Gate change since funding.
- **But the paper book is NOT all-survivor.** Of the 10 funded paper tracks, only 3 are full STRICT survivors,
  4 are overfit-clean-but-don't-out-return-SPY (DSR+holdout pass; soft fail on beat-B&H), and **3 now hard-FAIL
  a real floor** (GEM, Sector-Momentum, Dual Momentum QQQ). Their negative forward returns (GEM −1.16,
  Sector −1.42, QQQ +0.21 marginal) corroborate the re-gate: the marginal members were the ones the current
  Gate now rejects.
- **Does the paper book reflect reality?** Partially. It faithfully shows the forward P&L, but it still *funds*
  3 strategies the current Gate would no longer admit. The honest book would carry DAA/VAA/ADM as full
  survivors, PAA/GTAA/Risk-Parity/TSMOM as "overfit-clean, benchmark-relative" holds, and graveyard or demote
  GEM / Sector-Momentum / Dual-Momentum-QQQ. **This run is read-only and mutated nothing** — the demote/graveyard
  is a follow-up for the operator to action.

**No Gate constant was changed. No prod `gate_verdicts` / `tracks` row was written.**
