# Cosmu v2 — Build Brief

> **Status (2026-06-01):** Phases 0, 1, and **1.5 (single-asset aggregation gate) are BUILT and green on the fixture** — the honest wall, the LLM universal adapter (`ingest/standardize.py`), and the three-arm ablation (`research/gate.py` `evaluate_ablation`: price-only vs +alt vs buy-and-hold). See `IMPLEMENTATION.md`. **Reference only — do not rebuild.**
>
> **The active build unit is Phase 1.6 below — build it in one pass.** It proves the *second* half of the differentiator: *does combining asset classes beat any single one?* — the cross-asset/decorrelation edge most likely to pay at small size. It builds directly on the proven 1.5 harness, stays on **free data ($0)**, and keeps **execution deferred** (PLAN §2 two-plane split). Read `docs/PLAN.md` §0–§2 + Phase 1.6 for the why; this brief is the what + the acceptance bar.

---

## ACTIVE UNIT — Phase 1.6: The cross-asset extension

### Mission (one paragraph)
Extend the **proven 1.5 ablation** from one asset class to three, to answer the question the product's ambition rests on: **does combining asset classes beat any single one?** Add free **equity** (daily bars + FRED macro) and **prediction-market odds** (Polymarket public API) behind the existing seams; add **cross-asset features** (one market's price as another's feature); add a **fourth arm** to the ablation — (1) single-asset price-only · (2) single-asset+alt *(both built)* · **(3) cross-asset+alt (new)** · (4) buy-and-hold — with per-source *and* per-asset-class drop-one so the owner learns *which assets and which data* pay. This is the **data/signal plane only — execution stays one-venue/simulated and paid vendors are deferred** (PLAN §2). No UI, no Nautilus, no vectorbt, no Supabase, no live, **no paid vendors** — one pass. If cross-asset+alt doesn't beat the baselines, that is a valuable result: keep it single-asset and cut the classes that didn't pay, don't cut the project.

### Cold-start reading (in order, do not load whole files)
1. `AGENTS.md` — invariants + decision tables.
2. `docs/PLAN.md` §0–§2 (LLM at ingest-time not hot path; §2 **two-plane split** + multi-asset) + **Phase 1.6** in §4.
3. `docs/IMPLEMENTATION.md` — what is real vs stubbed (the wall + the 1.5 single-asset ablation are real and green).
4. The intent-spec headers of `data/altdata.py`, `research/gate.py`, `ingest/standardize.py` — you are *extending* these, not rewriting.

### Hard invariants (carry over — do not weaken)
- **Build on the proven 1.5 harness.** Reuse `evaluate_ablation`, the alt-data seam, the LLM adapter, the trial ledger, the scorer. This is an *extension* — adding asset classes + a fourth arm, not a new gate.
- **LLM only at ingest-time, frozen.** Validated (`instructor`/Pydantic) → **versioned + content-hash-cached** → deterministic code runs it forever. **Zero LLM calls in the backtest/scoring/decision paths.** The whole gate runs **fully offline via fixtures** (CI has no keys).
- **The scorer and money stay deterministic and out of any LLM path.**
- **Data plane only — execution stays deferred** (PLAN §2): paper/backtest fills are simulated; **no IBKR/Polymarket execution adapter, no paid data vendor** in this pass.
- **No magic numbers** (thresholds from a fitted `param_space`); **no hardcoded "edge"** (unsupported features → no trades).
- **Point-in-time integrity** everywhere (availability time, not event time); causal transforms only.
- **Determinism:** seeded, reproducible for a fixed data + fixture cache.
- **Every source/asset class declares a prior hypothesis.** More data/assets = more overfitting surface — anything that can't say why it carries swing-horizon edge does not get built.
- Verify with `python3 -m pytest apps/engine/tests`; keep all existing tests green.

### Scope — build ALL of this in one pass

**A. Two new free asset classes behind the existing seams — `apps/engine/cosmu/data/altdata.py` + `apps/engine/cosmu/data/market.py`**
Mirror the existing provider/`FixtureAltDataProvider` pattern (append-only, availability-stamped, latest snapshot ≤ *t*, causal transforms). Add offline fixtures for each so the gate runs with no key.
1. **Equities** — free **daily bars** (e.g. Stooq/Yahoo-free) + **FRED macro** (free API). *Known limit: free equity bars are **survivorship-biased** (no delisted names) — declare it; this gate tests signal **presence**, not deployable capacity. Norgate replaces it at the execution/live phase.*
2. **Prediction markets** — **Polymarket public CLOB odds** (free, no wallet). Odds-as-features only; no execution.

