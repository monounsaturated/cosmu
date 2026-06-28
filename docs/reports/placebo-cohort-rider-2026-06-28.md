# Placebo empirical-null panel as a standing finder cohort-rider (flag-gated, observe-only)

Date: 2026-06-28 · Branch: `claude/placebo-cohort-rider-2026-06-28` · Status: POC, **DO NOT MERGE yet**

## What this does

Roadmap #1 (highest leverage): wire the **existing** negative-control empirical-null panel
(`apps/engine/cosmu/research/placebo_panel.py`) into the finder's cohort path so it rides **every**
cohort on the finder's **real screened market** — converting a dormant honesty instrument (it only ran
from its own CLI / a dedicated test) into a **standing tripwire**.

The panel is the Gate's self-validation instrument (cross-disciplinary playbook bridge #1, from
pharmaco-epi / GWAS, Schuemie-OHDSI): it runs ~10 **placebo** specs (5 time-shuffled real signals + 5
pure-noise random-entry, sized to be Gate-eligible) through the **exact** finder→Gate BRUT path and
measures where they land. The headline check: **if any placebo clears the LOCKED Gate, that is an
upstream leak the Gate structurally cannot see** — reported loudly, never a test to weaken.

Before this change the panel never observed a real finder cohort. Now it does.

## The wiring

- **New module** `apps/engine/cosmu/lab/placebo_rider.py` — the seam, kept out of `finder.py` so it is
  pure and unit-testable in isolation. Public surface: `placebo_rider_enabled()`, `ride_cohort(...)`,
  `RiderOutcome`.
- **Finder hook** in `apps/engine/cosmu/lab/finder.py::_screen_timeframe`, placed **after** the cohort
  has fully screened + scored + `record_looks(...)` and **before** `_persist(...)`. It runs once per
  cohort (per timeframe), observes the **same `market` dict** the finder just screened, and passes the
  cohort's **promoted survivors' DSRs** for the optional survivor-vs-null comparison.

### The flag — `COSMU_PLACEBO_RIDER`, DEFAULT OFF

Mirrors the established `lab/depth.COSMU_SCREEN_DEEP` env-knob pattern (truthy = `1/true/yes/on`).
When unset/falsey, `ride_cohort()` returns `None` immediately — **a strict no-op**: no panel runs, no
extra backtests, the finder is byte-identical. Only when explicitly enabled does the panel run.

### Behaviour when ON (observe-only / propose-only)

1. Run `run_placebo_panel` on a **bounded, deterministic slice** of the same real market (≤
   `_MAX_RIDER_SYMBOLS = 6` symbols, stable-sorted cell keys — reuses already-screened bars, **no
   re-fetch, no new data**). The panel still runs its full ~10 placebo specs on that slice.
2. Always log `PlaceboPanel.render()` at INFO (the standing-instrument breadcrumb).
3. **If `any_cleared` is True** (a placebo cleared the LOCKED Gate): log **LOUDLY** at WARNING
   (`UPSTREAM LEAK CAUGHT …`) **and** write a best-effort `placebo_leak` **event row** (the same
   events-table audit trail the finder already uses for `track_opened` / `finder_survivor` /
   `holdout_look`), carrying the cleared cells.
4. For each promoted survivor, optionally attach `compare_survivor_to_null` so the survivor's DSR is
   placed in the measured null's right tail (logged + returned).

It **never blocks, fails, or alters the live verdict**: it reads the locked gate constants, never writes
them; `promote_brut` is untouched; and **any error inside the rider is swallowed** (an observer must
never put the live finder run at risk).

## Boundedness (M2 / cron safe)

- No-op cost when the flag is OFF (the production default).
- When ON: at most one bounded panel per cohort, ≤ 6 symbols × ~10 placebo specs, on bars the finder
  already loaded. No new fetch, no DB read on the hot path beyond a single best-effort event insert on a
  caught leak.

## Tests

`apps/engine/tests/test_placebo_cohort_rider.py` (19 tests, all green locally) proves the three
load-bearing guarantees from the task:

- **(a) OFF by default** — flag unset ⇒ `placebo_rider_enabled()` False, `ride_cohort()` returns None
  and the panel is **never** invoked (a spy raises if it is); falsey/truthy env-value parsing pinned.
- **(b) ON ⇒ a caught leak fires loudly** — with the flag ON and a known-leaky synthetic panel
  (`any_cleared=True`), the rider logs the `UPSTREAM LEAK CAUGHT` WARNING and writes exactly one
  `placebo_leak` event row with the cleared cell detail. The clean-panel case logs INFO only — no
  warning, no event. (The panel's own leak-**detection** correctness is already pinned by
  `test_placebo_panel.py`; this file pins the **finder-hook** behaviour.)
- **(c) live verdict UNCHANGED either way** — an end-to-end finder run with the flag OFF vs ON produces
  the **identical** `(screened, gate_passed, promoted)` counts and the **same** survivor + leaderboard
  config_tags; a real finder cohort with the rider ON completes without raising; and a panel error is
  swallowed (returns None, never propagates into the finder).

Run locally (worktree, single affected file, M2 discipline):

```
PYTHONPATH=apps/engine APP_ENV=test python3 -m pytest \
  apps/engine/tests/test_placebo_cohort_rider.py -q
# 19 passed

# affected existing suites (finder + panel) still green:
PYTHONPATH=apps/engine APP_ENV=test python3 -m pytest \
  apps/engine/tests/test_lab_finder.py apps/engine/tests/test_placebo_panel.py -q
# 21 passed
```

## Limitations / honest caveats

- **The leaky-market end-to-end is mocked, not natural.** Test (b) forces `any_cleared=True` via a
  synthetic `PlaceboPanel` because the panel **injects** its own placebo signal through `alt_by_symbol`,
  so there is no easy seam to feed a naturally-leaky real market that makes a placebo clear. This is the
  right scope (the hook is what's new; the panel's detection is already covered), but it means we have
  not exercised a real upstream-leak end-to-end through the finder.
- **The bounded slice (≤ 6 symbols) measures the null on a subset of the cohort's tape**, not every
  cell. That keeps it cheap (the design goal) but the empirical null is slightly less rich than the full
  cohort would give. Tunable via `_MAX_RIDER_SYMBOLS` if a deeper null is wanted on Modal.
- **Observe-only by design.** A caught leak emits a WARNING + an event row but does **not** halt the run
  or quarantine survivors — acting on the alarm is a deliberate next step, not this POC.
- **Not yet exercised against prod / a real cron.** The flag defaults OFF; turning it on in the
  autonomous loop / Modal fleet is a separate operator decision. No prod data is mutated by this change.
- **`survivor_dsrs` keys** are `config_tag:symbol@venue` strings for logging legibility; they are not a
  persisted contract.
