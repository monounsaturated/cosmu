# EPIC: Regime / Context Deep-Analysis Layer

> Source: operator chat 2026-06-14 (reflection on the BNP Paribas trading-floor video — "correlation smile," fat-finger safeguards, indicative-vs-firm price, the 24/7 night desk).
> Status: **PLAN ONLY** (operator: "just the plan for now"). Nothing here is built yet.
> Compute tier: **PENDING operator pick** — price table in §8. Default recommendation: **Tier B**.
> Detail level: full. The short pointer + tagged items live in `BACKLOG.md`.

---

## 0. Why (north-star justification)

The one metric is **realized risk-adjusted profit, net of every cost**. The single biggest
leak between a gate-passed SIM number and realized live P&L is **regime blindness** — a strategy
that only ever proved itself in one weather (bull / low-vol / risk-on / uncorrelated) gets funded,
then the weather turns and the edge inverts. The trading-floor video named the mechanism: the
**correlation smile** — "assets are uncorrelated when things go well; in the decline, everything
correlates." This epic makes the whole pipeline regime-aware so survivors are proven across
weathers, stress-tested against the correlated-decline, and continuously re-analyzed — which
*directly* raises the quality (and live-survival) of funded tracks.

This is also the "lean solo agentic" thesis made concrete: the analysis a 1,200-person floor
spreads across structurers, risk, and a 24/7 multi-timezone desk is collapsed into a deterministic
core + parallel propose-only sub-agents that never sleep.

## 1. The alignment lock (non-negotiable)

Every new capability in this epic MUST be exactly one of:

- **(a) a point-in-time feature/label** strategies *may* reference, which **must earn its trust OOS**
  (tier1 until validated; the Gate down-weights it until then); or
- **(b) a deterministic robustness gate** that can only make the bar **harder** (kill fragile edges),
  never easier, behind a `GateSettings` flag, out of every LLM path; or
- **(c) propose-only analysis** that is **summarized for the operator** and never funds, defunds,
  sizes, or moves money.

Nothing new touches the **fitness metric** (`master/scorer.py`) or the **money path**
(`orchestrator` / live toggle / 5 interlocks). ML and RL live entirely on the *propose* side.
This is the "two things the AI never touches: the scorer and the money" invariant, and it is the
structural answer to the video's "two wrong prices that agreed" trap — keep the proposer and the
judge independent, so new analysis can only add skepticism or context, never manufacture confidence.

## 2. What already exists (this epic is mostly wiring, not greenfield)

| Capability | Status | File |
|---|---|---|
| Trend regime (bull/bear/chop, ±5% band) | crude, wired | `apps/engine/cosmu/data/backtest.py:675` (`_regime_labels`) |
| Vol terciles (low/mid/high) | wired (diagnostic only) | `apps/engine/cosmu/ml/regime.py:43` (`_vol_bucket`) |
| Live-eligibility on proven regimes | wired | `apps/engine/cosmu/ml/regime.py:78` (`proven_regimes` / `regime_eligible`) |
| No-repaint Markov regime detector | built, parked ("momentum-subsumed overlay") | `apps/engine/cosmu/research/regime_cohort.py` |
| Macro features (curve, VIX, fed, credit, DXY, gold, risk-on) | ingested, **NOT used for regime splitting** | `apps/engine/cosmu/config/feature_registry.py` |
| Combinatorial Purged CV | **banked, NOT wired into Gate** | `apps/engine/cosmu/master/cpcv.py` |
| Half-normal slippage Monte-Carlo / fragility flag | **banked, NOT wired** | `apps/engine/cosmu/data/slippage.py` (`stress_returns`) |
| Deflated Sharpe + CSCV-PBO + BH-FDR | wired (immovable core) | `apps/engine/cosmu/master/scorer.py`, `master/fdr.py` |
| SIM→live variance attribution (regime Brinson bucket) | wired (review-only) | `apps/engine/cosmu/research/attribution.py` |
| Edge-decay + drift CUSUM (anticipatory defund) | wired | `apps/engine/cosmu/master/drift.py` |
| Triple-barrier meta-label (size/skip only) | wired in spec | `apps/engine/cosmu/strategy/spec.py` (`MetaLabel`) |
| Parquet/DuckDB cold tier, Modal heavy-compute lane | extras present, mostly unused | `pyproject.toml [lake]/[remote]`, `apps/engine/remote/app.py` |
| PIT alt-data store + feature registry + as-of join | production-grade | `data/providers/store.py`, `config/feature_registry.py`, `data/alt_join.py` |
| GraveyardMemory RAG + research_notes summaries | wired | `knowledge/memory.py`, `research/summary_facts.py` |
| **Multi-axis context label (macro × vol × correlation)** | **MISSING** | — |
| **Scenario / historical-replay / correlation-spike stress** | **MISSING** | — |
| **Parallel deep-analysis fan-out + auto-summaries** | **MISSING** | — |
| **RL experiment lane** | **MISSING** | — |

