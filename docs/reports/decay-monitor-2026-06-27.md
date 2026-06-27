# Time-axis decay monitor — pheromone-evaporation backtest study (2026-06-27)

> Playbook bridge **#8** (swarm/ACO *pheromone-evaporation allocation decay*) + red-team item **"post-discovery
> alpha decay"** from `docs/reports/cross-disciplinary-playbook-2026-06-26.md`. A **backtest-only** study + the
> **designed** live rule. Nothing is wired into the order path; gate/scorer constants are untouched; no money moves.
> Code: `apps/engine/cosmu/research/decay_monitor.py` · Tests: `apps/engine/tests/test_decay_monitor.py`.

## BLUF
1. **What it is.** An edge decays after discovery. The monitor multiplies each track's size by `exp(-Δt/τ)`, where
   `Δt` = periods since the track's **last significant forward confirmation** and `τ` = **the combo's backtest edge
   half-life** (`master/drift.fit_edge_decay`). A forward confirmation = a trailing window whose Probabilistic
   Sharpe clears the **same live-arming floor** the engine already uses (`PAPER_MIN_FORWARD_DSR` over
   `PAPER_MIN_FORWARD_OBS` obs) — re-proof on data the discovery never saw, which **resets the evaporation clock**.
2. **The test.** Replay each track's forward window under two policies and compare **risk-adjusted return**:
   the **decayed book** (evaporation overlay) vs the **hold-until-fail book** (the literal current baseline:
   full size until the wallet kill, `master/risk.py`).
3. **The result (method-validation panel).** When an edge **decays past zero** (the crowded-out / arbed-away case
   the red-team fears), the decayed book wins on **every** risk-adjusted dimension and across **12/12 seeds**:
   mean Sharpe **3.81 vs 1.63**, mean max-drawdown **12.2% vs 18.8%**. When the edge **persists** or is genuinely
   **re-confirmed**, the overlay correctly **stays out of the way** (mean Sharpe margin ≈ **0**). The asymmetry is
   the whole case: a **large** gain when the edge dies, a **negligible** cost when it lives.
4. **Decision.** Decayed wins on risk-adjusted return ⇒ the live decay rule is **designed below** (§4) — but
   **NOT wired** in this PR. Wiring waits on a **real-bar Modal run** confirming the win on live tracks (§3, command).

## 1. Thesis (why a time-axis instrument at all)
The Gate is the **discovery** filter — a single-snapshot judge of whether an edge was real *at backtest time*. The
killers the playbook names are all **downstream** of that snapshot, on the **time axis**: an edge that was real on
discovery **decays** as it gets crowded/arbed, and a snapshot Sharpe can't see it. ACO's answer to "which trails
still matter" is **pheromone evaporation**: a trail's weight decays on a half-life and is only kept alive by
**fresh reinforcement**. Mapped onto COSMU: a track's **size** should evaporate on its edge half-life unless it is
**re-confirmed forward**. The current policy is the opposite — **hold-until-fail**: full size until the wallet kill.

## 2. Method (deterministic, causal, offline)
- **τ — the combo's backtest edge half-life.** `edge_half_life(returns)` = `fit_edge_decay(rolling_edge(...))`
  from `master/drift.py` — the existing alpha-decay primitive. τ is fit on the **discovery/backtest window**
  (where the edge is still positive and merely *decaying*); a flat/rising/already-dead window returns **None** ⇒
  **no evaporation** (a non-decaying trail has no half-life and keeps full size). *Fitting τ on the full series
  would silently disable the very evaporation a dead tail needs — `fit_edge_decay` reports None once an edge has
  crossed zero — so the discovery/forward split is load-bearing.*
- **Forward confirmation — the clock reset.** `is_forward_confirmation(window)` reuses the scorer's PSR verbatim:
  `PSR(window Sharpe vs 0) − 0.5 > PAPER_MIN_FORWARD_DSR` over `≥ PAPER_MIN_FORWARD_OBS` obs — **byte-identical**
  to `master/live_eligibility.forward_significance`. So "significant forward confirmation" speaks the live gate's
  language; it is not a new magic number.
- **The kernel.** `pheromone_weight(Δt, τ) = exp(−Δt/τ) ∈ (0,1]`. Size is full at funding (just confirmed by the
  backtest), reaches `e⁻¹ ≈ 0.37` at `Δt = τ`, and resets to full whenever a forward confirmation fires.
- **Causality.** The weight for period *t* is decided **only** from returns strictly **before** *t*; the period's
  own return updates the clock for *t+1*. (`test_decay_weights_are_strictly_causal` perturbs the future and proves
  past/present weights are untouched.)
- **The two books.** Each track holds a fixed `1/N` slice. **Decayed** = hold-until-fail × the evaporation
  overlay; **evaporated size sits in CASH** (un-renormalized), so the study measures the honest cost/benefit of
  *pulling* capital as a trail goes stale — not a reshuffle that is always fully invested. **Hold-until-fail** =
  full size until the compounded equity hits the wallet kill floor (`master/risk.py`; prod default = ruin).
- **Risk-adjusted metrics.** Annualized Sharpe (headline), Calmar, max-drawdown, total/annualized return, and
  `forward_dsr` (PSR vs 0) — all from `master/risk_metrics.py` + the scorer PSR.