**B. Cross-asset features — extend `apps/engine/cosmu/config/feature_registry.py`**
- 2–3 cross-asset features, each with a one-line **prior** + `transform_version`: e.g. **prediction-market odds → crypto/equity risk-on/off tag**, **crypto funding → cross-asset risk-appetite**, equity-macro (FRED) regime tag. The point is *transfer* — one market's price as another market's feature.
- Reuse the built LLM adapter (`ingest/standardize.py`) only where a source is genuinely unstructured; numeric odds/bars/macro **skip the LLM**.

**C. Add the cross-asset arm to the ablation — extend `apps/engine/cosmu/research/gate.py` (`evaluate_ablation`)**
- Now **four arms** on the **same** windows / costs / wall: (1) single-asset price-only · (2) single-asset + alt-data *(both already built)* · **(3) cross-asset + alt-data (new)** · (4) buy-and-hold.
- Add a **per-asset-class** drop-one report alongside the existing per-source one (how much each class moves deflated Sharpe).
- **Pre-registered pass bar (log before looking; changing it after counts as a new trial):**
  - arm (3) net return **> arm (1)** *and* **> arm (2)** *and* **> buy-and-hold**, all net of the same costs
  - `num_trades ≥ 30` · `PSR(SR0) ≥ 0.95` after global-trial deflation · `overfit metric < 0.50`
  - **positive net in ≥ 2 regime folds** · `max_drawdown < 0.25`
  - **attempt budget ≤ 12** variants total, **every attempt counted in the global trial counter** (`master/trials.py`).
- Verdict: `PASS` (cross-asset thesis real → Phase 2 with all classes) / `STOP-narrow` (keep single-asset, cut classes that didn't pay, per the per-class report).

**D. Tests — `apps/engine/tests/` (extend, keep all existing green)**
- Each new provider serves point-in-time offline; a *revised* snapshot does not rewrite an earlier read; survivorship limit asserted for the equity fixture.
- The four-arm ablation runs end-to-end on fixtures and prints a deterministic verdict + per-source *and* per-asset-class drop-one.
- No LLM call in any backtest/scoring path (asserted); global trial counter increments once per attempt.

### Out of scope (do NOT build)
Execution adapters (IBKR, Polymarket live wallet) · **any paid data vendor** (Norgate/Sharadar/Databento) · UI (sidebar/charts/routes) · NautilusTrader · vectorbt/Optuna · Supabase/pgvector/RAG · survival model · live trading · LunarCrush. These are Phases 2–4, conditional on this gate.

### Definition of Done (Phase 1.6)
- All existing + new tests pass under `python3 -m pytest apps/engine/tests`.
- `python3 -m cosmu.research.gate` runs **offline** and prints a deterministic **four-arm** verdict + per-source and per-asset-class drop-one against the pre-registered bar; trial counter increments per attempt.
- No LLM call in any non-ingest path; **no execution adapter, no paid vendor**; no magic numbers; no survivorship/lookahead/holdout-reuse paths introduced (free-equity survivorship limit explicitly declared, not hidden).

---

## FOUNDATION REFERENCE — Phases 0+1 (BUILT — do not rebuild)

*The honest wall + the first single-signal gate. Retained so the invariants and acceptance math stay legible. This is already implemented; treat it as the spec the active unit builds on.*

## Mission (one paragraph)

Make the deterministic scorer a wall you can bet real money behind, then build the harness that
proves — cheaply and honestly — whether an exploitable edge exists on Binance spot after costs.
No LLM, no UI, no pipeline, no new cloud services in this build. Just correct math, honest data
handling, and a pre-registered gate. If the gate later fails, that is a valuable result and the
project stops; the machinery you build here is what earns the right to build the rest.

## Cold-start reading (in order, do not load whole files)

1. `AGENTS.md` — invariants + decision tables.
2. `docs/PLAN.md` — strategy, the gate-first sequence, §2 venue constraint, §6 risks.
3. `docs/IMPLEMENTATION.md` — what is real vs stubbed.
4. The intent-spec header of each module before you edit it.

## Hard invariants (non-negotiable — these define correctness)

- The **scorer and money are deterministic and out of any LLM path.** This build contains **no LLM
  calls at all.**
- **No magic numbers in strategies** — thresholds/lengths come from a fitted `param_space`.
- **No hardcoded "edge."** Unsupported features produce *no trades*, never invented returns.
- **Point-in-time integrity** everywhere: data is read "as you would have known it then."
- **Determinism:** seeded, reproducible for a fixed data cache.
- Verify with `python3 -m pytest apps/engine/tests` (the interpreter is `python3`; there is no `uv`
  or `ruff` locally — CI runs lint). Keep all existing tests green.

## Scope — build ALL of this in one pass

### A. Rewrite the scorer into a real wall — `apps/engine/cosmu/master/scorer.py`

Replace the hand-invented penalty with the genuine statistics. Six fixes, all required:

1. **Deflated Sharpe done correctly (DSR/PSR).** DSR = Probabilistic Sharpe Ratio evaluated against
   a benchmark `SR0` that is a function of the **number of trials** *and* the **cross-sectional
   variance of the trials' Sharpe ratios**, with the PSR non-normality adjustment for the return
   series' **skew and kurtosis** (crypto returns are fat-tailed — ignoring this overstates
   significance). Not `sharpe − f(N)`.
