# Independent Replication Cohort (R3) + Sequential paper-test design (2026-06-27)

> Builds the cross-disciplinary playbook's **bridge #5** ("independent cross-asset/venue replication cohort —
> replication is the final arbiter, not FDR") and the meta-lesson **"validation lives on data the discovery never
> touched"** (`docs/reports/cross-disciplinary-playbook-2026-06-26.md`). Two deliverables:
> 1. **BUILT** — an `R3` replication-cohort step + the equity-TAA (Faber GTAA) adapter (`cosmu/research/replication_cohort.py`, tests `tests/test_replication_cohort.py`).
> 2. **DESIGN ONLY** — elevate the paper/forward lane from a 30-day time-WAIT to a formal **anytime-valid sequential test** (§3). No code in the live/money path was touched.

## BLUF
- The discovery Gate (R1: deflated-Sharpe ≥ 0.95 + real holdout + BH-FDR q=0.10) controls overfitting **within the
  discovery data**, but it cannot catch a survivor that is a **single-CELL fluke** — an edge that exists only on the
  exact symbols/venue it was mined on. The BRUT per-combo Gate passes that survivor.
- **R3 replication-cohort** takes a survivor's **FROZEN** spec (params_hash, **NO refit**), re-runs it on **3–5
  HELD-OUT symbols/venues it was NOT discovered on**, and requires a **replication quorum (≥ 2 of N replicate
  net-of-fees)** before the survivor is deemed **credible**. No replication ⇒ single-cell overfit.
- It is an **ADDITIONAL credibility gate**, never a loosening: every R1 constant (`GateSettings`,
  `research/gate.py:PREREGISTERED_BAR`) is **UNCHANGED**. R3 can only *demote a credibility claim*, never promote
  past R1, and it **registers no trials** (replication is confirmation on independent data, not a fresh search, so
  it adds no multiple-testing inflation — exactly why GWAS uses replication, not a wider FDR, as the final arbiter).

---

## 1. The staged R-lane (R1 → R2 → R3)

A credibility ladder — each rung a **different axis of robustness**. R3 is the new rung this PR adds.

| Stage | What it proves | Axis | Where (code) |
|------|----------------|------|--------------|
| **R1 — Discovery Gate** | DSR ≥ 0.95 vs the trial-inflated benchmark + a real purged/embargoed holdout + BH-FDR across the cohort | **Time** axis on the *discovery universe* | `master/cohort.py:promote_cohort`, `master/scorer.py:score` (constants LOCKED in `config/settings.py:GateSettings` + `research/gate.py:PREREGISTERED_BAR`) |
| **R2 — Parameter robustness** | the edge survives a param-NEIGHBOURHOOD sweep (fee / start-date / breadth) | **Parameter** space | `research/equity_taa_robustness.py` |
| **R3 — Independent replication** *(NEW)* | the FROZEN edge **travels** to held-out symbols/venues the discovery never touched | **Data** space — the GWAS final arbiter | `research/replication_cohort.py` |

The survivor enters R3 already **frozen**: `master/promotion.py:freeze_promotion` snapshots its fitted params +
`params_hash` into `strategy_promotions`. R3 re-runs *those* params, never a re-derivation.

---

## 2. The R3 build (`cosmu/research/replication_cohort.py`)

### 2.1 The general step
- `FrozenSurvivor(id, label, params, discovery_universe, replay, venue)` — a Gate survivor carried by its frozen
  numeric params (what `params_hash` pins) + a `replay(symbol) -> CellRun | None` callable that runs the **frozen
  rule with no refit** on one held-out symbol, net-of-fees.
- `run_replication_cohort(survivor, held_out_symbols, *, quorum=2, expected_params_hash=None) -> ReplicationReport`:
  1. **NO-REFIT enforcement.** Computes `params_hash(survivor.params)`. If `expected_params_hash` is supplied (e.g.
     read off the `strategy_promotions` freeze record) and differs, returns **verdict `DRIFT`** and judges nothing —
     a mismatch means the spec was re-fit, **fail-closed**.
  2. **Held-out disjointness.** Any held-out symbol that overlaps the discovery universe is dropped (it is not held
     out) and noted.
  3. **Per-cell replay**, net-of-fees, one held-out symbol at a time. A symbol with no data is an honest skip.
  4. **Quorum verdict.** `REPLICATED` iff `n_replicated ≥ quorum`; `NOT-REPLICATED` if below; `INSUFFICIENT-DATA`
     if fewer than `quorum` cells even ran (cannot judge).

