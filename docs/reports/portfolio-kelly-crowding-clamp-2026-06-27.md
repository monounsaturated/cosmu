# Portfolio-axis crowding clamp — Kelly × signal-correlation (2026-06-27)

> Ships the long-backlogged crowding detector (sizing **T2**). Playbook bridge **#7** + red-team **#6** from
> `docs/reports/cross-disciplinary-playbook-2026-06-26.md`. Khandani-Lo deleveraging risk: a book of cells the Gate
> each blessed *alone* can be the **same trade**, and that is invisible to a single-cell Sharpe gate. **Gate
> constants are LOCKED** — this is a propose-only portfolio-axis overlay *after* the per-combo gate; it never
> changes a verdict and never moves money.

## BLUF

A funded-track book of 6 cells — a crowded crypto-beta momentum **cluster of 4** plus **2 decorrelated** cells —
run **WITH vs WITHOUT** the signal-correlation clamp:

| arm | total return | max drawdown | recovery (ret / DD) |
|---|---|---|---|
| WITHOUT clamp | **+13.82%** | **27.35%** | 0.51 |
| WITH clamp | **+13.36%** | **13.07%** | **1.02** |

**Same return (−0.5pp), half the drawdown (−52%), double the risk-adjusted return.** Across 20 noise seeds the
drawdown is cut **48–57%** (median 53%) *every time*, the recovery factor improves *every time*, and the absolute
book return moves only a little (median +0.3pp). That is the signature of shedding **redundant, synchronised**
exposure: the crowd's copies add little *unique* return (their gains round-trip in the shared crash) but they drive
the book's worst peak-to-trough.

The conceptual point: the book's drawdown is a property of how the cells move **together**, which **no per-cell
gate can see** — DSR, PBO, holdout and even a per-cell max-drawdown bar all judge each cell **alone**. A book of
individually-blessed cells can still draw down past any single-cell limit purely from correlation (here the
WITHOUT-clamp book hits 27%). **That gap is exactly the portfolio-axis risk the time-axis Gate is structurally blind
to** — and what this instrument measures.

## What was built

Three pieces, all **PURE** (no I/O, no DB, deterministic) and **propose-only** (never a gate input, never money):

