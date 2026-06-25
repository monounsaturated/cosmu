# Polymarket intraday over-extension — MAKER execution feasibility (2026-06-25)

**Scope:** EXPERIMENT ONLY — a FEASIBILITY study of the single live edge thread the whole sprint found.
Zero production impact: offline, keyless, persists NOTHING to prod, NO Gate constant touched, docs-only,
no code merged into a runtime path. Output = this report + a disposable HTML table
(`docs/reports/polymarket-maker-feasibility-table-2026-06-25.html`, every one of 3055 over-extension
events) + the harness (`apps/engine/scripts/research/polymarket_maker_feasibility.py`).

**The question.** The capstone (#400, on main:
`docs/reports/polymarket-intraday-overextension-2026-06-25.md`) found the intraday over-extension
reversion **GROSS edge is REAL** (+0.70c/$1 pooled, +1.62c sports, clears the BRUT Gate DSR=1.0, all
disconfirmers pass) but a **TAKER round-trip** pays the wide CLOB spread (median 1c / mean 2.9c / p75 3c,
from 1345 live two-sided books) → net **−2.86c/$1**, the cost 2–6× the edge. The only door left open:
earn the half-spread as a **MAKER** (resting limit orders) instead of crossing it. This study bounds that
door honestly.

---

## HONESTY MANDATE (read this before the numbers)

You **cannot** perfectly backtest maker fills offline. The keyless data has **no order-book
queue-position history** and **no per-order fill log** — so there is no way to know, for a resting order
at a past instant, whether it would have actually been filled, where in the queue it sat, or whether our
own size would have moved the thin book. **This is therefore NOT a fill backtest and NOT a maker Sharpe.**
It is a **feasibility characterization** that (1) bounds the maker opportunity from the *realized hourly
path* of each #400 event, (2) decomposes an honest maker-net estimate with an explicit best/expected/worst
sensitivity band, (3) states plainly what is unknowable offline, and (4) sanity-checks the spread and the
adverse-selection mechanism against the **live keyless order book + real trade prints**. Every assumption
below is stated and swept; the verdict is calibrated to that uncertainty, not asserted past it.

---

## TL;DR verdict — WORTH a small live/forward maker test (gross edge real; maker-net plausibly positive, but only live fills can confirm it)

