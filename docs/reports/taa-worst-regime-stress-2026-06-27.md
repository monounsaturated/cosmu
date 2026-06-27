# Equity-TAA worst-regime stress — the fragility the Gate can't see (2026-06-27)

**Harness:** `apps/engine/cosmu/research/equity_taa_stress.py`
**Reproduce (real numbers, on the M2 / Modal where the equities cache lives):**
```
COSMU_EQUITY_CACHE=/path/to/equities \
  python3 -m cosmu.research.equity_taa_stress --mult 4 --k-bars 1 \
  --report docs/reports/taa-worst-regime-stress-2026-06-27.md
```
> **Gate constants are LOCKED.** This module imports no `GateSettings`, calls no `score()`/`promote_cohort`, and
> moves no money. It is a **portfolio-axis instrument that watches what the single-snapshot Gate structurally
> cannot** (cross-disciplinary playbook 2026-06-26 → "the killers are all downstream of the backtest"). It
> **informs**; it does not dispose.

---

## BLUF

The deterministic Gate funds on **average** edge — a deflated Sharpe over one realized net-return stream. Two of
the playbook's named failure modes hide *inside* that average and never trip a snapshot Sharpe:

- **Red-team #7 — worst-regime fragility.** A strategy can clear the 0.95 deflated-Sharpe bar on its full window
  yet be **net-negative in the high-volatility regime** — exactly where it must not be. The Gate sees the blended
  number; it does not report the **minimum** Sharpe across volatility regimes.
- **Red-team #10 — stress liquidity / forced exit (LTCM).** The backtest prices every rotation at **calm** slippage
  (~1 bp/side IBKR all-in) and calm-data correlations. Under a forced de-risk the slippage leg blows out **3–5×**
  into a **one-sided book** (the whole defensive-TAA cohort sells the same risk assets at the same time), and the
  "diversification" of three differently-triggered rotations **collapses toward one trade**.

This report ships the **instrument** that measures all three (worst-regime Sharpe, forced-exit re-pricing, stress
correlation), the **flags** it raises, and the **mechanism-grounded prediction** of where the current survivors are
exposed. The **empirical numbers are produced by the reproduce command above** — this cloud session cannot fetch
the equities cache (Yahoo `query1.finance.yahoo.com` is **policy-denied** by the network egress here, confirmed
403), so the harness is verified on deterministic CI fixtures (17 offline tests) and run for real on the M2/Modal.

---

## 1. Who is under test

The **only full-Gate survivors** are the equity-TAA cohort (`docs/reports/equity-taa-honest-gate-survivors.md`):

| tier | strategy | module | in-sample maxDD | mechanism (why it can crowd / whipsaw) |
|---|---|---|---|---|
| **STRICT-PASS** | DAA — Defensive Asset Allocation | `equity_daa.py` | **8.3%** | 13612W momentum top-6 + **progressive** EEM/AGG canary → bonds |
| **STRICT-PASS** | VAA-G4 — Vigilant Asset Allocation | `equity_vaa.py` | **21.5%** | **all-in/all-out** top-1 risk asset, hard canary switch to defensive |
| **STRICT-PASS** | ADM — Accelerating Dual Momentum | `equity_accel_dual_momentum.py` | **17.0%** | **accelerating** (1+3+6mo) dual momentum, binary equities↔bonds |
| DSR+HOLDOUT | PAA — Protective AA | `equity_paa.py` | 5.8% | multi-canary protective, SMA breadth → cash |
| DSR+HOLDOUT | GTAA — Faber 5-asset | `equity_faber_gtaa.py` | 5.2% | 10-mo SMA on/off per sleeve |
| DSR+HOLDOUT | Risk Parity (inverse-vol) | `equity_risk_parity.py` | 11.1% | inverse-vol SPY/AGG/GLD |
| DSR+HOLDOUT | TSMOM — Time-Series Momentum | `equity_tsmom_trend.py` | 6.8% | trailing-return trend on/off |
| DSR+HOLDOUT | HAA — Hybrid AA (Keller 2023) | `equity_haa.py` | 8.9% | single TIP canary, top-4 of 8 |

All eight are **funded combos** (each has a deploy-lane `*_arm.py`). All are **monthly, multi-asset, total-return,
net of real IBKR fees, PIT**. The harness re-uses their realized streams verbatim via `equity_taa_cohort.build_streams()` — **no new data, no refit.**

---

## 2. The instrument (three measurements)