## 3. Evidence
### 3a. Method-validation panel (synthetic — CI/tests only; NEVER displayed in the app, NEVER run in prod)
A deterministic, seeded panel of 12 correlated tracks (shared market shock + idiosyncratic noise), 160 periods,
funded at period 50. Three post-discovery shapes, each replayed through the **exact** study. *Absolute Sharpes for
the two control shapes are idealized — a truly persistent 1.6%/period edge is unrealistically profitable — so for
the controls only the **relative margin ≈ 0** is meaningful; the **decaying** shape has realistic absolute levels.*

| Shape | What it models | Verdict | Decayed Sharpe | Hold Sharpe | Decayed maxDD | Hold maxDD |
|---|---|---|---|---|---|---|
| **decaying** | edge decays **past zero** (crowded out) | **DECAYED-WINS** | **4.16** | 2.32 | **10.1%** | 15.7% |
| persistent | constant edge, **no decay** (τ = None) | TIE | 61.12 | 61.16 | 0.0% | 0.0% |
| reconfirmed | decays but **re-discovered** periodically | TIE | 46.03 | 46.09 | 0.0% | 0.0% |

*(seed 7; `python -m cosmu.research.decay_monitor --source synthetic --scenario <shape> --seed 7`)*

**Robustness — the decaying shape across 12 seeds:** decayed wins **12/12**; mean Sharpe **3.81 vs 1.63**
(Δ mean **+2.18**, min **+0.98**); mean max-drawdown **12.2% vs 18.8%**. **Controls across 12 seeds:** persistent
mean margin **−0.025** (max |Δ| 0.48), reconfirmed mean margin **−0.056** (max |Δ| 0.50) — flat. The overlay acts
**strongly** when the edge dies and is a **near-zero-cost no-op** when it doesn't.

What the panel proves: the **machinery** computes the right thing — it captures the decay benefit, cuts the
drawdown, resets on genuine forward re-proof, and does **not** manufacture a win where there is no decay (the
red-team's own "could this just be overfitting the instrument?" disconfirmer).

### 3b. Real-bar evidence (run on Modal — bounded compute)
This sandbox has **no market-data egress** (the agent proxy denies Binance/Railway with 403), so the real-bar run
is a documented Modal job, per the AGENTS.md compute model (heavy/real-data ⇒ Modal, never the M2 or a chat
session). The driver `load_tracks_from_store` reads each funded track's realized forward record from
`portfolio_snapshots` and replays it through the identical study:

```
modal run apps/engine/remote/app.py --job run_module \
  --module cosmu.research.decay_monitor --args "--source store --out decay_report.json"
```

Bounded by construction: read-only over `portfolio_snapshots`, a handful of funded tracks, pure-Python analytics,
no grid/sweep. The live rule (§4) is gated on this run reproducing §3a's verdict on real tracks.

## 4. The designed live decay rule (NOT wired in this PR)
Wired **only after** §3b confirms the win on real tracks, and behind its own switch:
1. **Where.** A new size multiplier in `master/sizing.py`: `size_fraction(...) *= live_decay_multiplier(cell)`.
   The scalar is already exposed — `decay_monitor.live_decay_multiplier(realized_returns, tau)` returns the last
   `exp(−Δt/τ)` weight. It is **not called by any live path** in this PR (the order path is unchanged).
2. **Inputs (all point-in-time, already in the store).** `realized_returns` = the cell's `portfolio_snapshots`
   forward series; `τ` = the combo's **stored backtest edge half-life** (computed at funding, not re-fit live, so
   the live rule cannot peek forward); `Δt` = periods since the cell's last forward confirmation
   (`forward_significance` already computes the same statistic).
3. **Guardrails (non-negotiable).** (a) τ = None ⇒ multiplier = 1.0 (a non-decaying edge is never pulled).
   (b) Deterministic + LLM-free — it lives in `master/`, out of any LLM path, like `drift.py`. (c) It only ever
   **shrinks** size toward cash and resets to full on forward re-confirmation — never sizes **up**, never
   martingales. (d) The wallet kill and the existing drift defund remain underneath; evaporation is an **overlay**,
   not a replacement. (e) Behind a named policy switch (default **off**) with an audit event per adjustment.
4. **Relationship to the existing drift defund.** `drift.assess_drift` is a **binary, reactive** defund (cut to
   zero when thresholds trip). Evaporation is **continuous and anticipatory** — it trims size *gradually* as a
   trail goes stale and *restores* it on re-proof. They are complementary: drift handles the hard kill, evaporation
   handles the graceful taper that §3 shows is worth ~+2 Sharpe and ~−7pts max-drawdown when an edge decays.

## 5. Invariants honored
- **Gate constants LOCKED.** The study only **reads** `PAPER_MIN_FORWARD_DSR` / `PAPER_MIN_FORWARD_OBS`; it adds
  no scorer/FDR/gate knob and changes none.
- **No money path.** Backtest-only; the live rule is design + a non-wired scalar. Live stays OFF behind the 5
  interlocks.
- **No synthetic in prod.** The panel is quarantined to CI/tests, labeled `synthetic-fixture`, never surfaced.
- **No magic numbers in specs.** The thresholds are **policy constants** (like `drift.py`'s), borrowed from the
  live arming gate — not strategy params.
- **Deterministic + offline + point-in-time.** Seed-free analytics; causal weights; no look-ahead.