## 3. Phase 1 — Multi-axis context/regime labeler (PIT) ⭐ the core

New `apps/engine/cosmu/research/context.py`: compute a **multi-axis, point-in-time context label**
per bar/day, market-wide and per-asset:

- **Trend**: bull / bear / chop — upgrade from the ±5% band to the parked no-repaint detector
  (`research/regime_cohort.py`) + slope/Donchian confirmation.
- **Vol**: low / mid / high (reuse `ml/regime.py:_vol_bucket`) + a crisis / vol-of-vol flag.
- **Macro**: from `macro_regime` (FRED curve/real-rates/liquidity), fed-funds *direction*
  (hiking/pausing/cutting), `credit_spread` stress, `dxy` trend.
- **Risk-on/off**: `pm_risk_on` + a gold/SPX/credit composite.
- **Correlation regime** (the correlation smile): rolling average pairwise cross-asset correlation;
  flag a **`correlated_decline`** state when it spikes while trend is bear.

Storage & wiring (schema-free):

1. Store each axis as an **`alt_data` metric** (`provider="context"`, `symbol="MARKET"` or per-asset)
   via the existing ingest pattern — **no new table**. Lag `available_at` one bar (no look-ahead).
2. Register each in `config/feature_registry.py` (tier0/tier1, with `prior` + `transform_version`).
3. Add a daily ingest lane in `apps/engine/railway.toml` (after close), and add to the
   `_STORE_PROVIDER_OF` / `_STORE_MARKET_WIDE` routing in `data/providers/store.py`.
4. Replace `_regime_labels()` (`data/backtest.py:308`/`:675`) with a context-aware labeler that
   reads these PIT labels, so per-trade regime tagging and `regime_returns` use the rich label.
5. `proven_regimes()` / `regime_eligible()` (`ml/regime.py:78`) then gate live-eligibility on the
   **real composite regime** — a strategy proven only in `bull/low_vol/risk_on` is correctly benched
   when the current regime is `bear/high_vol/correlated_decline`.

Guardrails: causal, no-repaint, validated against shuffle/placebo controls (the discipline
`regime_cohort.py` already enforces). The labels are *features that must earn OOS* (alignment lock a).

**Acceptance:** regime labels visible per-trade and in the app; live-eligibility decided on the
composite regime; no-repaint test + shuffle placebo green; `pnpm verify` green.

## 4. Phase 2 — Wire banked robustness gates + correlation-smile stress (only ever *harder*)

- **Wire CPCV** (`master/cpcv.py`) into the champion (post-survivor) validation path — multi-path
  robustness on top of the single holdout.
- **Wire slippage-stress** (`data/slippage.py:stress_returns`) into scoring — kill edges that only
  survive at *mean* slippage (flag FRAGILE).
- **Regime-conditioned folds**: now that Phase 1 gives real labels, require positive net edge in
  ≥2 *real* regimes **and** specifically survive `bear`/`high_vol`/`correlated_decline`.
- **Correlation-spike scenario as a hard check**: re-simulate under a forced "everything correlates
  to 1 / liquidity dries up" shock (widen slippage+impact, collapse diversification benefit). The
  correlation smile, encoded as a gate.

