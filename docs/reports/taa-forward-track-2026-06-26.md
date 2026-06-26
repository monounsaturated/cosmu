# TAA survivor → forward (paper) tracking — verify + repair (2026-06-26)

**Task:** promote the equity-TAA survivor (DAA/VAA/ADM) from backtest → FORWARD (paper) so its real
forward record starts toward live-readiness. Investigate first; act only on a real gap; never arm money.

## TL;DR

- **The survivor is ALREADY forward-tracked.** DAA, VAA, ADM — and 6 documented TAA siblings — each have a
  `strategy_versions` row with `status='paper'`, `origin='documented'`, a `tracks` row, and a `track_opened`
  event (forward-clock origin). They were armed on **2026-06-07/08** via the documented-arm lane. **No new
  track was opened** (that would have duplicated an existing honest track).
- **The autonomous loop DOES auto-advance them.** The Modal `tick` cron (every 4h, `remote/app.py::tick`)
  runs `cosmu.research.arm_fleet`, which calls each `*_arm.py::arm()` (idempotent, SIM-only). So the loop
  keeps the forward clock ticking for the arm-based tracks — no manual intervention needed to *open* them.
- **BUT their forward state was being surfaced DISHONESTLY** — a real marking bug, fixed here. The honest
  per-track snapshot said `$1000 flat`, yet `tracks.equity` / `tracks.return_pct` (what the leaderboard and
  `live_eligibility.paper_net_return_pct` read) showed phantom catastrophic losses: **DAA −83.06%**, PAA
  −86.17%, GTAA −81.35%, TSMOM −80.09%, Sector −65.87%, RiskParity −32.91%.

## The survivor cell(s)

`research/equity_taa_cohort.py` routes ~12 documented multi-asset rotations through the **full 0.95 Gate**
(DSR ≥ 0.95 vs trial-inflated benchmark · BH-FDR q=0.10 · real purged+embargoed holdout · CSCV-PBO · folds/DD)
on their NATIVE total-return monthly universe. DAA/VAA/ADM clear the STRICT bar; PAA/GTAA/RiskParity/TSMOM
clear the DSR+holdout bar. The cohort module is *measure-only* — it does **not** register tracks.

Registration is a separate, deliberate lane: the per-strategy `research/equity_*_arm.py` modules
(`arm()` → `master/tracks.open_paper_track`), orchestrated by `research/arm_fleet.py`. This lane is on the
DEPLOY bar (positive OOS net of real IBKR fees + risk-adjusted beat of B&H), NOT the in-sample Gate — it
deploys externally-validated documented strategies to paper. The 0.95 Gate is untouched.

## Lifecycle finding

| | DAA | VAA | ADM | + 6 siblings |
|---|---|---|---|---|
| version status | `paper` | `paper` | `paper` | `paper` |
| origin | `documented` | `documented` | `documented` | `documented` |
| track row | yes | yes | yes | yes |
| `track_opened` (forward clock) | 2026-06-08 | 2026-06-07 | 2026-06-07 | 2026-06-07/08 |
| born honest (no OOS seed) | yes ($1000) | yes | yes | yes |

The track is **already open and the loop already advances it** → the only legitimate action was to **verify
honesty and repair** the surfaced forward number, not to open a duplicate.

## The bug (root cause)

`orchestrator/loop.py::mark_tracks` re-keys each held position to its BRUT cell
(`version:symbol:venue`) via a `cell_resolver`, giving every cell its own `scope='track'` snapshot series.
That is correct for genuine per-cell tracks. But the **documented multi-leg arms** hold one *legacy
version-wide* track row (`tracks.symbol/venue = NULL`) spanning N symbols (DAA = 6 legs: AGG/EEM/EFA/LQD/QQQ/SPY).