| | pooled (N=3055) | geopolitics 0% (N=2481) | sports 3% (N=574) |
|---|---:|---:|---:|
| GROSS reversion edge (per $1, reconciles #400) | **+0.68c** | +0.45c | +1.69c |
| Fill mix (favorable / adverse / no-fill) | 71% / 16% / 13% | 71% / 18% / 12% | 71% / 8% / 20% |
| **No-credit floor** (fill-price structure, **0c** spread credit) | **+0.16c** ✓ | +0.58c ✓ | −1.85c ✗ |
| Maker-net — **worst** fill assumptions | **+1.04c** ✓ | +1.46c ✓ | −1.09c ✗ |
| Maker-net — **expected** | **+1.68c** ✓ | +2.12c ✓ | −0.45c ✗ |
| Maker-net — **best** | **+3.05c** ✓ | +3.42c ✓ | +1.38c ✓ |
| Net DSR (BRUT prod scorer), expected | **1.0** PASS | 1.0 PASS | 0.05 FAIL |

**The half-spread flip works on paper, and it is not only the spread credit doing it.** Going passive
flips the sign of the dominant cost term: a taker *pays* ~one full spread (−2.86c net), a maker *earns*
roughly the half-spread back. Across the entire best/expected/worst band the **pooled** maker-net estimate
stays **positive** (+1.04c → +3.05c) and clears the BRUT Gate. Crucially, the **no-credit control** —
maker P&L from the realized fill prices with the spread credit stripped to **zero** — is **still +0.16c
pooled / +0.58c geopolitics**: the fill-price structure itself helps a little (adverse fills enter the
fade at a *deeper, better* over-extension level), so the result does not hinge entirely on assuming we
capture the spread.

**But the win is carried by geopolitics (0% fee), and it is fragile.** Sports (3% fee) is **net-negative
in worst and expected** and only positive under best-case fills — the 3% round-trip fee eats the entire
half-spread gain, exactly as for the taker. And the whole positive result rests on the one thing the
offline data **cannot** confirm: that a resting order actually *fills* the way the path-classification
assumes. The live trade prints confirm the adverse-selection *mechanism* is real (see below), which is a
reason for caution, not comfort.

**Verdict: WORTH a small live/forward maker test — geopolitics-only, 0% fee, mid-band, small size.** The
gross edge is real, the maker-net is plausibly positive across a defensible sensitivity band, and the
no-credit floor is positive — but the sign is *fee-sensitive and fill-sensitive*, and only a live passive
order log can settle whether the assumed fills materialize. This is **not** a fund-it result; it is a
"the one remaining door is genuinely ajar — go push on it with real resting orders, paper/forward, in the
0%-fee corner only."

---

## The adverse-selection core (the whole point)

A resting maker order earns the half-spread but **fills adversely**. To fade an UP-spike we post a resting
SELL-YES at/inside the touch. It gets **lifted by aggressive buyers** — i.e. it fills *preferentially when
the move continues up against us* (bad), and is *skipped when the price reverts down immediately* (the good
case we wanted, but never got positioned for). We classify each #400 over-extension event from its realized
hourly path in a short post-signal fill window (`FILL_WINDOW_H = 3` bars) into three buckets, then price
each from the **actual** subsequent path:

| class | what the realized path did | maker outcome | pooled share |
|---|---|---|---:|
| **FAVORABLE** | price lingered near/just past the spike (≤1 tick further), then reverted | resting order fills ~at the touch → earn gross reversion + half-spread | **71%** |
| **ADVERSE** | price ran *further* into the spike before reverting | order lifted at a worse level → earn half-spread but carry the continuation from the realized fill | **16%** |
| **NO-FILL** | price reverted immediately without trading back to our limit | **skipped — capture nothing** | **13%** |

### The two forces that decide the sign

The honest per-bucket gross (pooled, from the path) is the crux:

| bucket | gross signal→exit (taker view) | gross **fill→exit** (the maker actually earns) | mean over-run paid |
|---|---:|---:|---:|
| FAVORABLE | +0.42c | +0.42c (fills at the touch) | — |
| ADVERSE | **−1.62c** | **+1.86c** | +3.5c |
| NO-FILL | **+4.79c** (forfeited) | n/a (skipped) | — |

Two opposing forces, both real, both surfaced:

1. **The no-fill tax (against us).** The events a passive order *misses* are the **best taker trades** —
   the immediate reverters, **+4.79c gross each** pooled. Going passive forfeits exactly the trades the
   taker book most wanted. This is the survivorship cost of resting instead of crossing, and it is large
   (~7× the average edge). The model honestly excludes these from maker P&L entirely.

2. **The adverse-fill *entry-improvement* (for us).** When the price runs further before lifting our order,
   we fill at a *deeper* over-extension — a *better* fade entry. So even though the adverse bucket's
   signal→exit gross is −1.62c (the move continued), the gross measured **from the realized fill price to
   the later exit is +1.86c**: shorting the bigger spike still reverts on average. This is why the
   no-credit floor is positive: it is not the spread credit alone.

The expected maker-net (+1.68c pooled) is what survives after **both** forces plus the half-spread credit
and fees. The sign holds because the favorable bucket (71% of events) reverts modestly and earns the
credit, the adverse bucket enters at a better level, and the forfeited no-fills — while a real opportunity
cost — simply don't enter P&L (they neither help nor hurt the realized book; they only mean the maker
captures less *total* edge than the gross suggests).

---

## The sensitivity band (every assumption stated and swept)

Three explicit knobs, swept across worst / expected / best:

