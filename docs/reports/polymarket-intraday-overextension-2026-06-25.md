# Polymarket INTRADAY over-extension fade — the capstone (2026-06-25)

**Scope:** EXPERIMENT ONLY — the CAPSTONE the whole edge batch points to. Zero production impact:
offline, keyless, persists NOTHING to prod, NO Gate constant touched, NO behaviour change, docs-only.
Output = this report + a disposable HTML table
(`docs/reports/polymarket-intraday-overextension-table-2026-06-25.html`, every one of 3134 trades) +
the harness (`apps/engine/scripts/research/polymarket_intraday_overextension.py`). Do NOT merge code
into a runtime path.

**Thesis (the actual live hypothesis):** H9 (hold-to-resolution longshot short) just DIED on the
survivorship tail and re-confirmed the project's standing read — the prediction-fade lane's *only*
plausible edge is **INTRADAY over-extension that reverts BEFORE resolution**, not hold-to-resolution.
The #389 trust experiment found hourly/minute Polymarket odds DO exist keyless via *windowed*
`startTs/endTs` `prices-history` requests (`fidelity=60`); the daily endpoint just doesn't surface them.
This tests the live hypothesis directly: when a market's odds **spike intraday** (over-extend on
flow/news), do they **mean-revert within hours — before resolution — enough to trade NET of fees AND
the wide CLOB bid/ask spread?**

---

## TL;DR verdict — KILL (gross edge is REAL; the spread eats it whole)

| | pooled (N=3134) | geopolitics (N=2545) | sports (N=589) |
|---|---:|---:|---:|
| **GROSS reversion edge** (per $1) | **+0.70c** | +0.49c | +1.62c |
| Reversion sign | **reverts** ✓ | reverts ✓ | reverts ✓ |
| Gross DSR (BRUT, prod scorer) | **1.0** | 1.000 | 1.0 |
| Gross Gate (min_trades 30, DSR≥0.95) | **PASS** | PASS | PASS |
| − spread (1c optimistic) → NET | **−0.86c** | −0.51c | −2.38c |
| − spread (**3c base**, empirical) → NET | **−2.86c** | −2.51c | −4.38c |
| − spread (5c conservative) → NET | **−4.86c** | −4.51c | −6.38c |
| Net DSR @ 3c (BRUT) | **0.0** | 0.0 | 4e-14 |
| Net Gate @ 3c | **FAIL** | FAIL | FAIL |
| Net win rate @ 3c | **9.1%** | 9.1% | 9.2% |

**The over-extension genuinely reverts** — the gross fade is positive on *both* categories and clears
the BRUT Gate cleanly (DSR = 1.0 on 3134 trades). **The spread then eats the entire edge and more.**
The empirically-calibrated round-trip spread (median 1c, mean 2.9c on N=1345 live two-sided books)
turns a +0.70c gross edge into −2.86c net; the win rate collapses from 44% gross to 9% net. **This is
the predicted "gross edge exists but spread eats it" KILL** — and it cleanly points at the only way in:
**maker-only / limit-order execution** (earn the spread instead of paying it), never marketable taker
round-trips.

---

## What was tested

**Data (keyless, free — the #389 windowed path):** for each resolved binary market we fetch the
**HOURLY** YES-odds via paged `CLOB /prices-history?market={YES_token}&startTs=..&endTs=..&fidelity=60`
windows across the market's whole life. (The `interval=max` call only ever returns *daily*; the windowed
`startTs/endTs` request is the only keyless route to hourly — confirmed live: 336 rows at 3600s spacing
in a 14-day window.) Universe = **resolved** geopolitics (0% fee) + sports (3% fee) markets, survivorship-
complete (every binary in each event, both YES- and NO-resolvers); **crypto (7.2%) EXCLUDED**. 600
markets discovered, **355 with a usable hourly series**, **3134 qualifying trades**.

**Signal — ONE pre-registered rule, NO sweep:**
- `move_t = p_t − p_{t−3h}` (the 3-hour odds change).
- `z_t` = rolling z-score of `move_t` over the trailing **48** hourly bars.
- Enter the **FADE** when `|z_t| ≥ 2.5` (a clear over-extension): an up-spike (`z>0`) → **SHORT YES**
  (bet it reverts down); a down-spike (`z<0`) → **LONG YES**.
- **Exit after 6 hours** (time stop), strictly intraday. Entry odds band `[0.05, 0.95]`.
- Non-overlapping per market (cooldown until the open trade closes).

**P&L per $1:** short YES = `entry_p − exit_p`; long YES = `exit_p − entry_p`. Net = gross − spread −
category fee.

---

## The three decisive disconfirmers

### (1) PIT — entry uses only odds up to the entry ts (fail-loud)
The z-score at bar *i* is computed from `bars[:i+1]` only; the exit bar (`i+K`) is in the future and the
signal never reads it. The harness `assert`s on **every trade**: `ts[i] == entry_t` (the newest signal
bar is the entry bar, never the future), `entry_t < exit_t`, and `exit_t < deadline` (the intraday
invariant). 3134 trades, **0 assertion failures** → no look-ahead.

### (2) NOT trend-toward-truth — controlled two ways, PASSES
The risk: the "over-extension" is really the odds *legitimately converging to the eventual outcome*, so
the fade is just shorting a side that's about to win/lose.
- **Final-window exclusion:** **no entry inside the last 48h before resolution** (where genuine
  convergence concentrates). Mean entry was ~2900h (geo) / ~1990h (sports) before the deadline — far
  from resolution.