2. **Global trial accounting.** Deflate against the **cumulative number of hypotheses ever tested**
   (persist a running trial counter + the per-trial Sharpe samples in the store), not the per-spec
   `param_space` size. Family-wise error across an unbounded hypothesis search is the real overfit
   risk.
3. **Real overfit metric.** PBO (Probability of Backtest Overfitting) is defined by **CSCV/CPCV** —
   a combinatorial set of purged, embargoed train/test splits — not a per-strategy scalar. Implement
   a minimal **CSCV** here (it is the same machinery as CPCV; do not defer it and keep calling a
   proxy "PBO"). If you must ship an interim scalar, name it `overfit_proxy`, not `pbo`.
4. **Purged + embargoed splits.** Any cross-validation purges overlapping-label bars and applies an
   embargo so train/test do not leak across the boundary.
5. **One-shot holdout (see §D).** The scorer reads a holdout verdict from the ledger; it never
   re-evaluates a consumed holdout.
6. **Pin against reference values.** The DoD is that DSR/PSR/CSCV reproduce **known worked examples
   or a hand-computable synthetic** — not merely "PBO rises with trials."

Keep `score(metrics, gates) -> ScoreVerdict` as the public seam so callers don't change.

### B. Capacity- & regime-aware backtest — `apps/engine/cosmu/data/backtest.py`

- **Capacity-aware costs.** Replace the flat `slippage_bps=5` with a **size-aware** cost model:
  slippage grows with order notional relative to bar volume (a simple square-root or linear market-
  impact model is fine), plus spread. Expose the capacity assumption as a parameter. Report the
  notional at which the edge decays.
- **Regime-aware evaluation.** Split the sample into labelled regime folds (at minimum bull / bear /
  chop, by a simple trend+vol rule on BTC) and report per-fold net return so the wall can require an
  edge to survive **more than one regime**.
- Keep prior-bar signals → next-bar fills → venue fees; keep the last fifth as holdout evidence.
- Support **hand-specified signals** (for §F) without the full spec machinery — compute the 1–2 gate
  signals directly so an indicator-library bug can't fake the gate.

### C. Survivorship-safe universe — `apps/engine/cosmu/data/universe_calendar.py` (new)

- Point-in-time **listing/eligibility calendar**: a symbol is only tradeable at time *t* if it was
  listed and liquid then. At minimum, derive eligibility from "had ≥ N bars and ≥ liquidity floor
  before *t*"; better, use ccxt listing metadata. Backtests/gates iterate only eligible symbols at
  each *t* — never the *current* liquid set (that is survivorship bias and inflates everything).

### D. One-shot holdout ledger — `apps/engine/cosmu/master/holdout.py` (new) + schema row

- A **holdout consumption ledger**: each strategy version gets **exactly one** holdout evaluation,
  logged (version_id, ts, metrics) and locked. Re-requests are **refused** (raise / return the
  recorded verdict, never recompute). This is what stops an autonomous loop from silently
  incinerating the holdout by iterating against it.

### E. Alt-data provider seam — `apps/engine/cosmu/data/altdata.py` (new)

