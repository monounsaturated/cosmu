# Polymarket over-extension MAKER fade — HELD TO RESOLUTION — BRUT Gate test (2026-06-26)

**Scope:** EXPERIMENT ONLY. The single live edge thread the whole sprint found (the #400 intraday
over-extension fade), now run as a MAKER and **held to the authoritative UMA $1/$0 settlement** (#422),
judged BRUT through the production Gate. Zero production impact: offline, keyless, persists NOTHING to prod,
NO Gate constant touched, no cron, docs-only, no code merged into a runtime path. Output = this report + a
disposable HTML table (`docs/reports/polymarket-maker-gate-table-2026-06-26.html`, every one of 1310
over-extension events) + the harness (`apps/engine/scripts/research/polymarket_maker_gate.py`).

---

## The question this run answers (the one #401 explicitly deferred)

Three siblings led here:

| run | execution | exit | result |
|---|---|---|---|
| **#400** capstone | TAKER | K=6h intraday mark | GROSS reversion edge REAL (+0.70c/$1 pooled, DSR 1.0) but TAKER pays the spread → **net −2.86c**. Dead. |
| **#401** maker feasibility | MAKER | K=6h intraday mark | maker-net plausibly POSITIVE pooled (+1.68c expected) but FILL- & FEE-sensitive; **could NOT settle to resolution**. Verdict: "worth a small live test." |
| **#422** | — | — | the authoritative UMA resolution settlement now exists (`ExitRules.settle_at_resolution` → `data/backtest.py` settles a held position at the true $1/$0). |

**The #401 maker estimate exited at an arbitrary K-hour mark because it had no settlement.** Now it can
settle. This run asks the real question: **does the maker fade CLEAR the BRUT Gate, net of honest costs, when
the position is HELD TO RESOLUTION and settled at the true $1/$0 — instead of the intraday time-stop?**

This is a **different trade** from #400/#401, and a deliberately adversarial one. The intraday thesis was a
microstructure snap-back: open the fade, close it K hours later at the mid, flat well before resolution.
Holding to resolution is the **opposite horizon** — it is structurally H9 (the favorite-longshot hold that
DIED on the survivorship tail). If the intraday snap-back is a microstructure effect, holding all the way to
the binary outcome should **give it back**: the odds the fade shorted may simply have been *right* (they
converged to the eventual outcome). The real $1/$0 settles that. That is what we test.

---

## TL;DR verdict — KILL (does NOT clear the Gate honestly; the "pass" is longshot bias + the assumed spread credit)

**Clears the Gate? NO.** The expected/best scenarios show a nominal Gate PASS, but it is an artifact, and
**three independent disconfirmers kill it:**

| | geopolitics 0% (N=823) | sports 3% (N=487) | pooled (N=1310) |
|---|---:|---:|---:|
| GROSS taker→$1/$0 (held-to-resolution reversion) | +1.18c | +3.65c | +2.10c |
| **faded-WINNER vs faded-LOSER gross** | **−38.2c / +36.3c** | −30.1c / +31.5c | −35.3c / +34.5c |
| **No-credit floor** (fill-price structure, 0c credit), DSR | +1.72c, DSR **0.83** ✗ | −1.85c, DSR 0.17 ✗ | +0.51c, DSR 0.65 ✗ |
| Maker-net — worst | +3.28c, DSR 0.942 ✗ | −0.26c ✗ | +2.09c, DSR 0.908 ✗ |
| Maker-net — expected (nominal) | +4.15c, DSR 0.986 **"PASS"** | −0.39c ✗ | +2.63c, DSR 0.968 **"PASS"** |
| Maker-net — best | +4.45c, DSR 0.994 **"PASS"** | +2.63c, DSR 0.924 ✗ | +3.81c, DSR 0.998 **"PASS"** |
| **Outcome-shuffle null** p(null ≥ real) | **0.156** (1.09σ) | — | — |

### Why the nominal "PASS" is not real

1. **The decisive disconfirmer (#400's own disconfirmer-2) screams longshot bias.** Faded-winner gross is
   **−38.2c** and faded-loser gross is **+36.3c** (geopolitics). The held-to-resolution P&L is a near-perfect
   cancellation of two huge legs: shorting a YES that ends at $0 always wins ~entry_p; shorting a YES that
   ends at $1 always loses ~(1−entry_p). A **real reversion edge profits on BOTH legs** — this one only
   "works" because slightly more eventual-losers got faded than eventual-winners. The fade direction barely
   beats a coin flip at predicting the outcome: **short_yes wins (YES→$0) 54.1%**, **long_yes wins (YES→$1)
   51.5%** — both ≈ chance, at a mean entry of ~0.35.

2. **Strip the assumed maker credit and it FAILS the Gate.** The **no-credit floor** (maker P&L from the
   realized fill prices to settlement, spread credit set to **0c**, every fill kept) is geopolitics **+1.72c
   but DSR 0.83 — FAIL** (needs ≥0.95). The entire nominal "pass" is carried by the **assumed half-spread
   credit** (~1.5c at the 3c primary spread), not by any directional edge in the fade. The credit is exactly
   the thing the offline data cannot confirm — and #401's live prints already showed adverse selection is a
   real, strong force (P(BUY|price rose)=0.89).

3. **The edge is statistically indistinguishable from the outcome base-rate.** An **outcome-shuffle null** —
   randomly re-drawing each market's binary outcome at the same base rate (0.486) and recomputing the
   expected-scenario net 500× — produces a null mean of **+1.60c** from the credit + base-rate arithmetic
   ALONE. The real net (+3.68c on the geopolitics gross-fill+credit leg) sits just **1.09σ above this null
   (p=0.156)**: in ~16% of random-outcome universes the fade does as well or better. The fade's *direction*
   carries no real predictive power over the resolution.

4. **The DSR "pass" is a t-stat artifact of the binary-settlement variance.** Held-to-resolution P&L has a
   per-trade sd ≈ 0.45–0.48 (the ±$1/$0 swing). A tiny mean (~+0.04, ~80% of it the assumed credit) over
   that sd with n≈650 gives sharpe_per_obs ≈ 0.09 → t ≈ 2.3 → DSR ≈ 0.97. Because this is ONE pre-registered
   rule (`trials_counted=1`), the Deflated Sharpe applies no multiple-testing deflation — so a thin,
   credit-driven mean clears the 0.95 bar without there being a tradeable edge underneath. The DSR is doing
   its job (one honest trial); the **economics underneath are hollow**, which the no-credit floor and the
   outcome-shuffle null expose.

**Verdict: KILL the held-to-resolution variant.** Holding the maker fade to settlement **gives the intraday
gross edge back** (the +0.70c intraday gross collapses to a coin-flip on the binary outcome) and what little
positive net remains is the assumed spread credit riding on longshot bias and binary variance — not a real,
fill-confirmable edge. This is **not** a GO-live-test result. The #401 intraday-maker door
([[polymarket-maker-feasibility-2026-06-25]]) — gross edge real, maker-net plausibly positive across a
defensible band, settle-at-K-hours, geopolitics-only — **remains the only narrowly-open door**; holding to
resolution does not improve it and statistically nullifies it.

---

## Leakage tripwire (gated BEFORE any P&L)

The odds series AND the resolution settlement of every cell were run through
`research/prediction_tripwire.audit_prediction_cell` (the #422 prediction-lane gate) before any cell could
enter the gate population:

- **Cells audited: 337** (those with ≥96 hourly bars). **PASS 202 / FAIL 135.**
- Every one of the 135 failures was an **odds-series tripwire** failure (the shuffle-null / available-at /
  forward-shift triad on the YES-odds), NOT a resolution-PIT failure — the $1/$0 settlement points were
  uniformly PIT-honest (clean binary payout, available_at == the resolution ts, never earlier). The odds
  failures are expected: many resolved markets have short, sparse, or near-random-walk hourly series whose
  IC collapses into the shuffled band (correctly excluded — a "signal" indistinguishable from noise).
- **Only the 202 PASS cells (1310 events) entered the gate.** The tripwire did its job: the
  resolution-settlement join is PIT-clean, and noise-only odds cells were refused admission rather than
  blessed.

---

## The held-to-resolution decomposition (every number)

`maker net = gross(from the realized maker fill price → the true $1/$0 settlement) + half-spread credit −
category fee`, per $1 of YES notional. Settlement is **free** (no redemption fee, no slippage — exactly
`backtest.py:783`); the maker earns the credit on the **single** maker leg (the entry — the exit is the
chain settlement, not a maker fill).

### geopolitics (0% fee, N=823) — the only category that nominally passes
- fill mix fav/adv/nofill = **0.712 / 0.151 / 0.137**
- GROSS taker→$1/$0 = **+1.18c** (reverts to resolution, *barely*)
- **faded-winner / faded-loser gross = −38.2c / +36.3c** ← the longshot-bias fingerprint
- no-credit floor = **+1.72c, win 51.8%, DSR 0.831 → FAIL**
- worst = +3.28c (DSR 0.942, FAIL) · expected = **+4.15c (DSR 0.986, nominal PASS)** · best = +4.45c (DSR 0.994, nominal PASS)
- expected by spread: +3.15c @1c → +4.15c @3c → +5.15c @5c (credit rises with spread — passive economics)

### sports (3% fee, N=487) — fails everywhere except best-case fills
- fill mix = 0.659 / 0.088 / 0.253 (a much higher no-fill rate — sports books are thinner/faster)
- GROSS taker→$1/$0 = +3.65c (reverts) but faded-win/lose = −30.1c / +31.5c (same bias)
- no-credit floor = **−1.85c, DSR 0.166 → FAIL**
- worst = −0.26c · expected = **−0.39c (FAIL)** · best = +2.63c (DSR 0.924, still FAIL)
- the 3% round-trip fee eats the half-spread credit, exactly as it did for the taker (#400) and the
  intraday-maker (#401). Sports is dead in every defensible scenario.

### pooled (N=1310) — for completeness, NOT the verdict (BRUT judges per-category)
- GROSS taker→$1/$0 = +2.10c · faded-win/lose = −35.3c / +34.5c · no-credit floor +0.51c (DSR 0.65, FAIL)
- expected = +2.63c (DSR 0.968, nominal PASS) — same artifact; the pooled "pass" is the geopolitics leg.

---

## Why holding to resolution does NOT help (the economic intuition)

The #400 intraday edge was a **mean-reversion of an over-extended odds move within ~6 hours** — a
microstructure snap-back charged the spread. That edge is real on the *intraday* horizon. But the resolution
of a prediction market is the *terminal truth*, and a 3-hour odds spike carries almost no information about
the eventual $1/$0 outcome that the *current odds level* doesn't already price. So when you hold the fade to
settlement:

- the **intraday reversion P&L is replaced by the settlement P&L**, which is governed by whether the YES
  resolves to $1 or $0 — a near-coin-flip relative to the fade direction (54% / 51.5%);
- the per-trade variance explodes from the small intraday move (~1–3c) to the full ±settlement swing (~45c);
- the only systematic term left is the **favorite-longshot decomposition** (faded-loser legs pay, faded-winner
  legs cost), which a real edge must not depend on — and this one almost entirely does.

The maker credit (~1.5c) is then a thin, *assumed* sweetener on top of a coin flip. It is enough to tip a
DSR computed on n≈650 over the 0.95 line, but it is not an edge — it is the same H9 longshot trap wearing the
maker's clothes.

---

## What WOULD change the verdict (and what wouldn't)

- **Live maker fills would NOT rescue it.** Even granting perfect fills (the `best` scenario), geopolitics's
  edge is still the credit + longshot bias, and sports still fails. The live unknown (queue position, partial
  fills, own-size impact, adverse selection P=0.89 from #401) can only make the *realized* credit SMALLER
  than assumed — and the no-credit floor already fails. So the live-fill uncertainty cuts the wrong way here.
- **The intraday-maker door (#401) is unaffected** and remains the narrowly-open one: gross edge real,
  maker-net plausibly positive across a defensible band, geopolitics-only, *exit at K hours, never held to
  resolution*. If anything, this run sharpens why: the edge lives in the intraday snap-back, NOT in the
  terminal outcome, so a strategy that *closes intraday* is the only honest expression of it.

---

## KEY QUESTION answered

**Does the maker edge CLEAR the Gate net of honest costs WITH real resolution settlement?**
**NO.** With the authoritative $1/$0 settlement, the held-to-resolution maker fade:
- shows a nominal DSR PASS (geopolitics expected 0.986) that is a **binary-variance t-stat artifact**;
- **FAILS** the moment the assumed spread credit is removed (no-credit floor DSR 0.83);
- is **statistically indistinguishable from an outcome-shuffled null** (p=0.156, 1.09σ);
- is dominated by **favorite-longshot bias** (faded-winner −38c vs faded-loser +36c), the exact disconfirmer
  #400 pre-registered to catch this.

**GO-live-test / KILL: KILL** the held-to-resolution variant. The settlement join (#422) works and is
PIT-clean — it simply reveals that the intraday over-extension edge does **not** survive being held to the
binary outcome. The only door that stays ajar is the **intraday** maker test from #401, geopolitics-only,
closed at the K-hour mark, never held to resolution.

---

## Provenance / reproducibility

- **Endpoints (keyless, free):** `gamma-api.polymarket.com/events` (resolved-market discovery + tags +
  `outcomePrices` for the authoritative terminal_yes = the resolution payout + `createdAt`/`endDate`;
  `closed=false` for live two-sided books for the spread calibration),
  `clob.polymarket.com/prices-history` (windowed hourly odds, the #389 path).
- **Code reused BYTE-IDENTICAL:**
  `apps/engine/scripts/research/polymarket_intraday_overextension.py` (#400 — discovery, windowed hourly
  fetch, spread calibration, the BRUT `gate_stats` wrapper, the pre-registered (Z=2.5, lookback=48, H=3)
  rule, the FINAL_EXCLUDE_HOURS=48 convergence guard);
  `apps/engine/scripts/research/polymarket_maker_feasibility.py` (#401 — the maker fill classification
  FAVORABLE/ADVERSE/NO_FILL on the realized fill window, the worst/expected/best sensitivity band, the spread
  band); `cosmu/master/scorer.py` (BRUT DSR / min-trades, min_trades=30, min_deflated_sharpe_prob=0.95);
  `cosmu/research/prediction_tripwire.py` + `cosmu/research/leakage_tripwire.py` (the odds + resolution
  leakage gate); `cosmu/data/backtest.py` settle-at-resolution semantics (free settlement, no redemption fee,
  no slippage — `backtest.py:783`) expressed on the offline keyless path via each market's terminal_yes.
- **Harness:** `apps/engine/scripts/research/polymarket_maker_gate.py`. Re-run:
  `python3 apps/engine/scripts/research/polymarket_maker_gate.py --max-events 1200 --per-cat-budget 300
  --workers 12 --json-out /tmp/maker_gate_summary.json`. All numbers from a live run on 2026-06-26 (274.5s;
  600 resolved binaries sampled, 337 with an hourly series, **202 cleared the leakage tripwire**, **1310
  over-extension events**). The two extra disconfirmers (gross-fill gate, outcome-shuffle null) were run as a
  follow-up pass on the geopolitics leg with the same harness functions.
- **Disposable table:** `docs/reports/polymarket-maker-gate-table-2026-06-26.html` (every event, its fill
  classification, the $1/$0 settlement, the faded-winner flag, and the gross-to-resolution — per the
  surface-all-compute rule).
- **Zero production impact:** read-only keyless fetches; no DB writes, no `alt_data` rows, no cron, no Gate
  constant touched, no code merged into a runtime path. Docs-only.