In `portfolio.mark_to_market`, each leg resolved to a distinct cell key but found **no per-cell `tracks`
row** to anchor it → it fell to the `open_value` branch and wrote a snapshot worth **that one leg's
notional (~capital/N ≈ $166)** instead of the whole book. `_update_track_returns` then read the latest
cell-keyed fragment as the track's equity → **DAA $1000 → $169.35 = $1000/6 → a phantom −83%**.

The pattern was unambiguous in prod: every 1-leg arm (ADM/GEM/VAA, which DO own a stamped cell track) read
correctly (~$1000); every N-leg arm read ≈ $1000/N.

## The fix (two loci, minimal, brut model preserved)

1. **`master/portfolio.py::mark_to_market`** — a position adopts its cell key ONLY when a real per-cell
   `tracks` row owns that `(version, symbol, venue)` triple. A version-wide track now aggregates ALL its
   legs on the version key → the snapshot marks the **whole book**. Genuine per-cell tracks are unaffected
   (single-leg arms stay cell-keyed; the BRUT per-cell model is intact). Pre-migration (no cell columns) →
   empty set → version-keyed, byte-identical to prior behaviour.
2. **`orchestrator/loop.py::_update_track_returns`** — for a version-wide track, read the VERSION-keyed
   snapshot FIRST (its honest whole-book trajectory), falling back to the cell key only when no version
   snapshot exists (the single-cell case still advances off its seed).

**Regression test:** `tests/test_asset_aware_marking.py::test_versionwide_multileg_arm_track_marks_whole_book_not_one_leg`
— a 3-leg version-wide arm, flat at entry, must mark to its full $1000 (not $333). Verified to FAIL without
the fix ($333.35) and PASS with it.

## Prod repair (idempotent, SIM-only, no money moved)

Ran the corrected `mark_tracks` against prod (equity leg forced to keyless Yahoo — Alpaca returns 0 from the
operator Mac; the Modal/Railway cron uses the working feed). Result — honest, realistic forward records:

| arm | before (corrupt) | after (honest) |
|---|---|---|
| **DAA** | $169.35 / −83.06% | **$1015.97 / +1.60%** |
| TSMOM | $199.12 / −80.09% | $994.93 / −0.51% |
| GTAA | $186.48 / −81.35% | $990.10 / −0.99% |
| PAA | $138.28 / −86.17% | $1004.48 / +0.45% |
| RiskParity | $670.90 / −32.91% | $998.33 / −0.17% |
| Sector | $341.30 / −65.87% | $995.17 / −0.48% |
| ADM | $995.59 / −0.44% | $995.59 / −0.44% (SPY, unchanged) |
| GEM | $995.59 / −0.44% | $995.59 / −0.44% (SPY, unchanged) |
| VAA | $1052.18 / +5.22% | $1052.18 / +5.22% (EEM, unchanged) |

All 9 versions remain `status='paper'` (alive). The stale fragment cell snapshots are left in place (inert
— the read-side now prefers the version key) rather than destructively deleting history; the next cron mark
continues the honest series.

## Honest-state verification

- Born honest: `tracks.starting_capital = $1000`, no backtest-OOS seed (the `scope='track'` series shows
  `$1000.00 / pnl $0.00` at funding; equity now moves only from real marks).
- Forward clock advancing: `scope='track'` version-wide snapshots written today on the 4h cadence.
- Live gate untouched: `track_opened` is the live-arming origin; `PAPER_MIN_DAYS` + proven-regime passport
  still gate live (human-only). Nothing was armed.

## Answer

- **TAA survivor:** DAA (+ VAA, ADM) — clears the full 0.95 Gate on the native monthly universe via
  `equity_taa_cohort.py`; deployed to paper via the documented-arm lane.
- **Forward-tracked now?** **Already existed** (armed 2026-06-07/08) **and the autonomous `tick` cron
  auto-advances it** via `arm_fleet`. No track opened (would duplicate).
- **Honest state:** born honest, but the surfaced forward number was corrupted by a multi-leg marking bug —
  **fixed (code + regression test) and the prod data repaired** to honest values (DAA now +1.60% forward).