### 2.2 The locked per-cell predicate (`cell_replicates`)
A held-out cell **replicates net-of-fees** iff **all** of:
- `n_obs ≥ MIN_CELL_OBS` (36 monthly obs — below this a single cell's risk-adjusted stat is too noisy to vote), **and**
- `net_return > 0` (the frozen rule makes money after fees on a symbol it never saw), **and**
- it beats buy-and-hold of that symbol on **either** a risk-adjusted (Sharpe) basis **or** a materially-lower
  drawdown (`net_maxDD ≤ 0.75 × B&H_maxDD`).

The Sharpe-OR-drawdown bar is **not invented** — it is the **same deployment bar `equity_faber_gtaa.validate()`
already uses** (`MATERIAL_DD_REDUCTION = 0.75`). A trend-timer's documented edge in a strong bull is drawdown
reduction, not out-Sharpe-ing buy-and-hold, so requiring an outright Sharpe beat would be the wrong test.

### 2.3 The equity-TAA adapter (the survivor we run it on)
Faber GTAA's per-sleeve rule **is** a single-asset absolute-momentum timing rule: *hold the asset when its month-end
close is above its trailing 10-month SMA, else sit in cash (SHY)*. The whole portfolio is 5 equal-weight copies of
that rule. So the frozen rule on **one held-out ETF the strategy was never screened on is a genuine held-out
replication cohort** — exactly the GWAS test.

`faber_gtaa_survivor()` reuses `equity_faber_gtaa`'s **own** frozen primitives (`_sma_signal`, `_realized_return`,
`_add_months`, `SMA_MONTHS=10`, `IBKR_ETF_BPS_PER_SIDE=1.0`, `CASH="SHY"`) — there is **no re-implementation and no
refit**; the rule is byte-identical to discovery, only the symbol changes.
- **Discovery universe (not eligible):** `SPY, EFA, AGG, GLD, IEF, SHY` (Faber's canonical sleeves + cash proxy).
- **Default held-out (disjoint):** `QQQ, IWM, EEM, TLT, DBC` — all in `equity_total_return_backfill.TAA_SYMBOLS`,
  so their `*_tr.json` total-return data exists for the real run.
- **Frozen params_hash:** `7f5abd994340d2ace25cba5716ccb68e1c338f0cd600d188bd9901a03d275042` (pinned in the test).

### 2.4 Operationalizing the lane
- **CLI:** `python -m cosmu.research.replication_cohort [--held …] [--quorum N] [--no-persist]`.
- **Durable record:** `persist_replication_verdict` writes **one `gate_verdicts` row** (payload `kind="replication"`,
  `method="independent_replication_cohort"`) + a `replication_cohort_run` event — **no schema change**. The row's
  `decision` column carries the R3 verdict string (`REPLICATED` / `NOT-REPLICATED` / …), which can **never collide
  with the funding `PASS`**, so an R3 record can never masquerade as a money-moving gate pass. Best-effort +
  offline-safe (a persist failure never raises into the research path).
- **Modal:** runnable as `modal run apps/engine/remote/app.py --job run_module --module cosmu.research.replication_cohort`.

### 2.5 Running it on the equity-TAA survivor

**Real-data run — belongs on the M2/Modal, not a cloud agent.** Materializing the equities total-return cache is a
**data-network** task (keyless Yahoo v8), and the network policy on the web/cloud execution environment **blocks**
that fetch (confirmed: `query1.finance.yahoo.com` → `403` by policy; same for stooq). Per `AGENTS.md`, equity-data
fetch is a local/Railway task. So the real numbers are produced where the cache lives:

```bash
# on the M2 (or Modal), where COSMU_EQUITY_CACHE is materialized:
python -m cosmu.research.equity_total_return_backfill --taa     # writes SPY/QQQ/IWM/EEM/TLT/DBC/… *_tr.json
python -m cosmu.research.replication_cohort                     # R3 on Faber GTAA, held-out QQQ/IWM/EEM/TLT/DBC
```

When the cache is absent (as in this cloud session) the CLI degrades to **`INSUFFICIENT-DATA`** with an honest note
pointing at the backfill command — it **never fabricates a number** (the no-synthetic-in-prod rule).

**CI fixture demonstration (synthetic — proves the wiring, NOT a market result).** The harness was exercised
end-to-end on deterministic synthetic monthly series (a 40-up / 8-crash / 36-recover "crash" series where a
trend-timer sits out the crash, and a choppy series where it whipsaws). This is a **CI fixture, not real ETF data**
— shown only to demonstrate the machinery; it is never displayed in the app or run in prod:

```
INDEPENDENT REPLICATION COHORT (R3) — a Gate survivor's FROZEN spec re-run on HELD-OUT symbols (no refit)
  survivor=Faber GTAA 10m-SMA timing (frozen)  venue=equity  params_hash=7f5abd994340d2ac
  discovery universe (NOT eligible): ['AGG', 'EFA', 'GLD', 'IEF', 'SHY', 'SPY']
  held-out: ['QQQ', 'IWM', 'EEM', 'TLT', 'DBC']  quorum: >= 2 of 5 net-of-fees
  symbol      n   net_tot  netSR  netDD  B&H_SR  B&H_DD       beat  replicated
  QQQ        75   +209.0%   3.52  10.0%    0.67   57.0%  Sharpe/DD  YES
  IWM        75   +209.0%   3.52  10.0%    0.67   57.0%  Sharpe/DD  YES
  EEM        80    -66.6%  -1.70  66.7%   -0.33   39.4%          -  no
  TLT        75   +209.0%   3.52  10.0%    0.67   57.0%  Sharpe/DD  YES
  DBC        80    -66.6%  -1.70  66.7%   -0.33   39.4%          -  no
  VERDICT: REPLICATED  (credible=True) — 3/5 held-out cells replicated net-of-fees (>= quorum 2)
```

> **Honest expectation for the REAL run.** This synthetic demo replicates because the fixtures are built to. On real
> ETFs, an absolute-momentum trend rule's edge is *drawdown protection*: it should replicate (lower maxDD than B&H)
> on held-out symbols that experience trends + crashes (e.g. QQQ, IWM, TLT), and may legitimately *fail* to replicate
> on a structurally-choppy held-out symbol — which is the point: R3 reports the honest split, not a pass.

---

## 3. DESIGN ONLY — elevate the paper/forward lane to a formal sequential test

> **Status: design, not built.** No change was made to `live_eligibility.py`, `settings.py`, or any money/interlock
> path in this PR. This section specifies the test so it can be reviewed and built behind operator sign-off.

### 3.1 What we are elevating
The forward/paper lane **is** COSMU's "validation on data the discovery never touched" (playbook meta-lesson #1).
Today its live-readiness signal is a **30-calendar-day WAIT** plus a **fixed-n** significance floor:
- `config/settings.py:19` — `PAPER_MIN_DAYS = 30` (advisory; surfaced, not enforced).
- `master/live_eligibility.py:forward_significance` — `forward_dsr = PSR(daily Sharpe vs 0) − 0.5` must clear
  `PAPER_MIN_FORWARD_DSR = 0.15` over `≥ PAPER_MIN_FORWARD_OBS = 12` daily obs (`settings.py:39,44`).

**The flaw to fix:** that significance floor is a **fixed-n test re-checked every day** as obs accrue. Re-peeking a
fixed-n test inflates its true false-arm rate (optional-stopping / multiple-looks). A genuine edge also has to wait
out an arbitrary 30-day clock even after the evidence is already decisive.

### 3.2 The data surface (already exists)
`master/live_eligibility.py:forward_daily_returns(store, version_id, symbol=, venue_id=) -> list[float]` — the cell's
forward marked returns **resampled to ONE non-overlapping net-of-fee return per UTC calendar day** (de-duplicated by
day, so marking frequency cannot inflate N). This is exactly a sequential test's input: one observation at a time.

### 3.3 The test — an anytime-valid e-process (test martingale)
Let `r_1, r_2, …` be the daily net-of-fee returns. Pre-register (the blinding discipline, playbook bridge #3 — fixed
**before** the track's first forward mark, so the test can't be tuned to the track):
- **H0:** forward edge `μ ≤ 0` (net-of-fee daily drift is not positive).
- **H1:** `μ ≥ μ1`, where `μ1` is a **minimal detectable effect** — the smallest daily edge worth arming for (e.g.
  the daily mean implied by an annualized Sharpe ≈ 1, or a fixed bps/day). Pre-registered, not fit.
- **α** — the anytime false-arm rate (default 0.05).

Build a **nonnegative test (super)martingale** `E_t` (an *e-process*) with `E[E_t | H0] ≤ 1`. By **Ville's
inequality**, `P_{H0}(∃ t : E_t ≥ 1/α) ≤ α` — i.e. the test is **valid at every peek**, no matter the stopping time.
Two standard, robust constructions (pick one at build time):
- **(a) Mixture SPRT / time-uniform confidence sequence for the mean** (Howard–Ramdas–McAuliffe–Sekhon 2021): a
  one-sided t-like martingale mixed over the alternative mean, yielding a running **lower confidence bound `L_t`** on
  the daily edge. Equivalent stopping rule: **confirm when `L_t > 0`** (the anytime-valid CI excludes zero).
- **(b) Hedged / empirical-Bernstein capital process** (Waudby-Smith–Ramdas 2023): a betting wealth process that
  grows iff the mean is positive — heavy-tail-robust, well-suited to fat-tailed daily returns.

### 3.4 Stopping rule
At each new daily observation:
- **Confirm (forward-ready):** `E_t ≥ 1/α` (equivalently `L_t > 0`). Anytime-valid — peeking daily is *built in*, not
  a violation. A strong edge confirms **early** (often well under 30 days); a marginal edge takes **longer** — adaptive.
- **Abandon (park the forward track):** a symmetric futility boundary (an α-level e-process for "edge `< μ1`"), **or**
  a pre-registered **max horizon** (e.g. 90 calendar days) after which an unconfirmed track is parked, not armed.
- **Continue:** otherwise, accrue another day.

### 3.5 Assumptions & robustness
- Use the **non-overlapping daily** series `forward_daily_returns` already returns (no overlap-inflated N).
- Daily marks can be weakly autocorrelated (a held basket re-marked daily). Prefer the heavy-tail-robust hedged
  construction (b); if autocorrelation is material, calibrate the e-process threshold with a **block bootstrap**.
  State the assumption explicitly with the verdict.

### 3.6 How it slots in — ADDITIONAL, never a loosening
- The advisory **`PAPER_MIN_DAYS = 30` SURFACE stays** (operator-facing recommendation, unchanged).
- A new `forward_sequential_verdict(store, version_id, …) -> {confirmed, abandoned, e_value, lower_ci, n_obs}` would
  **augment/replace** the fixed-n `forward_significance` floor for **auto-arm** eligibility. `forward_ready` becomes:
  *regime-eligible AND sequential-**confirmed** AND ≥ min obs*. The **human override and the regime gate are
  unchanged**; the **5 interlocks remain the only hard money gate**.
- It lives **OUTSIDE** `GateSettings` / the deterministic scorer / FDR / money path — the **same isolation
  `PAPER_MIN_DAYS` already has** (`settings.py:37–38`). It **never** touches R1's locked constants.

### 3.7 Why this is the right elevation
An anytime-valid e-process controls type-I at `α` for **any** stopping time (fixing the daily-peek flaw), **stops
early** for a real edge (faster to live than a blind 30-day wait), and **waits longer** for a coin-flip (fewer
false arms). It is the GWAS sequential-replication discipline applied to COSMU's **time axis** — the natural partner
to R3's **symbol/venue axis**.

---

## 4. Invariants honored
- **Gate constants LOCKED.** `GateSettings` (DSR 0.95, FDR q 0.10, min_trades 30, …) and `PREREGISTERED_BAR` are
  byte-unchanged. R3 is purely additive; the sequential test is design-only.
- **No money path touched.** R3 moves no money, registers no trials, and persists an R3-only verdict that cannot be
  read as a funding pass. The sequential-test design changes no live code.
- **No synthetic in prod.** The CLI degrades to `INSUFFICIENT-DATA` with a real-data reproduce command when the
  equities cache is absent; the fixture demonstration above is labeled CI-only.
- **No schema change.** R3 reuses the existing `gate_verdicts` table + the existing `events` log.

## 5. Reproduce
```bash
# tests (offline, deterministic)
PYTHONPATH=apps/engine python -m pytest apps/engine/tests/test_replication_cohort.py -q
# real run (M2/Modal — needs the equities total-return cache)
python -m cosmu.research.equity_total_return_backfill --taa
python -m cosmu.research.replication_cohort
```
