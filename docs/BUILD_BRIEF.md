# Cosmu v2 — Build Brief

> **Status (2026-06-01):** Phases 0+1 below — **the honest wall + the first single-signal gate — are BUILT** (`scorer.py`, `research/gate.py`, `holdout.py`, `altdata.py`, `universe_calendar.py`, `trials.py`; see `IMPLEMENTATION.md`). They are **reference only — do not rebuild them.**
>
> **The active build unit is Phase 1.5 below — build it in one pass.** It is the cheapest honest test of the differentiator: *does aggregating numerous, complex, point-in-time sources and LLM-standardizing them add edge over price alone, after costs?* Read `docs/PLAN.md` §0–§2 + Phase 1.5 for the why; this brief is the what + the acceptance bar.

---

## ACTIVE UNIT — Phase 1.5: Prove the aggregation edge

### Mission (one paragraph)
Extend the existing wall + gate to answer the two questions the product actually exists for: **(1) does aggregating complex data beat price-only, after costs, point-in-time? and (2) does combining asset classes beat any single one?** — the cross-asset/decorrelation edge most likely to pay at small size. Run it as a **multi-arm ablation** (single-asset price-only vs single-asset+alt vs **cross-asset+alt** vs buy-and-hold) on **free multi-asset data ($0, no paid vendors)**, with per-source *and* per-asset-class drop-one reports so the owner learns *which assets and which data* pay. This is the **data/signal plane only — execution stays one-venue/simulated and paid vendors are deferred** (PLAN §2 two-plane split). No UI, no Nautilus, no vectorbt, no Supabase, no live — one pass. If cross-asset+alt doesn't beat the baselines, that is a valuable result: cut the data/assets that didn't pay, not the project.

### Cold-start reading (in order, do not load whole files)
1. `AGENTS.md` — invariants + decision tables.
2. `docs/PLAN.md` §0–§2 (LLM at ingest-time not hot path; §2 venue constraint) + **Phase 1.5** in §4.
3. `docs/IMPLEMENTATION.md` — what is real vs stubbed (the wall + first gate are real).
4. The intent-spec header of each module before you edit it.

### Hard invariants (carry over from Phases 0+1, plus one)
- **LLM only at ingest-time, frozen.** Any LLM transform is defined **once** → validated (`instructor`/Pydantic) → **versioned + content-hash-cached** → deterministic code runs it forever. **Zero LLM calls in the backtest, scoring, or decision paths.** The whole gate must run **fully offline via fixtures** (CI has no keys).
- The **scorer and money stay deterministic and out of any LLM path.**
- **No magic numbers in strategies** — thresholds/lengths come from a fitted `param_space`.
- **No hardcoded "edge."** Unsupported features produce *no trades*, never invented returns.
- **Point-in-time integrity** everywhere: data is read "as you would have known it then" (availability time, not event time).
- **Determinism:** seeded, reproducible for a fixed data + fixture cache.
- **Every source/feature declares a prior hypothesis.** More data = more overfitting surface; a source that can't say why it carries swing-horizon edge does not get built.
- Verify with `python3 -m pytest apps/engine/tests`; keep all existing tests green.

### Scope — build ALL of this in one pass

**A. Three free sources behind the existing seam — `apps/engine/cosmu/data/altdata.py`**
Extend the `AltDataProvider` Protocol; mirror the existing `FixtureAltDataProvider` so everything builds and tests with no key. All three: **immutable, append-only snapshots stamped with availability time** (never upsert — vendors revise history); reads select the latest snapshot ≤ *t*; causal transforms only (rolling/expanding, never full-sample).
1. **Crypto funding rate + open interest** (ccxt / exchange REST, free) — used as a **long filter** (spot, long-only per PLAN §2), not a standalone signal.
2. **Fear & Greed index** (alternative.me, free, daily).
3. **One genuinely unstructured source** (crypto news headlines, free tier) — the source that exercises the LLM-as-universal-adapter.

**B. The LLM universal adapter, done right — `apps/engine/cosmu/ingest/standardize.py` (new)**
- Maps the **unstructured** source (A.3) → a validated numeric row (e.g. `{event_type, sentiment, confidence}`) via `instructor`/Pydantic, **cheap tier, batched, cached by content hash, hard daily cost cap.**
- The transform is **versioned** (`transform_version` pinned into any feature that uses it) with a **deterministic offline fixture** so the gate runs with no key.
- A's numeric sources (funding/OI/F&G) **skip the LLM** — make that explicit; the LLM earns its place *only* on messy text.

**C. Hypothesis-backed features — extend `apps/engine/cosmu/config/feature_registry.py`**
- 2–3 features, each with a one-line **prior** + its `transform_version`: e.g. news-sentiment z-score; funding-extreme long filter; F&G mean-reversion regime tag.

**D. The ablation gate — extend `apps/engine/cosmu/research/gate.py`**
- Run **three arms** on the **same** eligible universe (`universe_calendar.py`), same costs (`data/backtest.py`), same wall (`master/scorer.py`): (1) **price-only** baseline, (2) **+ alt-data features**, (3) **buy-and-hold** BTC/ETH.
- Emit a **drop-one** per-source marginal-contribution report (how much each source moves deflated Sharpe).
- **Pre-registered pass bar (log it before looking; changing it after counts as a new trial):**
  - alt-data arm net return **> price-only arm** *and* **> buy-and-hold**, all net of the same costs
  - `num_trades ≥ 30` · `PSR(SR0) ≥ 0.95` after global-trial deflation · `overfit metric < 0.50`
  - **positive net in ≥ 2 regime folds** · `max_drawdown < 0.25`
  - **attempt budget ≤ 12** variants total, **every attempt counted in the global trial counter** (`master/trials.py`) — the gate itself must not be p-hacked.
- Verdict: `PASS` (aggregation thesis real → Phase 2) / `STOP` (cut to the sources that paid, per the drop-one report).

**E. Tests — `apps/engine/tests/` (extend, keep all existing green)**
- Each provider serves point-in-time offline; a *revised* snapshot does not rewrite an earlier point-in-time read.
- LLM adapter is deterministic given the fixture; a cache hit avoids a second call; no LLM call occurs in any backtest/scoring path (asserted).
- Ablation runs end-to-end on fixtures and prints a deterministic three-arm verdict + per-source drop-one contributions.
- Global trial counter increments once per attempt.

### Out of scope (do NOT build)
UI (sidebar/charts/routes) · NautilusTrader · vectorbt/Optuna · Supabase/pgvector/RAG · survival model · live trading · LunarCrush wiring beyond leaving the provider seam ready (free sources first — a $0 real gate beats a paid one). These are Phases 2–4, conditional on this gate.

### Definition of Done (Phase 1.5)
- All existing + new tests pass under `python3 -m pytest apps/engine/tests`.
- `python3 -m cosmu.research.gate` runs **offline** and prints a deterministic three-arm verdict + per-source marginal contribution against the pre-registered bar; trial counter increments per attempt.
- No LLM call in any non-ingest path; no new paid cloud dependency; no magic numbers; no survivorship/lookahead/holdout-reuse paths introduced.

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
