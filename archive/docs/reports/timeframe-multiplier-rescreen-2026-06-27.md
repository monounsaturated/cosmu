# Timeframe-multiplier luck lever — does the timeframe axis resurrect a killed crypto-price edge?

**Date:** 2026-06-27 · **Mode:** EXPERIMENT / MEASURE-ONLY — zero prod impact. The existing re-screen harness was run
with `persist=False`; **no `backtest_symbols` / `tracks` / `strategy_versions` row was written by this run, no paper
track opened, no Gate constant touched, no money moved.** Verified post-run (see "Prod-write audit").
**Origin:** the one untested entry in the cross-disciplinary playbook (`docs/reports/cross-disciplinary-playbook-2026-06-26.md`)
— the *timeframe-multiplier* luck lever. Distinct from the deep-window probe (`rescreen_cohort.py --deep`, already
disconfirmed 0/7): that varied the *amount* of data; this varies the *bar size*.

**Question under test:**
> A killed crypto-PRICE spec failed at its NATIVE timeframe. If we re-screen the *same* spec through the *unchanged*
> locked Gate at a *different* bar size (1h / 4h / 1d), does any of them flip to "would-pass"? I.e. is the timeframe a
> free luck lever that manufactures a survivor the way best-of-N variant search would?

**Harness:** `apps/engine/scripts/research/rescreen_cohort.py` (the LOT-C measure-only re-screen, `persist=False`).
**Cohort file:** 8 killed version_ids (`.cosmu/research/tf_cohort.txt`, disposable). **Raw JSON:**
`.cosmu/research/tf_multiplier.json` (`run_id 2026-06-27T16-41-45Z`). **Disposable HTML table:**
`docs/reports/timeframe-multiplier-rescreen-2026-06-27-table.html`.

---

## Verdict: **NO flip. 0 / 8 killed crypto-price specs pass the unchanged Gate at ANY of 1h / 4h / 1d.**

The timeframe axis does **not** resurrect a killed crypto-price edge. `crypto-price exhausted` holds *across*
timeframes, not just at the native one. The would-pass count is **0/8 (0.0%)** with the requested
`--timeframes 1h,4h,1d` override — every spec was screened once per timeframe and **not one variant×symbol×timeframe
cell cleared the Gate + own-holdout**.

This is the *same shape* of result as the deep-window probe: a lever that *changes the data view but not the signal*
does not turn a no-edge into an edge. Best-of-N over timeframes is just another multiple-testing knob, and the Gate
(which this run left completely unchanged) is exactly the thing that refuses to be farmed by it.

---

## The cohort (bounded, high-EV, thin-window, crypto-price-only)

Selection (prod DB, measure-only read): `status='killed'` ∧ best backtest **DSR-probability ∈ [0.90, 0.95)** (near-miss,
the highest-EV "almost survived" band; Gate threshold = 0.95) ∧ **crypto-PRICE-only** (`catalyst`, `event`,
`funding_feature` all null; every entry feature is OHLCV/technical — `ret_Nd`, `vol_realized`, `adx`; no event/funding/
alt feature) ∧ a venue in {binance, binanceperp, kraken, hyperliquid} ∧ **thin screen window (< 1 yr)** — the Lot-B
slice where a deeper/different data view has the *most* room to change the verdict. After de-duplicating near-identical
versions, the thin-window crypto-price near-miss universe collapsed to **two distinct spec families** (16 versions);
the cohort takes the highest-DSR 8, capped so one family cannot dominate.

| # | DSR (native) | bar | screen window | spec family | version_id |
|---|---|---|---|---|---|
| 1 | 0.9468 | 4h | 127 d | Cross-asset volatility breakout (`ret_Nd`, `vol_realized`) | `0d555409` |
| 2 | 0.9397 | 4h | 127 d | Cross-asset volatility breakout | `a82dc304` |
| 3 | 0.9150 | 1h | 31 d | ORB + FVG-multiple (`ret_Nd`) | `c1232825` |
| 4 | 0.9150 | 1h | 31 d | ORB + FVG-multiple | `1823e5c7` |
| 5 | 0.9150 | 1h | 31 d | ORB + FVG-multiple | `0b4e07ef` |
| 6 | 0.9150 | 1h | 31 d | ORB + FVG-multiple | `e11bdd67` |
| 7 | 0.9150 | 1h | 31 d | ORB + FVG-multiple | `48e97257` |
| 8 | 0.9150 | 1h | 31 d | ORB + FVG-multiple | `d7399d48` |

Both families were killed at native tf for the **same root reason: trade starvation, not a borderline edge.** The
production cron's *own* native-tf screen earlier today (00:20–08:52 UTC, independent of this run) tagged every cell with
`min_trades_per_symbol` (+ `deflated_sharpe` + `folds_positive` + `buy_and_hold`), at an average of **0.3–2.6
trades/symbol** — these are thin-window seeds that barely fire, the textbook case where "try another bar size" is the
tempting luck lever.

---

## Per-spec × per-timeframe result

Run: `--timeframes 1h,4h,1d --shallow --max-variants 8`, `persist=False`, `COSMU_BARS_URL` unset, local deep bar cache
(341 MB, `~/.cosmu/market_data`) symlinked in (then removed; tree clean). Each spec was `model_copy`'d to
`horizon.bar_sizes = [1h, 4h, 1d]` so the finder screens it once per timeframe — every other Gate input byte-identical.

