# Faster-than-monthly equity-TAA variants — through the LOCKED Gate (2026-06-29)

**Question.** The only Gate survivors are the equity-TAA cohort (DAA / GEM / Faber-GTAA / VAA / Risk-Parity / ADM)
— multi-asset rotation/momentum that rebalances **MONTHLY = slow**. The operator wants profit faster. Can a
**FASTER** multi-asset strategy — *similar in spirit* (cross-sectional sector momentum / dual-momentum / risk-parity
/ trend) but **weekly or daily**, shorter lookbacks, vol-targeted, faster trend — survive the **same locked Gate**,
or does the edge **require the monthly cadence**?

**Method.** A new harness `apps/engine/cosmu/research/equity_taa_faster_cohort.py` composes the **existing**
machinery used by `equity_taa_cohort.py` — `equity_holdout.metrics_with_holdout` (real purged+embargoed holdout) +
`master.cohort.promote_cohort` (DSR ≥ 0.95 vs the trial-inflated benchmark, BH-FDR q=0.10, CSCV-PBO, folds/drawdown
floors). **No Gate constant is touched.** Each variant is **one fixed, pre-registered config** (no per-variant
param search); two disconfirmers (Buy&Hold-SPY NULL, random-rotation PLACEBO) ride the same cohort so FDR/PBO see
them. Fees = REAL IBKR all-in, **taker/conservative 1 bps/side**, charged on realized one-sided turnover each
rebalance; a `{1,2,3,5}` bps sweep is reported per variant.

**Data (deep-fetched — no self-cap).** A faster rebalance needs **daily** total-return bars. The deepest daily-TR
coverage in the equities cache:

| sleeve | daily-TR source | history |
|---|---|---|
| 9 SPDR sectors (XLB/XLE/XLF/XLI/XLK/XLP/XLU/XLV/XLY) | `*_tr.json` (daily 1d bars, medgap 1.0d) | **1998-12 → 2026-06** (~27y) |
| SPY (regime + benchmark) | `SPY_tr_daily.json` | 2003-01 → 2026-06 |
| AGG (risk-off sleeve) | `AGG_tr_daily.json` | 2003-09 → 2026-06 |
| GLD (risk-parity third sleeve) | `GLD_tr_daily.json` | 2004-11 → 2026-06 |