### 2.1 Worst-regime net Sharpe (red-team #7)
- **Regime labels.** Each month is labelled by the **volatility regime it opened in**: the trailing `VOL_WINDOW=6`-
  month realized vol of the shared SPY benchmark (PIT — uses returns through *t-1* only), partitioned into
  **calm / normal / stress** terciles. The tercile *cuts* use the whole window — a retrospective *diagnostic*
  partition (this is attribution, not a tradeable signal), the standard regime-conditional construction.
- **Metric.** Annualized **net** Sharpe **within each regime** (same `mean/pstdev·√12` convention as
  `equity_holdout.metrics_with_holdout` / `scorer.sample_moments`), and the **minimum across regimes** — reported
  for the **full realized stream** and **separately for the embargoed holdout tail** (the window the strategy never
  saw). Regimes with `< MIN_REGIME_MONTHS=6` months are excluded from "worst" (noise).
- **Contrast surfaced:** `avg SR (what the Gate scores)` vs `WORST-regime SR`.

### 2.2 LTCM forced-exit re-pricing (red-team #10)
- **Realized cost recovery.** Each month's rebalance cost is recovered exactly as `cost_t = gross_t − net_t`
  (the calm slippage+fee the backtest already charged — every TAA module exposes both `gross_returns` and
  `net_returns`; the cohort `StratStreams` now carries `gross`, **read only here, never by the Gate**).
- **Forced re-pricing.** In **stress** months the cost is re-priced into a one-sided book:
  `extra_t = cost_t · (slip_mult − 1) · one_sided_penalty`, with `slip_mult ∈ {3,4,5}` (default 4) and
  `one_sided_penalty = 1.5`. The stress-regime Sharpe is recomputed under `net_t − extra_t`.
- **K-bar feasibility.** Given a book notional and a stress-haircut ADV,
  `bars_to_exit = ⌈notional / (participation_cap · ADV · stress_liquidity_haircut)⌉`; **feasible iff `≤ K`**
  (default `K=1` monthly bar). Without an ADV feed (this cloud env), `bars_to_exit` is `nan` and feasibility is
  `None` — **cannot measure ⇒ never falsely flagged**; the operator's run supplies real ETF ADV.

### 2.3 Stress-regime correlation (red-team #6 + #10)
- Pairwise survivor correlation computed **on stress months only** (index-aligned on the common calendar, then
  filtered), via `master.strategy_correlation.pairwise_correlation`, at the **crowding** threshold
  `CROWDING_RHO = 0.70` (not the 0.85 redundancy default). Reported as **calm avg ρ vs stress avg ρ**, with the
  crowded pairs listed. A stress cluster `≥ 0.70` is the **"one trade under stress"** failure mode.

### Output schema (the reproduce command fills the cells)

| strategy | n | avg SR (Gate sees) | **WORST-regime SR** | holdout WORST SR | stress SR → forced (4×) | bars-to-exit | flags |
|---|---:|---:|---|---|---|---:|---|
| DAA … | ‹run› | ‹run› | **‹run›** | ‹run› | ‹run›→‹run› | ‹run› | ‹run› |
| … one row per survivor … | | | | | | | |

Plus: `calm avg ρ` vs `stress avg ρ`, the crowded pairs, a verdict
(`ROBUST` / `WATCH` / `CROWDING-WARNING` / `FRAGILE-SURVIVORS`), and the flagged survivor list.

---

## 3. Mechanism-grounded findings (what the instrument will confirm)

These are **structural predictions from the published mechanics + the cohort's own drawdown profile** — the
harness measures them on the real data. They are *not* fabricated numbers.

1. **Stress correlation is the highest-conviction risk — `defensive5`'s "diversification" is a calm-data
   artefact.** ⚠️ DAA, VAA, ADM, PAA, GTAA, HAA **all** key off (a) 1–12-month momentum and (b) a canary/breadth
   signal that rotates to **Treasuries/cash** when equities roll over. In a stress flip they de-risk **the same
   direction at the same time** → stress-regime ρ → **~1** even though calm ρ is moderate. The ensemble report's
   `defensive5` maxDD of 4.9% is a **calm-blended** number; under stress the cluster is **one position**. Expect
   `stress avg ρ ≫ calm avg ρ` and a single crowded cluster ≥ 0.70 → **`CROWDED_UNDER_STRESS`** on the cohort.

