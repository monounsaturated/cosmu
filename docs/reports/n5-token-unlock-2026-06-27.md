# N5 — Token-unlock supply-shock drift (2026-06-27)

**Scope:** EXPERIMENT ONLY — the slate's #2 pick, run after [N1 (UMA pre-settlement)](n1-uma-presettlement-2026-06-27.md)
was killed. From [edge-hypothesis slate v2](edge-hypothesis-slate-v2-2026-06-26.md). Zero production impact:
keyless, persists NOTHING to prod, NO Gate constant touched, NO behaviour change, docs-only. Output = this report
+ a disposable HTML table (`docs/reports/n5-token-unlock-table-2026-06-27.html`) + the harness
(`apps/engine/scripts/research/n5_token_unlock.py`, with an offline `--selftest`). Do NOT merge code into a
runtime path.

**Thesis (N5):** large SCHEDULED vesting **unlocks** are a pre-announced, dated supply shock. The cliff date is
fixed at TGE and public months ahead, yet small/mid-cap tokens are claimed to drift **down into** a large unlock
(sellers front-run the new supply) and **relieve after** (overhang cleared). Retail holds through the cliff;
informed flow positions early. Classic forced-flow with a fixed, **leak-proof** PIT date — the cleanest PIT story
in the batch (`available_at` of the event is *years* before the event). The only honest failure mode is that the
"drift" is just the tokens' own beta/vol — which is exactly what the **placebo-date null** is built to catch.

---

## TL;DR verdict — KILL

| | value |
|---|---:|
| Protocols with a DefiLlama unlock schedule | 339 |
| …matched to a keyless tradeable token (Bybit/Binance/Kraken spot) | **165** |
| N total cliff events on tradeable tokens | 20,248 |
| **N LARGE unlock events (≥ 5% of circulating float, full ±5d window)** | **344** |
| N placebo windows (random non-unlock dates, same tokens, ≥30d from any unlock) | 489 |
| **Pre-drift** (−5d→0, into unlock): real vs placebo | **−1.66%** vs −0.99%, **p = 0.15** |
| **Post-drift** (0→+5d, "relief"): real vs placebo | **−3.52%** vs −1.42%, **p = 0.0008** |
| Full window (−5d→+5d): real vs placebo | −5.19% vs −2.42%, p = 0.001 |
| **Net spot-tradeable relief leg** (long, 0→+5d, 50bps round-trip) | **−4.02% / event**, t = −4.95, PSR≈0 |
| Short-into leg (gross, would need a perp) | +1.66% / event, but pre-drift p = 0.15 (= beta, not edge) |
| Magnitude dose-response (bigger unlock → bigger drift?) | **none** (upper-half ≈ lower-half) |

**One-line:** across **344 large unlocks on 165 tokens**, the only spot-tradeable leg (the post-cliff *long
relief*) is not a relief at all — it is **−4.0% per event** (t = −4.95, p≈0). Tokens keep falling *after* the
unlock, **more** than on random non-unlock dates (post-drift −3.52% real vs −1.42% placebo). The "sell into the
unlock" pre-drift (−1.66%) is statistically **indistinguishable** from a random date on the same token
(placebo −0.99%, p = 0.15) — i.e. it is the tokens' own bearish beta, not an unlock-specific edge. Bigger unlocks
do **not** drift more. **KILL** on the pre-registered net-of-fees criterion. No fall-through target is specified;
the next slate survivor is N11 (attention-acceleration breakout).

---

## What was pre-registered (BEFORE any result)

One rule, no sweep, declared in the slate kill-experiment and in the harness header:

1. **Event** := a discrete **cliff** unlock (`metadata.unlockEvents[].cliffAllocations`, `unlockType == "cliff"`)
   on a token that resolves to a keyless tradeable spot pair. Linear-only dates (a slow drip) are excluded.
2. **Magnitude** := `unlock_pct = cliff_tokens / circulating_just_before`, where `circulating_just_before` is the
   cumulative tokens-unlocked-to-date at the documentedData point **strictly before** the cliff (the float about
   to absorb the new supply). The genesis cliff (no prior float = no denominator) is excluded.
3. **LARGE unlock** := `unlock_pct ≥ 5%` of circulating float (slate-pre-registered threshold).
4. **Window** := close-to-close daily **log** returns at **h = −5 … +5 trading days** around the cliff day.
   `pre = ret[−5→0]`, `post = ret[0→+5]`, `full = ret[−5→+5]`. An event without a full ±5-bar window is dropped
   (never padded).
5. **Net of fees** := the only spot-tradeable leg (the slate notes spot can trade only the post-cliff *long
   relief*; the *short-into* leg needs a perp venue) charged a conservative **50 bps** round-trip
   (20 bps taker + 30 bps small-cap slippage).