All four are deterministic, seeded, out of the LLM path, behind `GateSettings` flags. They only
tighten the bar (alignment lock b). **This phase touches the immovable core** — the `PREREGISTERED_BAR`
move needs explicit operator sign-off (see `BACKLOG.md` gate-bar-drift guard discipline). Overlaps
the existing backlog item "Gate hardening: route the cohort through the full `research/gate.py:PREREGISTERED_BAR`".

**Acceptance:** a known-fragile fixture strategy that passes today is correctly killed; the
`PREREGISTERED_BAR` ≡ `GateSettings` mirror test still pins; `pnpm verify` green.

## 5. Phase 3 — Scenario / stress lab (propose-only)

New `apps/engine/cosmu/research/scenario_engine.py` (deterministic, seeded):

- **Historical replay**: 2008, COVID-2020, 2022 crypto winter (LUNA/FTX), May-2021 — using the
  deep history from Phase 0.
- **Synthetic shocks** (quarantined to analysis — NEVER shown as real, NEVER gates funding):
  vol×N, slippage×N, funding×N, correlation→1, regime-transition.
- **Block-bootstrap Monte-Carlo** for confidence bands (heavy MC offloaded to Modal if Tier B/C).

Output → `research_notes` (kind=`scenario`) + `events` ledger; an advisory "fragility score"
surfaced in the app (advisory, never the gate). Review-only (alignment lock c). New skill
`/stress-test`. Builds on the existing slippage MC and the realtime-epic event-study harness (P1).

**Acceptance:** every funded survivor gets a scenario card; results reproducible for a fixed seed;
offline-testable with fixtures; `pnpm verify` green.

## 6. Phase 4 — Parallel deep-analysis fan-out + auto-summaries

After the Gate passes survivors (in `master/scheduler.py:run_tick`, post-replicate), spawn
**smaller parallel propose-only analysis sub-agents**, each a focused slice:

- regime-match (Phase 1 + a new `ml/regime_hypothesis.py::assess_regime_hypothesis`)
- scenario/stress (Phase 3)
- cross-asset correlation — "where else does this edge live?" → feeds `/evolve-strategy`
  (overlaps backlog "Cross-strategy correlation signals")
- attribution (funded tracks, `research/attribution.py`)
- decay/drift (`master/drift.py`)

Each writes **deterministic facts**; Claude (on the flat sub, exactly like the existing
`/backfill-summaries` pattern) synthesizes a **plain-language per-strategy summary** into
`research_notes`. The engine stores/serves; Claude writes the prose. New skill `/analyze`
orchestrates the slices via the proven `fan-out` pattern (one branch each, merge train). Distinct
from the existing web-research `deep-research` skill — name it `/analyze` to avoid collision.

Cost control: slice agents default to **Sonnet/Haiku**; Opus only for the final synthesis. Bounded
by the existing daily LLM/API spend cap.

**Acceptance:** one autonomy tick produces a deep-analysis summary per survivor; all sub-agents are
propose-only (no re-gating, no money); summaries carry the `facts_hash` staleness pin; `pnpm verify` green.

## 7. Phase 5 — RL experiment lane (operator: ASAP; still sandboxed + propose-only)

Pulled forward per operator. RL is the **most overfit-prone** generator, so it is fenced hardest:

- New `apps/engine/cosmu/evolution/rl_lane.py`: an RL policy (exit/sizing or entry-timing) trained
  **offline on real bars** (Modal if Tier B/C). Its output is **frozen into a deterministic
  `StrategySpec` param set** (thresholds land in `param_space`, no magic numbers) and routed through
  the **same FarmLoop Gate + BH-FDR** as every other candidate. RL is just another candidate
  *generator* — it never touches the scorer, the money, or live.