- **Faded-winner vs faded-loser decomposition:** a real *reversion* edge must profit whether or not the
  side we faded eventually won. It does — the gross leg is **positive on BOTH** sub-populations:

  | | gross when we faded the eventual WINNER | gross when we faded the eventual LOSER |
  |---|---:|---:|
  | geopolitics | +0.12c | +0.86c |
  | sports | +0.61c | +2.41c |

  The faded-loser leg is larger (longshot bias is *part* of it), but the faded-winner leg is **still
  positive** — so this is genuine intraday mean-reversion, not pure "short the winner-about-to-lose."
  The disconfirmer passes: the gross signal is a real reversion, not a disguised convergence trade.

### (3) SPREAD HONESTY — the decisive cost, calibrated from live books
The historical `prices-history` series is the **midpoint** — the bid/ask is NOT in it (Roll spread ≈ 0
on the minute bars; serial covariance is *positive*, i.e. trend, not bounce). So the spread **must be
charged explicitly**, and on prediction markets it is **wide**. We calibrated it from the **real current
two-sided books on live open markets** (resolved markets have a degenerate post-resolution book ~0.001):

> N = **1345** genuinely-tradeable two-sided mid-band books — full spread: **p25 = 1c, median = 1c,
> mean = 2.9c, p75 = 3c, p90 = 7c**. (Most prediction markets are one-sided/illiquid — the median
> *across all* markets was 100c; we kept only books with `0 < bestAsk − bestBid < 0.20` and mid in
> `[0.05, 0.95]`, i.e. the only markets you could actually round-trip.)

A taker round-trip pays ~one full spread (cross on entry, cross on exit). We charge three levels —
**1c optimistic / 3c base / 5c conservative** — and report the full **GROSS → SPREAD → NET**
decomposition. The base 3c is the empirically-typical round-trip; even the 1c optimistic floor leaves
net negative.

---

## The decomposition (this is the whole result)

```
                         GROSS edge   − spread    − fee   =  NET
  pooled  (N=3134)        +0.70c       3.0c (base)  mixed    −2.86c   → KILL
  geopolitics (N=2545)    +0.49c       3.0c         0%       −2.51c   → KILL
  sports  (N=589)         +1.62c       3.0c         3%       −4.38c   → KILL
```

- **Gross edge is real and gate-clearing** (DSR 1.0, both categories positive, reversion sign correct,
  passes disconfirmers 1 & 2). The retail-over-reaction snap-back genuinely exists at the hourly scale.
- **It is ~0.5–1.6 cents per $1** — and a taker round-trip on the *most liquid* prediction-market books
  costs ~1–3 cents. The cost is **2–6× the edge.** There is no realistic taker spread at which this is
  net-positive: even the optimistic 1c floor leaves −0.86c pooled.
- **The win rate tells the same story bluntly:** 44% of gross fades reverted enough to profit; after a
  3c round-trip only **9%** clear. The edge is real but smaller than the toll booth.

---

## Verdict & what it points at

**KILL** as a taker strategy — a clean, honest KILL of the "gross edge exists but spread eats it"
shape, on a robust N=3134 brut sample. This is a *valuable* negative: it confirms the standing read
(intraday over-extension is the prediction-fade lane's only real signal) **and** pins down precisely why
it isn't tradeable as designed (the wide CLOB spread, not the signal).

**The one door it leaves open: maker-only / limit-order execution.** The entire loss is the spread we
*pay* as a taker. A fade expressed as **resting limit orders** that get filled by the over-reacting flow
(earning the half-spread instead of crossing it) flips the sign of the dominant cost term: gross +0.70c
+ ~+1.5c earned spread, minus fees, could plausibly be net-positive — but that requires modelling fill
probability and adverse selection on a passive book, which the keyless midpoint history cannot support.
That is the only follow-up worth running, and it is a **different experiment** (execution microstructure,
not signal discovery). As a marketable/taker fade, the lane is dead.

**Sibling consistency:** H9 died on the resolution tail; this — its intraday sibling — finds the signal
is real but spread-murdered. Both point the same way: **do not fund a taker prediction-fade.** The
prediction-market lane only re-opens with a passive-execution (maker) study.

---

## Provenance / reproducibility

- **Endpoints:** `gamma-api.polymarket.com/events` (resolved-market discovery + tags + `outcomePrices` +
  `createdAt`/`endDate`), `gamma-api.polymarket.com/events?closed=false` (live `bestBid`/`bestAsk` for
  the spread calibration), `clob.polymarket.com/prices-history` (windowed hourly odds). Keyless, free.
- **Code read:** `cosmu/ingest/polymarket_odds.py` (the windowed path is the natural extension of its
  `fidelity=1440` daily fetch), `cosmu/data/sources/polymarket.py` (`PerMarketOddsSource`,
  `PolymarketClobSource`), `cosmu/master/scorer.py` (the BRUT DSR / min-trades reused byte-identical),
  `scripts/research/h9_polymarket_thetadecay.py` (keyless fetch + Gate plumbing template),
  `docs/reports/polymarket-trust-experiment-2026-06-25.md` (#389 — the hourly windowed-path finding).
- **Harness:** `apps/engine/scripts/research/polymarket_intraday_overextension.py`. Re-run:
  `python3 apps/engine/scripts/research/polymarket_intraday_overextension.py --max-events 1200
  --per-cat-budget 300 --workers 12`. All numbers above are from a live run on 2026-06-25 (141.9s).
- **Disposable table:** `docs/reports/polymarket-intraday-overextension-table-2026-06-25.html` (every
  one of the 3134 trades, per the "surface all compute" rule).
- **Pre-registered rule (no sweep):** move horizon 3h · z-lookback 48h · z-entry 2.5σ · exit 6h ·
  final-exclude 48h · entry band [0.05, 0.95]. Spread levels 1c/3c/5c, primary 3c.
- **Zero production impact:** read-only fetches; no DB writes, no `alt_data` rows, no cron, no Gate
  constant touched, no code merged into a runtime path. Docs-only.