| version | native | 1h | 4h | 1d | would-pass at ANY tf? |
|---|---|---|---|---|---|
| `0d555409` Cross-asset vol breakout | 4h | kill | kill | kill | **NO** |
| `a82dc304` Cross-asset vol breakout | 4h | kill | kill | kill | **NO** |
| `c1232825` ORB + FVG | 1h | kill | kill | kill | **NO** |
| `1823e5c7` ORB + FVG | 1h | kill | kill | kill | **NO** |
| `0b4e07ef` ORB + FVG | 1h | kill | kill | kill | **NO** |
| `e11bdd67` ORB + FVG | 1h | kill | kill | kill | **NO** |
| `48e97257` ORB + FVG | 1h | kill | kill | kill | **NO** |
| `d7399d48` ORB + FVG | 1h | kill | kill | kill | **NO** |

`kill` = no variant cleared the Gate at that timeframe. The harness only materialises *gate-passing* cells
(`report.leaderboard + report.survivors`, and `leaderboard` is built from `gate_passers` only), so "0 gate-passers" is
reported as `cells=0` for every spec — i.e. **8/8 specs produced zero gate-passing cells across all three timeframes.**

**Headline: did ANY killed spec flip at a non-native timeframe? → NO.**

---

## Why `cells=0` is a real measurement and not an empty/silent run (the footgun from the prior probe)

The prior probe's lesson was that an unconfigured cache or a left-on `COSMU_BARS_URL` makes the screen *silently* read
~999 remote bars or an empty cache, so a "still-killed" can be a non-measurement. Three independent checks confirm this
run actually backtested real bars:

1. **Runtime.** The run took ~27 min at sustained ~100% CPU. An empty/999-bar screen of 8 specs finishes in seconds.
   60-symbol 1h screens are the dominant cost — consistent with real per-symbol backtests over the cached series.
2. **Cache wiring.** `COSMU_BARS_URL` was explicitly **unset** for the process and the 341 MB local cache was symlinked
   into the worktree before the run (then removed afterward; `git status` clean).
3. **A native-tf control screen** of `0d555409` (4h, `max_variants=4`, same code path) returned `screened=4,
   gate_passed=0, leaderboard=0, survivors=0` — i.e. it *did* run 4 real variant backtests and *none* passed, exactly
   the `cells=0` pattern. The production cron's *own* native-tf cells today carried real, non-zero trade counts
   (up to 16/symbol on some cells). So `cells=0` here = "Gate refused every cell", not "no data".

---

## Prod-write audit (this run wrote nothing)

- All 8 cohort versions are still `status='killed'` after the run (re-queried).
- `tracks` for the cohort: **0**.
- `backtest_symbols` rows for the cohort created today exist (240) **but every one is timestamped 00:20 / 04:20 / 08:26 /
  08:52 UTC — all from the 4-hourly production Modal cron, all BEFORE this run's 16:14–16:43 UTC window.** Zero cohort
  rows were written in the run window.
- The harness is `persist=False` by construction (`StrategyFinder.find(..., persist=False)` never calls `_persist`, the
  sole writer of `backtest_symbols`/`tracks`/survivor events). **prod_writes = 0.**

---

## Sample size, caveats, and what is unknowable

- **Small N.** 8 versions, **2 distinct spec families** — because the thin-window (<1 yr) crypto-price near-miss slice
  is genuinely small in the current population (16 versions total, 2 families). This is a *targeted* probe of the
  highest-EV slice, not a population census. A null on 2 families is suggestive, not a proof that *no* crypto-price spec
  anywhere could ever flip on timeframe.
- **The cohort's kill reason was trade-starvation, not a near-miss edge.** Their DSR ∈ [0.90, 0.95) was the *best single
  cell*; the binding kill was `min_trades_per_symbol` on a thin window. Switching bar size does not add calendar history,
  so a finer bar (1h) fires more often but over the *same short span* and a coarser bar (1d) fires even less — neither
  manufactures the trade count *and* the deflated edge the Gate demands simultaneously. This is the mechanism behind the
  null, and it is exactly why the timeframe lever is structurally weak here.
- **Shallow window by design.** This run is `--shallow` (1500/1000-bar window) to isolate the *timeframe* axis from the
  *depth* axis (already tested separately). A spec could in principle need *both* a different bar size *and* a deeper
  window to flip; this run does not test that interaction (it would re-introduce the depth confound).
- **What's unknowable from this run:** the *per-tf kill reason* (the harness surfaces only gate-passers, so a failing
  cell's reason is not in the JSON — only the prod cron's native-tf verdicts give that). And, as always, a backtest
  "would-pass" — had any appeared — would still not be a live edge; only paper/forward is the fluke safeguard. Here the
  question is moot: nothing passed.

---

## Bottom line

The timeframe axis is **not** a hidden luck lever for killed crypto-price specs. Combined with the prior deep-window null
(0/7) and the locked Gate's multiple-testing controls, the practical reading is firm: **for the thin-window crypto-price
near-miss slice, `crypto-price exhausted` holds across 1h / 4h / 1d.** The edge is not hiding in a different bar size;
the direction remains away from re-screening dead crypto-price seeds and toward orthogonal data / new market structure
(equity-TAA, prediction-market) per the playbook.