| knob | what it is | worst | expected | best |
|---|---|---:|---:|---:|
| **(A) half-spread earned** | maker credit = `hs_frac` × round-trip spread | 0.25× | 0.50× | 1.00× (passive both legs) |
| **(B) favorable fill rate** | fraction of FAVORABLE events that actually fill at the touch | 0.70 | 0.90 | 1.00 |
| **(B) adverse fill rate** | fraction of ADVERSE events that fill (rest = missed) | 1.00 (keep all) | 1.00 | 0.85 (skip some) |
| **(B) no-fill rescue** | fraction of NO-FILL reverters that *do* lift our order | 0.00 | 0.00 | 0.30 |
| **(C) adverse capture** | fraction of the realized over-run we get picked off at | 1.00 (full) | 1.00 | 0.50 |

The primary spread is the empirically-typical **3c round-trip** (median live spread 1c, mean 2.9c, p75 3c
— so the maker credit is ~half of that). The **spread sensitivity is inverted vs the taker**: a *wider*
spread means *more* maker credit, so the expected maker-net *rises* with spread (+0.68c @1c → +1.68c @3c →
+2.68c @5c pooled) — the opposite of the taker, where a wider spread killed it faster. This is the whole
economic point of going passive.

Pooled maker-net stays positive across the full band. Per-category, geopolitics is positive everywhere;
**sports turns negative in worst and expected** and is the fragile leg.

---

## Live realism check (keyless, real — grounds the model)