- Reward = the same net-of-cost objective the Gate optimizes (no bespoke fitness — alignment lock).
- Seeded + reproducible; runs in the research/paper lane only (the locked "gate-checked or not =
  research-vs-funded routing, NEVER a softer live bar" invariant from the 2026-06-13 epic).
- Honest framing: RL output that clears the Gate is real; RL that doesn't is a dead end recorded in
  the graveyard. Volume can't manufacture a winner (the whole RL cohort is one BH-FDR family).

Overlaps/extends the backlog "Multi-lane strategy INTAKE — ML | Prompt | Index" (RL is an ML-lane
generator) and "Deeper ML — geometric/vectorial, Modal-computed."

**Acceptance:** an RL-authored spec runs end-to-end through the Gate and is either funded (SIM track)
or graveyarded — with zero RL code anywhere in the scorer or money path; `pnpm verify` green.

## 7b. Phase 0 — Substrate (prerequisite for deep history + heavy compute)

- Deepen history (Binance 1d/4h/1h multi-year, equities 5y+, macro via FRED) through the existing
  `/manage-data` path — idempotent, append-only, no schema change. (Overlaps backlog "robust full
  backfill" + "Backfill 1m bars".)
- Wire the **DuckDB/Parquet cold tier** (`[lake]` extra) for columnar scans over the 17M-row
  `alt_data` — needed for correlation matrices, regime fits, scenario replay at scale. (Overlaps
  backlog "Local analytical layer — DuckDB over Parquet (on R2)" and "Hot/cold data tiering".)
- Optional: wire **Modal** (`apps/engine/remote/app.py`, already scaffolded) as the heavy-compute
  lane for Monte-Carlo + ML/RL fitting — keeps the cron tick lean. (Overlaps backlog "Compute Phase 2".)

## 8. Compute & cost — price ranges (operator asked; pick a tier)

All prices as of June 2026; usage-based, bounded by the existing **daily LLM/API spend cap**.

| Tier | What you get | Incremental cost / mo | Notes |
|---|---|---|---|
| **A — Lean** | pure-Python regime/scenario + DuckDB cold tier | **$0** | DuckDB & numpy-free; fully deterministic; LLM tokens already covered by Claude Max flat sub |
| **B — ML + Modal** *(recommended)* | `[ml]` extra (numpy/scipy/sklearn, all free) + Modal heavy-compute (scale-to-zero) | **~$0–60** | Modal Starter $0 platform + **$30/mo free credits** usually cover intermittent CPU sweeps (CPU ~$0.0000131/core-sec, ~3.75× for non-preemptible US ≈ $0.18/core-hr); GPU only if RL needs it |
| **C — Maximal + paid data** | Tier B + paid alt-data | **~$70 → $1,000+** | Nansen pay-per-use $0.01–0.05/call (or $0–69/mo); Glassnode API ≈ $999/mo (Studio Pro + sales-quoted add-on) — steep |

**Recommendation: Tier B.** It delivers real ML + "huge compute" (Modal scale-to-zero) while
staying inside the free credits most months, and matches the prior decision (Modal + Railway crons,
`docs/COMPUTE.md`). **Defer Tier C paid data** until a free-data strategy proves the edge exists and
the paid feed *measurably* improves it (cosmu's own ROI-gate / "buy commodities, build the
differentiator" / tier1-must-earn-OOS). RL on Modal CPU stays in Tier B; only reach for GPU if a
deep RL net is actually warranted.

## 9. Ask-first flags (cosmu rules)

- **Schema**: designed to be near schema-free — labels go in `alt_data` as metrics; analysis in
  `research_notes` as new *kinds*; audit in the generic `events` ledger. No DDL unless we choose a
  dedicated label table.
- **Spend/footprint**: the `[ml]` extra, Modal compute, and any paid data are real cost decisions
  (Tier choice above) — confirm before incurring.
- **Scorer changes** (Phase 2) touch the immovable core — explicit sign-off before the
  `PREREGISTERED_BAR` moves.

## 10. New skills introduced

- `/stress-test` — drive the scenario/stress lab (Phase 3).
- `/analyze` — orchestrate the parallel deep-analysis fan-out + summaries (Phase 4).
- (Phase 1 reuses `/manage-data` + `/add-data-source` + `/profile-source`; RL reuses `/run-gate`.)

## 11. Suggested sequencing

Phase 0 (substrate) → **Phase 1 (regime layer, highest leverage)** → Phase 2 (robustness gates)
→ Phase 3 (scenario lab) → Phase 4 (fan-out summaries) → Phase 5 (RL, fenced). Phases 3–5 can run
as parallel sub-agents (one branch each, merge train) once Phase 1 lands.

## 12. Multi-asset breadth (operator 2026-06-14: cosmu is NOT crypto-only)

Source: the BNP video names the desk's universe — **equities, FX, commodities, rates, credit**
(+ crypto). cosmu spans stocks (Alpaca; IBKR/IG wanted), futures (Kraken Futures; IBKR/IG wanted),
Polymarket, options (wanted), and crypto. The binding constraint, verified in code: the instrument
model (`spine/venue.py`) is only `Literal["crypto","equity","prediction"]` and `Instrument` carries
`tick_size/lot_size/min_notional` but **no contract multiplier, expiry, strike, option_type, or
trading session**. Several of the video's subtlest lessons are asset-class-specific and land here.

Phase 1 is **multi-asset by construction**: regime axes resolve per asset class (equity regime via
VIX/credit-spread/2s10s; crypto via DVOL/funding/OI; FX/rates via their own vol) PLUS one
**cross-asset correlation regime** spanning all classes (the correlation smile — "French PM resigns
→ CAC + OAT + EUR move together"). The context labels are market-wide and per-class.

New/refined items (each obeys the §1 alignment lock):

- **M1 — Extend the instrument/venue model beyond 3 classes** (ASK-FIRST: core model + likely DDL).
  Add asset classes (`futures`, `options`, `fx`) and derivatives fields to `Instrument`
  (`contract_multiplier`, `expiry`, `strike`, `option_type`) + a per-venue **trading session/calendar**.
  Unlocks futures/options/IBKR/IG; fixes the **multiplier fat-finger** ("process one = process 100")
  in `master/risk.py` sizing and the **clocks** ("don't price a closed market") for honest per-class
  freshness. (engine, opus)
- **M2 — Per-venue execution model: CLOB vs RFQ.** The cost model branches: CLOB = slippage/impact
  bps (today); RFQ = wide bid-ask + fill-probability + adverse-selection for options/structured/thin
  Polymarket. "Reveal myself" → don't telegraph size (iceberg/TWAP) on thin books. (engine, opus)
- **M3 — Options / vol lane on the block registry** (`strategy/blocks.py`). Trade vol, not direction:
  implied-vs-realized spread + term structure (VIX/DVOL/MOVE) as signals (the "it's red → markets
  stressed" tell); defined-risk payoff blocks (spread/collar/capital-protected = bond+call); a
  delta-hedge leg (cover options with futures); Polymarket as discrete-event insurance. Reframe:
  credit/options/Polymarket are **insurance markets** — cosmu can be insurer (premium/carry) or
  insured (tail hedge for a funded track). Routed through the SAME Gate. Seeds exist
  (`dvol-calm-regime-momentum.json`, `polymarket-positioning-risk-flip.json`). (engine, opus)
- **M4 — Fleet-level correlation-aware funding.** Wire `master/strategy_correlation.py` into
  funding/rotation as a diversification PREFERENCE (don't fund 10 secretly-identical bets — the
  desk's "we already have too much risk on those parameters"). Advisory; the Gate still gates,
  no pooled wallet. (engine, sonnet)
- **M5 — Negative-skew / short-gamma flag.** In the Phase-4 fan-out, lean on the scorer's existing
  skew/kurtosis PSR and flag `carry`/`mean-reversion`/premium-selling survivors ("short the put —
  no upside, only downside") for mandatory correlation-spike/tail scrutiny. (engine, sonnet)
- **M6 — Per-asset-class cost/notional normalization + the morning call.** Edge & cost in
  bps-of-notional per class with per-class funding/margin (futures margin vs cash equity vs spot);
  the Phase-4 fan-out emits a daily cross-asset **morning brief** (overnight crypto+Asia moves;
  day-ahead earnings/macro/unlocks/OPEX/Polymarket events; exposed tracks). (engine+config, sonnet)
- **M7 — Jurisdiction restrictions for new TradFi venues.** Populate `restricted_jurisdictions` /
  `live_legal_in` for IBKR/IG/Kalshi/options (Volcker → cosmu's "legality is one more venue fact").
  GB is already a supported jurisdiction for IG. (config, sonnet)