6. **DECISIVE CONTROL — placebo-date null:** for each large-unlock token, draw 3 random **placebo** event-dates per
   large event, each ≥ **30 days** from *any* real unlock of that token, and run the identical window math. The
   placebo inherits the token's beta/vol; if the drift survives there, it is just that beta → KILL.
7. **Pre-registered GO needs ALL of:** (i) N_large ≥ 30; (ii) drift sign matches the thesis **and** beats the
   placebo band (p < 0.05) on the spot-tradeable post-relief leg; (iii) net of fees still > 0.

---

## Results (every number)

Full table (top large unlocks by magnitude, per-event pre/post/full):
[`docs/reports/n5-token-unlock-table-2026-06-27.html`](n5-token-unlock-table-2026-06-27.html).
Machine summary: `apps/engine/scripts/research/n5_token_unlock_results.json`.

### Drift — real vs placebo (mean daily-log-summed return)

| leg | real (N=344) | placebo (N=489) | placebo p | thesis says | observed |
|---|---:|---:|---:|---|---|
| pre (−5d → 0, into unlock) | **−1.66%** | −0.99% | **0.15** | down (front-run) | down, but = placebo (just beta) |
| post (0 → +5d, "relief") | **−3.52%** | −1.42% | **0.0008** | **up** (relief) | **DOWN, worse than placebo** |
| full (−5d → +5d) | −5.19% | −2.42% | 0.0012 | mixed | down throughout |

### The spot-tradeable leg (long the post-cliff relief), net of 50 bps

| metric | value |
|---|---:|
| mean net return / event | **−4.02%** |
| t-stat | −4.95 |
| Sharpe / event | −0.27 |
| PSR vs zero (production `probabilistic_sharpe`) | 2.4e-06 |

The leg the thesis says you can actually trade on spot is **significantly, strongly negative**. There is no relief
rally to harvest; tokens keep selling off after the cliff.

### Magnitude dose-response (the thesis: bigger shock → bigger drift)

| half (by unlock %) | %-of-float range | pre-drift | post-drift |
|---|---|---:|---:|
| lower half | 5.0% – 8.6% | −1.26% | −3.58% |
| upper half | 8.6% – 384% | −2.07% | −3.46% |

Pre-drift is marginally more negative for bigger unlocks, but post-drift is **flat** across the split — no clean
dose-response. The shock magnitude does not scale the (already adverse) outcome.

---

## Interpretation — why it dies

- **No relief, the opposite.** The spot-tradeable leg (long the post-cliff relief) is the cleanest test, and it is
  **−4.0% / event, t = −4.95**. Tokens do not bounce after the overhang clears; they keep falling — *more* than on
  random dates (post-drift −3.52% real vs −1.42% placebo, p = 0.0008). The relief half of the thesis is wrong in
  sign.
- **The "sell into it" pre-drift is just beta.** The into-the-unlock down-move (−1.66%) is **indistinguishable
  from a random date on the same token** (placebo −0.99%, **p = 0.15**). Small/mid-cap vesting-heavy tokens grind
  down regardless of the specific cliff date; the placebo control strips that out and the unlock-specific signal
  vanishes. The gross "short-into" leg (+1.66%) is this same beta, is tiny over 5 days, and needs a perp venue
  (funding + borrow) the spot lane does not have — it is not a real edge.
- **No dose-response.** Bigger unlocks do not drift more on the tradeable leg — the mechanism's central prediction
  (the bigger the shock, the bigger the move) does not hold.
- **PIT is clean (and irrelevant to the kill).** The unlock date is leak-proof by construction (set at TGE), so
  this is *not* a leakage death — it is a genuine-absence death. The signal that survives the placebo control is
  adverse, not favourable.

In the ledger's framing, the wall here is **genuine absence of an exploitable edge**, not cost or data-access:
the data was free and abundant (20k+ events, 344 large ones, 165 tokens), the PIT story was the cleanest in the
slate, and the placebo control was decisive. The forced-flow is real, but it is **already priced** (the calendar
*is* public months ahead — the moat thesis "nobody sizes it" does not hold; everybody who holds the token can see
the cliff), and what is left after the placebo is the tokens' own bearish drift.

---

## Verdict

**KILL.** Pre-registered criterion (ii)+(iii) fail: the spot-tradeable post-relief leg is significantly
**negative** (−4.0%/event, p≈0) and does not beat the placebo band in the favourable direction. N_large = 344 ≥ 30
(criterion i passes), so this is a real, well-powered KILL, not a thin-data non-event. Killed in one offline pass,
no prod impact.

*Zero production impact. No Gate constant touched, no money path written, no source ingested. To promote any
remaining slate survivor (next up: N11 attention-acceleration), run its <1-day offline kill experiment first;
only a passing offline study earns a typed spec through the locked BRUT Gate.*
