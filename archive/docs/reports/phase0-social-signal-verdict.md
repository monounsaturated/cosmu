# Phase-0 Social-Signal Cohort Gate Verdict (P0.8)

> **Does crowd/social attention carry a tradeable edge?** Now that the LunarCrush social history is
> backfilled (186k point-in-time points, 30 symbols), the five social-signal specs queued in
> `strategies/inbox/` can finally face the deterministic Gate. This report routes the family through
> the EXISTING Gate as ONE COHORT (so the multiple-testing correction applies across the family, not
> per-spec) and records the honest result. **No threshold was changed; no PASS was manufactured.**

Status legend: **PASS** · **FAIL** · **INSUFFICIENT-DATA**.

**VERDICT: FAIL** — no spec survived the cohort Gate + BH-FDR (q = 0.10). Every spec is killed by the
per-candidate stats gate (deflated-Sharpe well below 0.95 **and** a negative untouched-holdout
Sharpe) *before* the cohort FDR is even binding. See §3.

---

## 1. Criteria (the existing, untouched Gate)

The Gate's statistical thresholds are the existing `GateSettings` / scorer —
`min_trades=30`, `min_deflated_sharpe_prob=0.95`, `max_pbo=0.50`, `max_drawdown=0.25`,
`min_folds_positive_pct=0.60`, `holdout_min_deflated_sharpe>0` — **and** the cohort BH-FDR at
**q = 0.10** (`cosmu/master/cohort.py:promote_cohort` + `cosmu/master/fdr.py`). **None changed.**

### PASS — per spec, ALL must hold (and it must survive the cohort FDR)
1. **Deflated Sharpe ≥ 0.95** net of all cost, against the trial-inflated benchmark.
2. **CSCV-PBO < 0.50** and **≥ 60% positive folds**.
3. **Untouched-holdout deflated Sharpe > 0** (out-of-sample, not in the fitting slice).
4. **maxDD ≤ 0.25**, **≥ 30 trades**.
5. **Survives cohort BH-FDR at q = 0.10** — judged together with the whole family, not alone.

### KILL (FAIL)
- No spec clears (1)–(4) after an honest, fully-powered run, OR every spec is rejected by FDR.

### The cohort (existing scorer/FDR — no threshold changes)
- `galaxy-score-momentum-breakout.json` — LONG: ride momentum only while LunarCrush **Galaxy Score**
  (composite 0–100 health rank) is above a fitted floor; exit when it rolls over.
- `social-sentiment-divergence-contrarian.json` — LONG: buy when crowd **sentiment** is positive while
  recent price return is still negative (a sentiment-leads-price divergence) inside a non-crashing trend.
- `social-volume-collapse-exit-filter.json` — LONG: momentum entry that **exits when social volume
  collapses** (the engaged-buyer pool drains).
- `social-volume-spike-flat-price-entry.json` — LONG: enter when **social volume spikes while price is
  flat** (attention not yet priced).
- `cross-asset-social-rotation.json` — LONG: rotate into the assets the crowd is currently focused on
  (high cross-sectional momentum rank **and** high social volume).

---

## 2. Run — 2026-06-05 (REAL data, the binding verdict)

Run via the new deterministic harness `cosmu/research/social_signal_cohort.py`
(`cd apps/engine && python3 -m cosmu.research.social_signal_cohort`), offline on **cached real
Binance daily bars + the backfilled LunarCrush social JSONL store** + PIT taker fees. For each spec
the harness builds the spec's coarse Finder GRID (`lab.finder.build_grid`, ≤ 64 variants), screens
every variant on the real bars/social/fees, **records each variant as a trial** (so deflation/FDR see
the true count), takes the gate-best variant, computes a gross (zero-cost) run for `cost_ratio`, and
routes the five gate-best representatives through `promote_cohort(..., fdr_q=0.10, register=False,
trials=trial_stats(store))` — **one cohort, BH-FDR across the family**. Deterministic; zero LLM.
Mirrors the funding-crowding harness exactly, social features in place of funding.

**Data source:** `live-cached` (real Binance bars + real LunarCrush social). **NOT synthetic.**
**Traded window:** `2023-09-10 .. 2026-06-05` (~1000 daily bars/symbol), clipped to where social
history exists (social itself reaches back to 2020-01; the bar cache is the binding limit).
**Regimes in window** (bar-labels summed across the universe): **chop 6995 · bull 10533 · bear 12421**
— all three present. **Social depth:** 30/30 universe symbols carry social history — **186,430 PIT
points** (2,348 per symbol × 3 metrics: social_volume, social_sentiment, galaxy_score). Point-in-time:
each daily social bucket carries `available_at = ts + 1 day`, joined to bars via `align_asof` (a bar
only ever sees social published on or before its close — no look-ahead). The deepest spec trades
**2,731** times — fully powered, no INSUFFICIENT-DATA abstention.