Three keyless endpoints, all confirmed reachable this run (the #389 discovery extended): Gamma
`/events`, CLOB `/book?token_id=` (full depth ladder), and **`data-api.polymarket.com/trades?market=`
(real BUY/SELL trade prints — newly confirmed keyless here; the authenticated `clob/trades` is 401)**.

- **Spread the maker posts into:** real two-sided books N=1353 — touch spread (cents) p25=1.0,
  median=1.0, mean=2.9, p75=3.0, p90=7.0. (Matches #400; confirms the 3c primary is honest.)
- **Touch depth:** median ~4108 shares at the touch (mean skewed to ~59k by a few deep books). A *small*
  resting order joins a real queue without being the whole book — but **queue position is unobservable
  offline** (see below).
- **The adverse-fill mechanism is real:** on real prints, **P(aggressor = BUY | price rose since the
  prior print) = 0.89** (n=2360), and P(SELL | price fell) = 0.56. Aggressive buying lifts the offer when
  price is rising — exactly the mechanism by which a resting SELL (our short-YES fade of an up-spike) gets
  filled *into* continued upward pressure. **This confirms adverse selection is a genuine force**, which
  is why the offline classification cannot be waved away and why a live test is required to size it.

---

## What is UNKNOWABLE offline (the live-test requirement)

The positive estimate above rests on assumptions the keyless midpoint history **cannot** validate. A live
/ forward maker test with a real resting-order log is the only way to settle:

1. **Exact queue position.** The CLOB is price-time-priority. The midpoint history shows *that* a price
   traded, never *whether our specific order at that price was reached in the queue*. A favorable-classified
   event may never fill if we sit behind existing size; an adverse one fills first. Offline this is assumed,
   not measured.
2. **Partial fills.** A resting order may fill in fragments at different times/levels; the path model treats
   each event as a single clean fill. Real partials change both the entry price and the held size.
3. **Own-size market impact.** Touch depth is real but finite; a non-trivial order *is* part of the book and
   can move the thin prediction-market price against itself. The model assumes price-taking-free passivity.
4. **Cancel / repost dynamics.** A real maker cancels and re-posts as the inside moves; whether you chase,
   how often, and the resulting realized fill price is a policy the offline path cannot simulate.
5. **The favorable/no-fill split itself.** The classification reads the realized path to label fills — but
   in life you post *before* knowing the path. The split (71/16/13) is a plausible *characterization* of
   how often each regime occurs, not a guarantee of which ones *you* catch.

A small live/forward test answers all five directly: post resting fade orders on geopolitics mid-band
markets, log every fill (price, time, partial, queue), and compare the realized maker-net to the +1.68c
expected estimate. That is the experiment this study points to — and the **only** thing that can convert
"plausibly positive" into "real."

---

## Verdict & what it points at

**WORTH a small live/forward maker test — geopolitics-only (0% fee), mid-band [0.05, 0.95], small size.**

- The **gross edge is real** and reconciles with #400 (+0.68c pooled here vs +0.70c there; same events).
- The **maker-net estimate is positive across the full worst/expected/best band pooled** (+1.04c →
  +3.05c) and clears the BRUT Gate (DSR 1.0). The **no-credit floor is positive** (+0.16c pooled / +0.58c
  geopolitics), so the result is not purely an artifact of assuming we earn the spread.
- **Fee-sensitivity is the dividing line.** Geopolitics (0%) is positive everywhere; **sports (3%) is
  net-negative in worst and expected** — the round-trip fee eats the half-spread gain just as it did for
  the taker. Any live test must start in the 0%-fee corner.
- **Fill-sensitivity is the residual risk.** The sign is plausible but rests on fills the offline data
  cannot confirm, and the live prints show adverse selection is a real, strong mechanism (P=0.89). This is
  why the verdict is "go test live small," **not** "fund it."

**This is the honest target:** *gross edge real, maker-net plausibly positive across a defensible band,
but only a live passive-order test can confirm the fills.* The prediction-fade lane — dead as a taker
(#400) — re-opens **narrowly** as a passive-execution forward experiment, scoped to the 0%-fee geopolitics
corner, never as a funded taker round-trip.

---

## Provenance / reproducibility

- **Endpoints (keyless, free):** `gamma-api.polymarket.com/events` (resolved-market discovery + tags +
  `outcomePrices` + `createdAt`/`endDate`; `closed=false` for the live `bestBid`/`bestAsk` + book sampling),
  `clob.polymarket.com/prices-history` (windowed hourly odds, the #389 path), `clob.polymarket.com/book`
  (real depth ladder), **`data-api.polymarket.com/trades`** (real BUY/SELL prints — confirmed keyless this
  run; the authenticated `clob/trades` returns 401).
- **Code read / reused:** `apps/engine/scripts/research/polymarket_intraday_overextension.py` (#400 — the
  over-extension events, windowed hourly fetch, spread calibration, and the BRUT scorer wrapper are
  imported and reused **byte-identical**), `cosmu/ingest/polymarket_odds.py` +
  `cosmu/data/sources/polymarket.py` (the CLOB endpoint contracts), `cosmu/master/scorer.py` (the BRUT
  DSR / min-trades, `min_trades=30`, `min_deflated_sharpe_prob=0.95`).
- **Harness:** `apps/engine/scripts/research/polymarket_maker_feasibility.py`. Re-run:
  `python3 apps/engine/scripts/research/polymarket_maker_feasibility.py --max-events 1200
  --per-cat-budget 300 --workers 12`. All numbers above are from a live run on 2026-06-25 (150.0s;
  600 resolved binaries discovered, 355 with an hourly series, **3055 over-extension events**).
- **Disposable table:** `docs/reports/polymarket-maker-feasibility-table-2026-06-25.html` (every event,
  its fill classification, realized fill/exit prices, and over-run, per the "surface all compute" rule).
- **Maker model (declared, no sweep on the signal — the #400 rule is inherited verbatim):** fill window 3h
  · favorable = run ≤ 1 tick · adverse = ran further then reverted · no-fill = reverted past entry before
  lifting our order · maker exit = K=6h from the fill bar · scenarios worst/expected/best as tabled ·
  spread credit = `hs_frac` × {1c/3c/5c}, primary 3c.
- **Zero production impact:** read-only fetches; no DB writes, no `alt_data` rows, no cron, no Gate constant
  touched, no code merged into a runtime path. Docs-only.
