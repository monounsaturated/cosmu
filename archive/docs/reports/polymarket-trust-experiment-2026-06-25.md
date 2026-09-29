# Polymarket odds — data-trust experiment (2026-06-25)

**Scope:** EXPERIMENT ONLY. Empirically test whether Polymarket odds are a *trustworthy research
data source* on **real fetched data**. Zero production impact — no prod wiring, no cron, no Gate
touch, no merge. Output is this one report.

**Method:** real keyless fetches against the public Gamma (`gamma-api.polymarket.com`) + CLOB
(`clob.polymarket.com`) endpoints — the same endpoints `cosmu/data/sources/polymarket.py` already
calls — on a handful of **resolved** macro/political markets (the class the flagship prediction-fade
spec `g2-prediction-prob-overextension-fade-short.json` targets). Then: PIT-honesty probes, the
**new leakage tripwire** (`cosmu/research/leakage_tripwire.py`, PR #387) on real odds-as-feature, and
a toy fade backtest. Script: `/tmp/pm_trust_experiment.py` (disposable; not committed).

> SSL note: the M2 needs `certifi` for these hosts — the repo's `cosmu.data.altdata._ssl_context()`
> already handles it; a bare `ssl.create_default_context()` fails `CERTIFICATE_VERIFY_FAILED`.

---

## TL;DR verdict

| Question | Finding |
|---|---|
| Coverage / depth | **GOOD.** 84–307 **daily** rows per resolved macro market, back to market launch (2024–2026). |
| Granularity | **Daily only on the current code path.** Hourly/minute exist but are unreachable as wired. |
| PIT honesty | **HONEST.** Buckets are real as-of (midnight = day's open), immutable, converge to outcome. |
| The PR #385 "available_at==ts = 1-bucket look-ahead" worry | **DOES NOT HOLD for the daily series** — the bucket is backward-honest (the open), not a forward aggregate. |
| Leakage tripwire on real odds | **FAIL on all 6 markets — but on `shuffle_null`, not look-ahead.** The available_at audit and forward-shift PASS everywhere; the odds level has no per-market next-day predictive IC distinguishable from noise. |
| Toy fade backtest | Tiny n, **all losing** trades — characterization only (no UMA join, no fees, no velocity arm). Consistent with "rich contracts mostly resolve YES" (favourite-longshot the *wrong* way for a naive fade). |

**Refined verdict on #385: REVIEW (lean GO on the data, NO-GO on the daily wiring).** The data source
is trustworthy and PIT-honest; the *daily granularity* is what starves the Gate, and it is a
**wiring** limit, not a data limit. Single highest-value next experiment: **re-run the fade at hourly
granularity via the windowed CLOB path** (below) — daily is too coarse to ever clear the Gate's
min-trades.

---

## Section 1 — Coverage / depth / granularity (real fetch)

Six resolved markets, top-volume, macro/political (the fade spec's universe):

| market | daily rows | span | resolved YES |
|---|---:|---|:---:|
| Will Donald Trump win the 2024 US Presidential Election? | 307 | 2024-01-05 → 2024-11-06 | 1 |
| Fed decreases interest rates by 50+ bps after Jan 2026 meeting? | 134 | 2025-09-18 → 2026-01-28 | 0 |
| Fed increases interest rates by 25+ bps after Dec? | 132 | 2025-08-01 → 2025-12-10 | 0 |
| US government shutdown Saturday? | 84 | 2025-11-14 → 2026-02-04 | 1 |
| Will Zohran Mamdani win the 2025 NYC mayoral election? | 197 | 2025-04-23 → 2025-11-05 | 1 |
| Will the Sacramento Kings win the 2025 NBA Finals? | 205 | 2024-09-25 → 2025-04-17 | 0 |

- **Depth is real and deep enough per market** — full daily history from each market's launch to
  resolution, free, no key, immutable midpoint quotes in `[0,1]`.
- **Coverage is back to 2024** for long-horizon markets (the Trump-2024 series is 307 daily points).

### The granularity wall (the real finding)

The current code (`PerMarketOddsSource.fetch_odds` and `PolymarketClobSource._market_history`) hardcodes
`fidelity=1440&interval=max`. Measured behaviour of that exact call vs alternatives, on the Trump-2024
YES token / shutdown market:

| call | rows | spacing |
|---|---:|---|
| `interval=max&fidelity=1440` (as wired) | 307 | **1 day** (86400s) |
| `interval=max&fidelity=60` | **0** | — (API refuses hourly on the full-history call) |
| `interval=max&fidelity=1` | **0** | — |
| `startTs/endTs` 14-day window, `fidelity=60` | **335** | **1 hour** (3600s) |
| `startTs/endTs` 14-day window, `fidelity=1` | **20158** | **1 minute** (60s) |

**Conclusion:** hourly and minute data fully exist on Polymarket's CLOB, but **only via explicit
`startTs`/`endTs` windowed requests** — `interval=max` caps total rows and silently returns *daily-or-
nothing*. So the orphaned ingest is structurally daily because of *how it queries*, not because the
data is coarse. This is exactly the #385 symptom ("fidelity=1440 → ~1 trade/market → Gate refuses"):
daily odds over a 3–10-day hold give a prediction-fade spec ~1 entry per market, far below the Gate's
min-trades. The fix is a windowed/paged fetch, not a new data source.

---

## Section 2 — PIT honesty (are the timestamps real as-of, or retroactively revised?)

Probed on the Fed-50bps market (134 daily rows). **Four independent checks, all pass:**

1. **As-of grid:** 134/134 daily buckets land exactly on **00:00 UTC**. Not arbitrary ingest moments —
   a real, regular as-of grid.
2. **Backward-honest bucket (the key one):** the daily `fidelity=1440` midnight bucket **equals the
   day's first hourly tick at 00:00 UTC, 10/10 days checked** (e.g. 2025-11-12 daily 0.0450 = hourly
   00:00 0.0450, … through 2025-11-21). So the daily point is the **price *as-of* midnight (the day's
   open)** — it is *not* a forward aggregate of the whole day. A value stamped at `ts` was genuinely
   knowable at `ts`.
3. **Immutable / revision-free:** re-fetching the full history twice, **0/134 shared timestamps
   differ.** Vendor never rewrites past buckets — the `append_dedup` ts-keyed idempotency assumption
   in `ingest/polymarket_odds.py` is sound.
4. **Tracks live belief → converges to outcome:** the Fed-50bps series ends at p=0.0005 and the market
   resolved **NO (YES=0)**; the Trump-2024 series ends near 1 and resolved YES=1. The odds are the
   real evolving market price, not a back-stamped constant.

### This refines the #385 look-ahead concern

PR #385 flagged `available_at == ts` as "a 1-bucket look-ahead." **Finding (2) shows that is not true
for the daily series:** because the midnight bucket is the day's *open*, joining it `available_at == ts`
to a daily trading bar aligns the odds-open to the bar-open — backward-honest, no peek. The genuine
residual risk to watch is only if a *coarser-than-daily* consumer or a *bar whose own timestamp
precedes midnight* were joined; on the day grid the odds source is PIT-clean. The leakage tripwire's
own `available_at_audit` confirms this empirically (Section 3, check [1] = 0 look-ahead on every
market).

---

## Section 3 — Leakage tripwire on REAL odds (its first real-data run)

Ran `audit_feature(points, bars, horizon=1)` from `cosmu/research/leakage_tripwire.py` (PR #387) on each
market, framing **the odds level as the feature against the odds-instrument's own next-day return** —
the honest framing for a contract whose *price is the odds* (the fade spec trades the contract itself).
200 shuffle trials, seed 7.

| market (cond) | n | real IC | [1] available_at | [2] shuffle-null | [3] forward-shift | verdict |
|---|---:|---:|:---:|:---:|:---:|:---:|
| Trump-2024 (dd22) | 306 | −0.0905 | PASS (0 LA) | **FAIL** p=0.124 | PASS | **FAIL** |
| Fed-50bps (1781) | 133 | −0.0675 | PASS (0 LA) | **FAIL** p=0.458 | PASS | **FAIL** |
| Fed-25bps (fcd2) | 131 | −0.1019 | PASS (0 LA) | **FAIL** p=0.269 | PASS | **FAIL** |
| Shutdown (43ec) | 83 | +0.0113 | PASS (0 LA) | **FAIL** p=0.920 | PASS | **FAIL** |
| Mamdani (ebdd) | 196 | −0.0385 | PASS (0 LA) | **FAIL** p=0.607 | PASS | **FAIL** |
| Kings-NBA (763c) | 204 | −0.0948 | PASS (0 LA) | **FAIL** p=0.204 | PASS | **FAIL** |

**Honest read of the tripwire's first real-data test:**

- **Check [1] available_at audit — PASS on all 6** (0 look-ahead, 0 wrong-winner). The PIT join on real
  odds is strictly backward-looking. This *confirms* Section 2: the data is leak-free as wired.
- **Check [3] forward-shift sanity — PASS on all 6.** Lagging the feature never beats the live read
  (the `-1 honest` IC is below or near the live IC; the `+1 cheat` is higher, the healthy direction).
  No baked-in peek.
- **Check [2] shuffle-null — FAIL on all 6.** The per-market odds level's next-day IC sits **inside**
  the time-shuffled noise band (p ranges 0.12–0.92, none < 0.05). The IC magnitudes (~0.04–0.10) are
  real but **indistinguishable from autocorrelation noise on a single ~100–300-point series**.

**Interpretation — this is the tripwire working correctly, not a leak.** The tripwire fails the odds
*as a standalone single-market predictive feature* because, per market, the odds level does **not**
carry a next-day edge that survives a shuffle. That is the right verdict: a lone market's odds-IC is
noise. It is **not** a look-ahead failure — checks [1] and [3], the actual leakage detectors, pass
cleanly. The honest conclusion is: **trust the data (PIT-clean), but do not trust a single market's
raw odds-IC as an edge.** A real fade edge, if it exists, must come from the *cross-sectional* pattern
(favourite-longshot across many markets) + the velocity-rollover timing arm — neither of which a per-
market shuffle-null on the level alone tests. The tripwire is doing exactly its job: it refuses to
bless a noisy single-series IC, and it cleanly clears the source of look-ahead.

> Caveat on the framing: scoring odds-as-feature against the odds-instrument's own return is a
> near-degenerate self-prediction (the "bars" *are* the feature path), so a high IC here would actually
> be the *suspicious* outcome. The shuffle-null FAIL (low, noisy IC) is the benign result. When the fade
> is properly backtested, the odds become an *entry signal* on the contract, scored against the
> contract's path to **resolution** — a different and fairer test (Section 4 sketches it).

---

## Section 4 — Toy prediction-fade backtest (characterization ONLY)

Toy model of `g2-prediction-prob-overextension-fade-short`: **short the contract the first day its odds
cross above `rich_level`, hold to resolution, P&L per $1 = entry − resolved_outcome.** This is a
characterization, **not** a real backtest — it lacks the proper per-bar UMA resolution join, CLOB fees,
depth/slippage, and the velocity-rollover entry arm. Numbers:

**rich_level = 0.70:**

| market | entry | resolved | P&L/$1 |
|---|---:|:---:|---:|
| Trump-2024 | short @ 0.705 (2024-07-16) | YES (1) | **−0.295** |
| Shutdown | short @ 0.795 (2026-01-25) | YES (1) | **−0.205** |
| Mamdani | short @ 0.727 (2025-06-26) | YES (1) | **−0.273** |
| Fed-50bps / Fed-25bps / Kings | never reached 0.70 | — | no trade |

**rich_level = 0.80:** Shutdown short @ 0.875 → YES → **−0.125**; Mamdani short @ 0.803 → YES →
**−0.197**; rest no trade.

**Every toy trade lost.** Each rich contract resolved YES — i.e. the favourite *won*. This directly hits
the spec's own **Disconfirmer 2** ("rich contracts can keep rising to resolution; if the edge is
dominated by resolution losses, the fade is on the wrong side of the longshot bias"). On this tiny,
biased, hold-to-resolution sample the naive level-fade is on the wrong side. **This is not evidence
against the spec** — a 5-symbol, no-velocity-arm, no-stop, hold-to-resolution toy cannot represent a
spec whose edge thesis is *intraday over-extension that mean-reverts before resolution* with a stop and
a velocity-rollover trigger. It only confirms: (a) the resolution outcomes join correctly (data is
usable for a real backtest), and (b) the naive "short anything rich and hold" strawman loses, which the
spec already anticipates.

---

## Refined GO / REVIEW / NO-GO on #385

**Overall: REVIEW.** Split:

- **Data trust → GO.** Polymarket odds via keyless CLOB/Gamma are **PIT-honest, immutable, deep, and
  resolution-true.** The leakage tripwire's look-ahead detectors ([1] available_at, [3] forward-shift)
  PASS on every real market. The available_at==ts daily stamp is backward-honest (the open), so the
  #385 "1-bucket look-ahead" worry is **resolved/void for the daily series**. Trust it as a research
  source.
- **Daily wiring → NO-GO (as-is).** The orphaned ingest is hardcoded to `fidelity=1440&interval=max`,
  which is **structurally daily** → ~1 trade/market → the Gate correctly refuses. Daily granularity
  will never feed a 3–10-day-hold fade spec enough trades. Do **not** wire the daily path to the Gate.
- **Missing UMA resolution join → confirmed gap.** The toy backtest had to hand-roll the outcome from
  Gamma `outcomePrices`; there is no PIT resolution join in the read path. Required before any real
  fade backtest (so a contract's terminal value is the actual UMA outcome, PIT-stamped at resolution
  time, not leaked early).

### Single highest-value next experiment

**Re-run the fade at HOURLY granularity via the windowed CLOB path, on a cohort of resolved markets,
with the UMA resolution join.** Concretely:

1. Add a windowed fetcher: page `startTs`/`endTs` at `fidelity=60` across each market's life (proven to
   return ~3600s-spaced rows; ~335 rows / 14-day window) instead of `interval=max&fidelity=1440`. This
   alone turns ~1 trade/market into dozens — the difference between "Gate refuses" and "Gate can judge."
2. Join the **UMA resolution** (Gamma `umaResolutionStatus=resolved` + `outcomePrices`), PIT-stamped at
   the resolution timestamp, as the contract's terminal price.
3. Backtest the *full* spec (rich-level entry **AND** velocity-rollover, with the stop/TP/time-stop) on
   that hourly cohort, net of CLOB fees, and run it through the existing Gate.

That is the one experiment that decides whether the prediction-fade lane is real — it removes the two
confirmed blockers (granularity + resolution join) and tests the actual edge thesis (intraday over-
extension that reverts *before* resolution), which neither the daily wiring nor this toy could reach.

---

## Provenance / reproducibility

- Endpoints: `gamma-api.polymarket.com/markets` (discovery, resolution), `clob.polymarket.com/prices-history`
  (odds history). Keyless, free.
- Code read: `cosmu/ingest/polymarket_odds.py`, `cosmu/data/sources/polymarket.py`
  (`PerMarketOddsSource`, `PolymarketClobSource`), `cosmu/data/providers/store.py`
  (`read_asof`/`available_at` PIT semantics), `cosmu/research/leakage_tripwire.py`,
  `cosmu/research/disconfirmers.py`, `strategies/inbox/g2-prediction-prob-overextension-fade-short.json`.
- Experiment script: `/tmp/pm_trust_experiment.py` (disposable, not committed). All numbers above are
  from a live run on 2026-06-25.
- **Zero production impact:** read-only fetches; no DB writes, no `alt_data` rows, no cron, no Gate run,
  no code merged. Docs-only.