| Spec | net ret | gross | cost_ratio | deflated-Sharpe | gate-PBO | folds+ | holdout-DSR | regimes+ | trades | maxDD | skew | gate | FDR |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| galaxy-score-momentum-breakout | +5.18% | +6.15% | 0.84 | **0.636** | 0.518 | 0.50 | −0.478 | 1 | 1037 | 0.128 | +2.74 | STOP | ✗ |
| social-sentiment-divergence-contrarian | +1.09% | +1.43% | 0.76 | 0.044 | 0.438 | 0.54 | −0.500 | 2 | 532 | 0.067 | +1.38 | STOP | ✗ |
| social-volume-collapse-exit-filter | +15.36% | +17.58% | 0.87 | 0.512 | 0.528 | 0.68 | −0.500 | 1 | 1940 | 0.183 | +1.64 | STOP | ✗ |
| social-volume-spike-flat-price-entry | +0.52% | +2.11% | 0.25 | 0.020 | 0.472 | 0.49 | −0.496 | 1 | 2200 | 0.092 | +1.59 | STOP | ✗ |
| cross-asset-social-rotation | +5.38% | +7.80% | 0.69 | 0.044 | 0.526 | 0.53 | −0.465 | 1 | 2731 | 0.115 | +1.84 | STOP | ✗ |

**Cohort BH-FDR (q = 0.10):** DSR→p-values `[0.364, 0.956, 0.488, 0.980, 0.956]`; **no spec survives.**
Even the best (galaxy-score, p = 0.364) is far above any BH cutoff and above an *uncorrected* 0.05. The
FDR step is therefore **not the binding constraint** — every spec already fails the per-candidate gate.

---

## 3. Reading the verdict (against the untouched criteria)

- **Untouched holdout ✗ — the decisive, universal kill.** Every spec's out-of-sample holdout slice
  has a **negative** deflated Sharpe (−0.47 … −0.50). Whatever in-fit return the table shows, the
  signals **lose money on data the fit never saw.** This alone fails all five.
- **Deflated Sharpe ✗ (the other binding failure).** Best is galaxy-score at **0.636**, then
  collapse-filter 0.512; the other three sit at **0.02–0.04** — all far below the **0.95** bar. With
  ~1000 days × 30 symbols and 532–2731 trades, the test has ample power: there is **no statistically
  significant net edge** against the trial-inflated benchmark.
- **CSCV-PBO** — 3/5 (galaxy 0.518, collapse 0.528, rotation 0.526) sit just over the 0.50 overfit
  line; the other two are under. Moot given the DSR/holdout failures, but consistent with "fitting
  noise," not edge.
- **Positive folds** — only collapse-filter (0.68) clears the 0.60 bar; the rest are ~0.49–0.54
  (a coin-flip across folds — the hallmark of no persistent signal).
- **cost_ratio** — healthy (0.69–0.87) for four specs, so **fees are not the killer** there; the lone
  exception is `social-volume-spike-flat-price-entry` at **0.25** — it over-trades (2200 entries) and
  bleeds 75% of a tiny gross to costs (DSR 0.020), the classic over-trading-an-absent-edge signature.
- **tail/skew ✓** — all skews positive, maxDD ≤ 0.183 (under the 0.25 bar). The failure is **absence
  of edge**, not blow-up risk.

**No false positive to chase.** The highest DSR anywhere is 0.636 — below 0.95 even *before* FDR — so
there is no survivor and no near-miss to re-audit for look-ahead.

---

## 4. Honest caveat — 4 of the 5 specs did not actually test their social signal

A material finding that does **not** change the FAIL verdict but reframes what was tested. The specs
were authored against an **assumed feature scale** that the live LunarCrush feed does not use. Because
the instruction was "no threshold changes," the specs were run **exactly as written** — the
consequence is recorded here rather than silently patched:

| Feature | Real LunarCrush range (this data) | Spec's fitted floor | Binds? |
|---|---|---|---|
| `social_volume` | ~1.3M → 207M (grew ~160× over 2020–26) | `sv_floor` 8k–60k, `sv_exit` 3k–20k | **No — always-true** |
| `social_sentiment` | 31 → 64 (0–100 scale) | `sent_floor` 0.15–0.5, `sent_exit` 0–0.2 | **No — always-true** |
| `galaxy_score` | 0–100 (e.g. 62) | `gs_floor` 55–80, `gs_exit` 40–65 | **Yes — genuinely gates** |

So `social-volume-spike`, `social-volume-collapse`, and the volume leg of `cross-asset-social-rotation`
reduce to **price-momentum + (rotation) xsec-rank** rules with a no-op social filter — confirmed by
their always-on trade counts (1940–2731). `social-sentiment-divergence` reduces to a **price-reversion**
rule. Only **`galaxy-score-momentum-breakout`** truly gates on its social feature (Galaxy Score is
natively 0–100, matching the floor) — and it is the top DSR (0.636) yet **still fails.**

**Bottom line:** the one spec that honestly tested a LunarCrush signal failed the Gate; the other four
failed *and* never bound their nominal signal. There is **no exploitable social-attention edge** in this
cohort after costs. A genuine retest of the volume/sentiment theses would require re-fitting the param
ranges to the realized feature scale (or normalizing the features) and re-running the cohort — a new,
pre-registered attempt, not a threshold tweak to this one.

---

## 5. Reproduce

```bash
cd apps/engine
python3 -m cosmu.research.social_signal_cohort
```

Requires the cached real Binance daily bars (`.cosmu/market_data/binance/*_1d.json`) and the
backfilled LunarCrush social store (`.cosmu/altdata/lunarcrush_*_{social_volume,social_sentiment,galaxy_score}.jsonl`).
Deterministic for a fixed cache; zero network, zero LLM. The Gate thresholds and the cohort q = 0.10
are the existing, untouched values.