2. **VAA-G4 and ADM are the most worst-regime-fragile; DAA the most robust.** ⚠️ VAA is **all-in/all-out** (holds
   the single strongest risk asset, then snaps fully defensive) — a **binary switch** that **whipsaws in
   high-vol chop**, consistent with its **21.5%** in-sample maxDD (≈ 2.6× DAA's). ADM's **accelerating** momentum
   reacts fast but is **whipsaw-prone** at vol spikes (17.0% maxDD). DAA's **progressive** `b/2` canary steps into
   bonds gradually (8.3% maxDD) — its worst-regime Sharpe should be the least negative. The likely
   **`WORST_REGIME_NEGATIVE`** candidates, in order, are **VAA → ADM**.

3. **Forced-exit risk is dominated by COST, not bars-to-exit — until capital scales.** ℹ️ On liquid ETFs
   (SPY/QQQ/EFA/EEM/GLD/AGG/TLT, ADV $100M–$10B+) at retail/SIM notional, the whole book clears in **well under one
   monthly bar**, so `bars_to_exit ≤ 1` (feasible). The binding constraint is the **extra slippage drag** in stress
   months, largest for the **highest-turnover switchers (VAA, then ADM)** whose canary flip is ~100–200% one-sided
   turnover. `STRESS_EXIT_INFEASIBLE_K_BARS` only fires once **book notional approaches `participation_cap ·
   stress-ADV`** — i.e. it is a **capacity ceiling at scale**, which the harness makes explicit by accepting
   `--`/`adv_usd_by_name` + `capital_by_name`.

4. **DSR+HOLDOUT siblings (PAA/GTAA/TSMOM) carry the lowest maxDD and likely the least worst-regime damage**, but
   they share the same de-risk trigger, so they **add to the crowding cluster** rather than diversifying it.

---

## 4. Flags & thresholds (harness parameters — NOT Gate constants)

| flag | fires when | default threshold |
|---|---|---|
| `WORST_REGIME_NEGATIVE` | min(full, holdout) worst-regime SR `< −materiality` | `WORST_REGIME_MATERIALITY = 0.25` |
| `WORST_REGIME_SUBZERO` | worst-regime SR negative but within the materiality band | — |
| `STRESS_EXIT_ERODES_EDGE` | forced-exit re-pricing drives the stress SR `< −materiality` | `slip_mult = 4`, `one_sided_penalty = 1.5` |
| `STRESS_EXIT_INFEASIBLE_K_BARS` | book not exitable within `K` bars at stress ADV | `K = 1`, `participation_cap = 0.10`, `stress_liquidity_haircut = 0.5` |
| `CROWDED_UNDER_STRESS` | in a stress cluster with pairwise ρ `≥` crowding threshold | `CROWDING_RHO = 0.70` |

Every threshold above is a **named, overridable harness dial** (CLI / `analyze_streams(...)`). **None is a Gate
threshold.** The Gate's locked pre-registered bar (`research/gate.py:PREREGISTERED_BAR`, unchanged) remains:
`min_deflated_sharpe_prob 0.95 · max_cscv_pbo 0.50 · min_regimes_positive 2 · max_drawdown 0.25 ·
must_beat_buy_and_hold · BH-FDR q 0.10 · min_trades 30`.

---

## 5. What a flag means (and does not mean)

- A flag is an **input to sizing and the launch decision**, not a re-Gate. The Gate already fired (discovery);
  this instrument tells the operator **where a funded survivor is fragile** so a launch can be (a) **regime-sized**
  (smaller in high-vol), (b) **de-crowded** (do not run the whole `defensive5` cluster at full size as if it were 5
  independent bets), and (c) **capacity-capped** (keep book notional below the stress-ADV ceiling).
- It is **measure-only**: it writes no disposition, changes no Gate constant, and moves no money — consistent with
  the playbook's directive to build the **time/portfolio-axis instruments** that watch what the Gate cannot.

---

## 6. Honesty notes

- **Empirical numbers are not in this document** because the equities cache is absent in this cloud session and the
  Yahoo egress is policy-denied (no synthetic survivor numbers are ever displayed — AGENTS.md hard rule). The
  reproduce command at the top regenerates this report's table with real cells on the M2/Modal.
- **The instrument math is verified offline** by 17 deterministic tests (`tests/test_equity_taa_stress.py`): PIT
  regime labelling, minimum-not-average worst-regime Sharpe, forced-exit re-pricing monotonicity, K-bar
  feasibility, and the stress-correlation spike — all without cache, network, or RNG.
- **No Gate threshold was touched.** The only change to a Gate-adjacent file is an additive, inert `gross` field on
  `StratStreams`, read solely by this harness; the cohort/Gate path scores `net` exactly as before (existing
  cohort/ensemble/robustness tests still pass).
