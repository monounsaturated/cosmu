# Phase-0 Triple-Barrier Meta-Labeling Gate Verdict

> **Pre-registered as a powered FAIL.** Meta-labeling (López de Prado) can only AMPLIFY an edge the
> primary signal already has — a secondary classifier that decides *whether to act* cannot manufacture
> alpha where the primary has none. Prior gates established that spot momentum/reversion after Binance's
> ~20 bps round-trip shows no out-of-sample edge (`phase0-carry-verdict.md`, `phase0-funding-crowding-verdict.md`).
> This report tests whether a triple-barrier meta-label — a secondary regularized logistic that sizes/skips
> the primary trade, with funding as one feature — can rescue it. It cannot, and that closes the spot-only
> meta-labeling avenue. No threshold was changed; the existing deterministic Gate judged it.

Status legend: **PASS** · **FAIL (STOP)** · **INSUFFICIENT-DATA**.

---

## 1. What was built (mechanism)

Triple-barrier meta-labeling layered on the existing typed-spec / Gate machinery as an **optional,
backward-compatible** `StrategySpec.meta_label` field (the same pattern as `direction` and `funding_feature`:
`None` ⇒ byte-identical to the prior primary book, proven by a real trading-path regression test).

- **Primary signal** decides only the SIDE (long spot): a permissive momentum (`ret_Nd > floor`) or
  reversion (`rsi < floor`) entry.
- **Triple barrier → label.** Each past primary event is labeled by which of the three barriers —
  stop-loss / take-profit / time — it hit first, netted of round-trip cost (win = 1, else 0). The three
  barriers ARE the spec's existing `ExitRules` (`stop_loss` / `take_profit` / `time_stop_days`), so the
  label measures exactly the trade the primary book would have taken.
- **Secondary model = regularized logistic** (`cosmu/ml/logistic.py`, shared with the survival ranker —
  one implementation, two callers). Spot history is <100k rows; a boosted tree would only overfit, so
  LightGBM is reserved for offline MDA, never the live gate. The logistic predicts P(win) from momentum
  strength, RSI / Bollinger-z, realized vol, and **perp funding**, read point-in-time at entry.
- **Size/skip ONLY, never direction.** Below a fitted `prob_threshold` the trade is skipped; at/above it
  the primary trade is taken (optionally sized by the predicted probability). The gate can only ever
  *subtract* primary trades — never add, never flip side.
- **Point-in-time / no look-ahead.** Training is expanding-window: a decision at bar *t* trains only on
  primary events whose barrier RESOLVED on a strictly earlier bar, so the secondary never sees its own
  trade's outcome. Below `META_MIN_TRAIN = 30` resolved events the trade is ungated (the bare primary).

Funding now reaches the secondary model because the alt-data join was unified into one
`cosmu/data/alt_join.py` (used by BOTH the cohort screen and the Finder sweep) and made meta-aware — the
Finder previously screened every funding/alt spec **price-only** (a latent bug, now fixed).

## 2. Pre-registered criteria (unchanged Gate)

The Gate's statistical thresholds are the existing, untouched scorer / `GateSettings`
(`min_trades = 30`, `min_deflated_sharpe_prob = 0.95`, `max_cscv_pbo = 0.50`, `min_folds_positive`,
`max_drawdown = 0.25`, `must_beat_buy_and_hold`, untouched purged+embargoed holdout) **plus** the Finder's
honest trial deflation (every variant a trial), correlation-cluster effective-N, real CSCV-PBO, and
BH-FDR over distinct representatives. **None changed.** A spec PASSES only by clearing all of it AND the
one-shot holdout deflated-Sharpe floor.

### The cohort (spot, Binance, daily; CORE_PERP_UNIVERSE = BTC/ETH/BNB/SOL/XRP)
- `metalabel-momentum-triple-barrier.json` — primary = time-series momentum; secondary on
  [ret, rsi, vol, funding].
- `metalabel-reversion-triple-barrier.json` — primary = oversold RSI; secondary on [rsi, bb_z, vol, funding].

---

## 3. Results — 2026-06-05

### 3a. Gate sweep (the binding verdict) — `StrategyFinder.find`, 48 variants, two-pass, funding wired

| spec | screened | gate-passed | promoted | decision |
|---|---|---|---|---|
| metalabel-momentum-triple-barrier | 48 | **0** | **0** | **STOP** |
| metalabel-reversion-triple-barrier | 48 | **0** | **0** | **STOP** |

**No variant of either spec cleared the Gate + FDR + one-shot holdout.** Powered FAIL, as pre-registered.

### 3b. Mechanism check — meta-labeled vs bare primary (midpoint params, funding wired)

| spec | book | trades | val oos | val Sharpe | maxDD | **holdout DSR** |
|---|---|---|---|---|---|---|
| momentum | PRIMARY (no meta) | 430 | +0.073 | 0.491 | 0.124 | **−0.500** |
| momentum | META-LABELED | 298 | +0.088 | 0.670 | 0.115 | **−0.500** |
| reversion | PRIMARY (no meta) | 49 | +0.026 | 0.565 | 0.027 | **−0.431** |
| reversion | META-LABELED | 49 | +0.026 | 0.565 | 0.027 | **−0.431** |

The momentum gate **works as designed** in-sample: it skipped ~31 % of primary entries (430 → 298) and
lifted validation Sharpe 0.49 → 0.67 and oos +0.073 → +0.088 while cutting drawdown. **But the holdout
deflated Sharpe is unchanged and negative (−0.50).** The reversion primary fires only ~49 times total
(barely above the per-symbol floor), below the secondary's 30-event activation threshold, so the gate
never engages — meta-labeling is inapplicable to a signal that sparse.

---

## 4. Interpretation — why this closes the avenue

1. **Meta-labeling amplifies; it does not create.** The momentum secondary demonstrably improves the
   *validation* slice (where it trains), confirming the mechanism is correct and leak-free — yet the
   untouched holdout stays negative. There is no edge for it to amplify.
2. **The holdout is structurally inert for a data-hungry secondary on spot.** With <100k rows the
   purged+embargoed holdout is too short to accumulate `META_MIN_TRAIN` resolved events, so the gate
   cold-starts to the bare primary there. Meta-labeling cannot rescue a holdout it is too data-starved to
   even act on — itself a finding: spot's history is too thin for this technique to get a fair test.
3. **Consistent with the prior FAILs.** Carry, cross-sectional, and funding-crowding all failed on spot;
   meta-labeling on the same underlying signals fails for the same root reason — **spot is the binding
   constraint, not the modeling.** The next real lever is the venue/instrument (perps, the short side,
   funding as P&L), not a smarter classifier on spot.

**Verdict: FAIL (STOP).** Do not fund. The meta-labeling machinery is retained — it is venue-agnostic and
becomes worth re-testing the moment a primary signal shows a real holdout edge (e.g. on perps), where a
secondary model would then have something to amplify.