So the natural deepest universe for a fast cross-sectional book is **the 9 sectors (rank/hold) + SPY (regime
filter + benchmark) + AGG (risk-off)**, and `{SPY, AGG, GLD}` for risk-parity. The weekly window binds on SPY
(2003-01) — **1215 weekly bars** / **~5800 daily bars** of true total-return history per variant. The full
available history is used (window binds on each variant's youngest required series), never a truncated last-N slice.

---

## The pre-registered slate (9 variants + 2 disconfirmers)

Lookbacks in panel periods — weekly: 13w≈3mo, 26w≈6mo, 40w≈200d-SMA, 20w≈100d-SMA, 12w≈60d-vol; daily: 120d≈6mo.

1. **wk_sector_mom_13w_top3_sma40** — weekly, top-3 sectors by 13w return, SPY>200d-SMA regime else AGG
2. **wk_sector_mom_26w_top3_sma40** — weekly, top-3 by 26w (≈ the monthly book's 6mo lookback), 200d-SMA regime
3. **wk_sector_dualmom_13w_top3** — weekly dual-momentum, top-3 by 13w, absolute-momentum → AGG (no SMA)
4. **wk_accel_dualmom_4_13_26_top3** — weekly accelerating dual-mom, score = mean of (4,13,26)w returns, abs-mom → AGG
5. **wk_risk_parity_12w** — weekly inverse-realized-vol {SPY, AGG, GLD}, 12w vol
6. **wk_voltgt10_sector_mom_13w_top3** — weekly top-3 sector mom scaled to **10% annual target vol**, AGG buffer
7. **wk_fast_trend_sma20_sector13_top3** — weekly, SPY>**100d-SMA** (fast trend) → top-3 sector mom (13w) else AGG
8. **dy_sector_dualmom_120d_top3** — **daily** dual-mom, top-3 by 120d, abs-mom → AGG
9. **dy_fast_trend_sma100_sector120_top3** — **daily**, SPY>100d-SMA → top-3 sector mom (120d) else AGG
- *disc:* Buy&Hold-SPY NULL (weekly) · Random weekly sector rotation (PLACEBO)

---

## Result — VERDICT: **NO-SURVIVOR**

`python -m cosmu.research.equity_taa_faster_cohort` (deterministic; net of 1 bps/side taker fees):

| variant | cad | reb/y | trn/y | n(IS) | annSR | DSR | hldDSR | PBO | fold+ | maxDD(IS) | IS_tot | SPY_IS | net_tot | flag |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| wk accel dual-mom top-3 (4,13,26w) | wk | 52 | 10.5 | 946 | 0.81 | **0.983** | +0.210 | 0.70 | 1.00 | **0.289** | +571% | +516% | +703% | fdr-only |
| wk risk-parity 12w | wk | 52 | 1.3 | 878 | 0.92 | **0.982** | +0.481 | 0.70 | 1.00 | 0.187 | +147% | +442% | +228% | fdr-only |
| wk vol-tgt 10% sector mom 13w | wk | 52 | 9.5 | 933 | 0.78 | **0.973** | +0.376 | 0.70 | 1.00 | 0.264 | +298% | +508% | +400% | fdr-only |
| wk sector mom 26w top-3 + 200dSMA | wk | 52 | 9.4 | 906 | 0.70 | **0.951** | +0.406 | 0.70 | 1.00 | 0.227 | +338% | +435% | +575% | fdr-only |
| *disc* Buy&Hold SPY (NULL) | wk | 52 | 0.0 | 976 | 0.68 | 0.950 | +0.465 | 0.70 | 0.80 | 0.546 | +595% | +595% | +1136% | fdr-only |
| wk fast-trend 100dSMA→sector 13w | wk | 52 | 12.3 | 942 | 0.69 | 0.949 | +0.325 | 0.70 | 1.00 | 0.217 | +319% | +534% | +410% | fdr-only |
| wk sector mom 13w top-3 + 200dSMA | wk | 52 | 11.3 | 906 | 0.64 | 0.923 | +0.420 | 0.70 | 1.00 | 0.169 | +267% | +435% | +493% | stop |
| *disc* Random rotation (PLACEBO) | wk | 52 | 51.2 | 965 | 0.62 | 0.921 | +0.077 | 0.70 | 0.80 | 0.629 | +603% | +581% | +592% | stop |
| wk sector dual-mom 13w top-3 | wk | 52 | 11.5 | 957 | 0.54 | 0.857 | +0.226 | 0.70 | 0.80 | 0.370 | +248% | +533% | +311% | stop |
| dy fast-trend 100dSMA→sector 120d | dy | 252 | 23.9 | 4515 | 0.87 | 0.838 | +0.351 | 0.70 | 1.00 | 0.190 | +537% | +524% | +729% | stop |
| dy sector dual-mom 120d top-3 | dy | 252 | 20.8 | 4567 | 0.60 | 0.446 | +0.380 | 0.70 | 1.00 | 0.368 | +324% | +515% | +509% | stop |

**No faster variant clears the full Gate, and none clears the brief's DSR+holdout bar either.** Fee sweeps `{1,2,3,5}`
bps barely move the annualized Sharpe (turnover is modest, 1–12×/yr for weekly), so the verdict is **not** a
knife-edge fee artifact — the binding constraints are **drawdown, the SPY-beta hurdle, and overfit (PBO)**, not fees.

### The decisive comparison — same machinery, only cadence differs

| | **Monthly cohort** (slow, the incumbent) | **Faster cohort** (weekly/daily) |
|---|---|---|
| Cohort CSCV-PBO | **0.043** (clean) | **0.700** (overfit-flagged) |
| STRICT survivors | DAA, VAA, ADM | **none** |
| DSR+holdout survivors | DAA, VAA, ADM, PAA, GTAA, **Risk-Parity**, HAA, TSMOM (8) | **none** |

Run through the **identical** Gate, with the **same disconfirmers** in the pool, on the **same asset family**: the
monthly strategies' edge is robust enough that the in-sample winner stays OOS-strong (**PBO 0.04**); the faster
variants' edge is weak enough that the in-sample winner is a **selection fluke** (**PBO 0.70**) — the overfit guard
fires exactly as designed. **The slow cadence is doing real work, not just being conservative.**

---

## What the Gate is actually saying (per-variant, PBO isolated)

The cohort-level CSCV-PBO (0.70) blocks every candidate, so to see each variant's *individual* merit I re-ran
`promote_cohort` carrying each candidate's own PBO (≈0, non-binding) — isolating DSR / holdout / drawdown /
beat-B&H. The nuance matters:

- **wk_accel_dualmom (weekly accelerating dual-momentum) is the standout** — **DSR 0.983**, **holdout +0.210**,
  folds 1.00, **survives FDR**, and is the **only** non-disconfirmer that **out-RETURNS** SPY in-sample (+571% vs
  +516%). It fails on **one** floor only: **max_drawdown = 28.9% > 25% cap**. A genuine, FDR-corrected,
  holdout-confirmed, SPY-beating weekly edge — killed by the drawdown limit, not by absence of edge.
- **wk_risk_parity_12w** — DSR 0.982, holdout **+0.481**, **maxDD 18.7% (well within cap)**, survives FDR. Fails
  **only** `buy_and_hold` (risk-parity is risk-adjusted; it never out-returns SPY in a bull — exactly like the
  monthly RP, which is itself a DSR+holdout survivor, not a STRICT one). At the cohort level its only extra failing
  reason is PBO.
- **wk_voltgt10** (DSR 0.973) and **wk_sector_mom_26w** (DSR 0.951) clear DSR and survive FDR; they fail
  buy_and_hold (± max_drawdown). The vol-target's realized vol is **10.4%** (target 10% — the vol-targeting *works*),
  yet it still draws down 26.4% because momentum **gaps through fast crashes** (COVID-2020, 2022) between weekly
  rebalances — barely breaching the 25% cap.
- **Daily variants are weakest.** Even where annualized Sharpe is high (daily fast-trend annSR 0.87), the
  **per-observation** Sharpe is tiny at daily cadence, so DSR (which deflates on per-obs SR × √trials) lands at
  0.84 / 0.45 — well below 0.95. Daily rebalancing also pays ~21–24× annual turnover. Faster ≠ better here.
- **Disconfirmers behave correctly.** Buy&Hold-SPY NULL fails `buy_and_hold` (by construction) + max_drawdown (54.6%
  raw SPY DD). Random rotation fails deflated_sharpe + FDR + has the **weakest holdout** (+0.077). The placebo never
  promotes — the cohort gate is sound. (Note the disconfirmers carry the **highest in-sample means** because raw SPY
  beta over 2003–2026 is a huge bull; that is precisely why CSCV keeps picking them as in-sample "winners" and they
  then land OOS-below-median, which is *what drives the cohort PBO to 0.70*. The real 7 weekly variants alone have
  PBO 0.29 — they only fail the cohort PBO because the trivial-beta benchmarks dominate in-sample selection, which
  is itself evidence the faster variants don't cleanly beat plain beta.)

---

## Honest verdict — does faster-TAA work?

**No faster-than-monthly multi-asset momentum/rotation variant survives the locked Gate on this universe. The edge
that the monthly cohort harvests does NOT cleanly survive being sped up to weekly or daily.** Three independent
reasons, all genuine (not fee-driven):

1. **Drawdown.** The faster momentum books are punchier — they gap through fast crashes between rebalances. The
   best weekly variant (accel dual-mom) breaches the 25% DD cap (28.9%) despite a real, SPY-beating, holdout-confirmed
   edge. Vol-targeting hits its 10% vol target but still draws 26.4% (crash gaps, not steady-state vol).
2. **The SPY-beta hurdle.** 2003–2026 is a historic equity bull; a weekly book that de-risks (risk-parity, trend,
   vol-target) is **risk-adjusted-superior but does not out-RETURN** raw SPY in-sample, so it fails
   `require_beat_buy_and_hold` — the same reason the monthly Risk-Parity / GTAA / TSMOM are DSR+holdout survivors
   rather than STRICT survivors.
3. **Overfit (PBO).** Across the same-cadence cohort the in-sample winner tends to land OOS-below-median (PBO 0.70
   vs the monthly 0.04). The monthly edge is robust to selection; the faster edge is not.

**The fastest cadence that comes closest is WEEKLY** — `wk_accel_dualmom` and `wk_risk_parity` each clear DSR ≥ 0.95
+ holdout > 0 and survive FDR, failing only a single additional floor (drawdown and buy-and-hold respectively).
**Daily is materially worse** (DSR collapses on per-obs Sharpe; turnover ~22×/yr). So the **edge degrades
monotonically with speed**: monthly (8 survivors, PBO 0.04) → weekly (0 survivors, but 2 books one-floor-away,
PBO 0.70) → daily (0 survivors, DSR far below bar). **The slow monthly cadence is load-bearing.**

### If the operator wants to push the weekly lane further (NOT a Gate change — new pre-registered configs)

The weekly accel-dual-mom edge is real (DSR 0.983, holdout +0.21, beats SPY) and dies *only* on drawdown. A
**risk-managed** weekly variant — explicit equity-exposure cap / faster de-risk to AGG when SPY breaks its trend, or
a lower vol target (e.g. 8%) — could plausibly bring the in-sample DD under 25% **without** loosening anything. That
is the one thread worth pulling. But on the configs tested here, **the honest answer is: faster-than-monthly TAA does
not survive — the multi-asset momentum edge requires (close to) the monthly cadence.**

---

*Harness:* `apps/engine/cosmu/research/equity_taa_faster_cohort.py` — propose/measure-only, moves no money, no
merge, zero LLM on the gate path, deterministic for fixed cached data. Reuses `equity_holdout` + `master.cohort`
unchanged; mirrors the `equity_taa_cohort.py` pattern. Existing `test_equity_taa_cohort.py` (3 tests) still passes.