1. **Fractional-Kelly self-sizing from the *deflated* edge** — `master/sizing.py :: kelly_size_multiplier`.
   A frozen funding-time multiplier in `[0.10, 0.50]` derived from the cell's deflated-Sharpe **probability**
   (`scorer.deflated_sharpe_prob` / `Track.rolling_dsr`), **not** the raw in-sample Sharpe. Sizing on the deflated
   edge is the whole point: the raw Sharpe is the exact number overfitting inflates, so it is the worst thing to
   lever on. Half-Kelly (the default scale) keeps ~¾ of full-Kelly's growth at far lower drawdown and is robust to a
   mis-estimated edge. It is **multiplied on top of** `size_fraction` (the same seam as `tracks.exposure_factor`),
   never threaded inside it — so `size_fraction` stays the gate-verified physics and the backtest==forward==live
   parity (audit #7) is untouched.

2. **Pairwise SIGNAL-correlation clamp (Khandani-Lo)** — `master/signal_crowding.py`.
   Clusters live cells by the Spearman correlation of their **SIGNAL** streams — the positions they *want*, not the
   returns they *got* — at a **0.70** cap (tighter than the realized-return crowding's 0.85, because signals reveal
   structural crowding a calm window hides). Any cluster above the cap is scaled **DOWN** to ~one cell's worth: keep
   the best representative at full exposure, scale every other member to `1/cluster_size` (floored at 0.10). The
   freed exposure is **not redeployed** — no pooled wallet; the cluster simply deploys less. A crowd of K
   near-identical signals is no longer K trades that collapse into one under stress.

   *Why signal, not realized return?* `master/crowding.py` already clamps on **realized-return** correlation
   (ex-post: did they make money together?) and is wired into the funder. This new instrument is the **ex-ante,
   structural** axis (do they hold the same positions?) — it fires *before* a calm window can mask the redundancy.
   The two are complementary; this PR adds the signal axis and leaves the realized-return one untouched.

3. **Capacity as a first-class RANKED feature, never a disqualifier** — `signal_crowding.py :: capacity_score`.
   A `[0,1]` "where to play" rank (poker game-selection: *where* you play beats *how well* you play). It rewards
   markets that are **fillable** for our small size **and niche** (desk-invisible — below the ~$25M/day a quant desk
   can deploy into; that thin turf is the solo's moat). It **ranks** a cell and **tips which member a crowded
   cluster keeps** — it never kills a cell. In the backtest this is visible: the cluster keeps `momo_niche`
   (cap-rank 0.70) at full size over the deeper, *higher-edge* `momo_sol` (cap-rank 0.50) — capacity changed *where*
   the book deploys its full slice.

Per-cell factors from the run (`combined = kelly × crowding`):

```
cell         cluster  edge→kelly   crowd  cap_rank  combined  keep
momo_niche      1     0.958→0.479  1.000    0.70     0.479    ★ KEEP   (niche moat wins the cluster)
momo_sol        1     0.964→0.482  0.250    0.50     0.120    · scaled
momo_btc        1     0.962→0.481  0.250    0.50     0.120    · scaled
momo_eth        1     0.960→0.480  0.250    0.50     0.120    · scaled
carry_b         0     0.961→0.480  1.000    0.63     0.480             (decorrelated → untouched)
meanrev_a       0     0.958→0.479  1.000    0.49     0.479             (decorrelated → untouched)
```

## Method & honesty notes

- **Data.** Exchange network (Binance/Kraken/Bybit) is **policy-blocked** in this session (403 on CONNECT), so the
  book is a **deterministic, fully-disclosed methodology fixture**, built to embody the exact structure the clamp
  targets — *not* live P&L, and never shown in the app (honest-loop rule: synthetic, edge-bearing constructions stay
  in CI/tests/methodology). The crowd is 4 **long-biased crypto-beta** cells whose signals move together; the beta
  factor is tuned to **round-trip** (a bull the synchronised crash gives back), which is why the crowd nets little
  over the cycle but shares a deep mid-cycle drawdown.
- **Boundary of the claim (stated honestly).** "Similar return" holds because the crowd **round-trips**. A crowd
  that *kept* its gains would see the clamp cost return (you cannot drop profitable redundant copies for free in a
  no-pooled-wallet book) — there the win shows up as a higher **recovery factor**, not flat return. Both regimes
  improve risk-adjusted return; only the round-tripping regime gives ~flat absolute return.
- **Reproduce on real bars.** The book simulator (`master/crowding_backtest.simulate_book`) is data-source-agnostic.
  In a session **with** exchange network, point `returns_by_cell` at real per-bar streams from
  `data/backtest.run_strategy_backtest_detailed` (which already charges per-venue fees + 5bps slippage) and derive
  each cell's SIGNAL stream from its replayed positions; the same WITH-vs-WITHOUT comparison runs unchanged.
- **Compute.** Bounded: 6 cells × 252 daily bars, no network, no DB — trivially M2/Modal-friendly.

## Run it

```
PYTHONPATH=apps/engine python3 apps/engine/scripts/crowding_clamp_backtest.py
```

Tests: `apps/engine/tests/test_kelly_sizing.py`, `test_signal_crowding.py`, `test_crowding_clamp_backtest.py`.

## Not in this PR (follow-up, needs operator sign-off)

Wiring the combined factor into the **live** paper/live executor needs a new `tracks` column (e.g.
`portfolio_factor`) to persist it next to `exposure_factor` — a **schema change** (AGENTS.md: *ask first*). The
existing realized-return crowding already proves the funder→`tracks`→`paper_step` seam; the drop-in is
`portfolio_exposure_factors(cells).combined()` multiplied into the sized fraction, exactly like `exposure_factor`
is today. The instrument is built and proven here; the live persist is the gated next step.