- `AltDataProvider` Protocol + a `LunarCrushProvider` impl (reads key from settings, server-side
  only) + an **offline `FixtureAltDataProvider`** so everything builds and tests without a key
  (mirror the existing `MarketDataProvider` injection pattern).
- **Immutable, append-only snapshots.** Vendor pulls are stored append-only with the **availability
  timestamp**; never upsert-in-place (vendors revise history, which would retroactively rewrite your
  point-in-time truth). Reads select the latest snapshot ≤ *t*.
- **Causal transforms only:** any normalization (z-score, winsorize) uses rolling/expanding windows,
  never full-sample.

### F. The edge-gate harness + pre-registered bar — `apps/engine/cosmu/research/gate.py` (new)

- Define **1–2 hand-built signals** (assume **spot, long-only**; treat funding extreme as a **long
  filter**, per PLAN §2): e.g. social-momentum (LunarCrush galaxy_score rolling z-score) and a
  funding-filtered momentum entry, point-in-time, on eligible liquid pairs.
- Run them through the **§A wall** and the **§B costs**, benchmarked vs **BTC/ETH buy-and-hold** net
  of the same costs.
- **Pre-registered pass bar (log it before looking; changing it after counts as a new trial):**
  - `num_trades ≥ 30`
  - `PSR(SR0) ≥ 0.95` (DSR positive after global-trial deflation)
  - `overfit metric < 0.50`
  - net return **> buy-and-hold net** over the same window
  - **positive net in ≥ 2 regime folds**
  - `max_drawdown < 0.25`
  - **attempt budget ≤ 12** signal variants total, **every attempt counted in the global trial
    counter** (the gate itself must not be p-hacked).
- Emits a clear verdict: `PASS` (proceed to Phase 2) or `STOP` (thesis falsified — a real result).

### G. Tests — `apps/engine/tests/` (extend, keep all existing green)

- Scorer pinned to reference values (DSR/PSR/CSCV).
- Holdout one-shot: second evaluation is refused and returns the recorded verdict.
- Survivorship: a delisted symbol present at *t1* but gone at *t2* is included at *t1*, excluded at *t2*.
- Capacity: net return degrades monotonically as size rises.
- Regime: per-fold returns are reported; a single-regime winner fails the ≥2-fold rule.
- Gate harness runs end-to-end on the offline fixture provider and prints a verdict deterministically.

### H. Declutter (cheap, do it while you're here)

- Add `__pycache__/` and `*.pyc` to `.gitignore`, then `git rm -r --cached` the tracked ones.
- Untrack `TradingAgents-main/` (~5 MB vendored reference, not product code) — `git rm -r --cached` it and add to `.gitignore` (it's ingested into RAG later, not built here).
- Delete any hand-rolled code your §A/§B rewrites supersede — no dead surrogate beside the real thing.
- If you touch AGENTS.md, drop its stale "Legacy v1 / `apps/api`" section (`apps/` is only `engine` + `web` now).

### I. Run it

- A CLI entry (`python3 -m cosmu.research.gate`) and/or a `POST /research/gate` endpoint that runs the
  harness and returns the verdict + the pre-registered bar it was judged against. Regenerate TS
  contracts if you add an endpoint (`python3 scripts/generate_contracts.py`).

## Out of scope — do NOT build in this pass

LLM wiring · Prefect · Supabase migration · pgvector/RAG · survival model · vectorbt/Optuna swap
(the existing Python backtest is correct enough for the gate) · the UI (sidebar, charts, tri-state
toggles) · NautilusTrader · live trading. These are Phases 2–4 and are **conditional on the gate
passing.**

## Open decisions — assumed defaults (flagged for the owner)

1. **Spot vs futures:** assumed **spot, long-only**; funding/OI used as **long filters**, not
   standalone signals. (Changing to futures widens the hypothesis space — owner decision.)
2. **LunarCrush tier/key:** built behind an offline fixture; owner supplies the key to run the gate
   for real.

## Definition of Done

- All existing tests + the new tests pass under `python3 -m pytest apps/engine/tests`.
- `pnpm --filter @cosmu/web build` still succeeds (contracts regenerated if an endpoint was added).
- The scorer's DSR/PSR/CSCV match pinned reference values.
- The gate harness runs offline and prints a deterministic `PASS`/`STOP` verdict against the
  pre-registered bar, with the global trial counter incremented per attempt.
- No LLM call, no new cloud dependency, no magic numbers, no survivorship/lookahead/holdout-reuse
  paths introduced.
