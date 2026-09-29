# Backtest provenance + price-source÷venue divergence (no more black-box backtests)

**Date:** 2026-06-28
**Branch:** `claude/backtest-provenance-2026-06-28`
**Status:** DO NOT MERGE yet — autonomous-run POC.

## Why

Operator rule: *"a backtest result must never be a black box."* Audit PR #472 confirmed that
`data/reference.load_decision` computes a `price_alignment` (which source served the cell, whether it FELL BACK to a
reference source, and the corr/spread vs the venue's own price) but the verdict was **write-only** — persisted, never
surfaced on a result. This PR makes the facts available on the backend (result object + log line + API field). No web
components.

## What is now surfaced (and where)

### 1. Per-cell DATA PROVENANCE

A new `CellProvenance` dataclass (`apps/engine/cosmu/data/reference.py`) captures, per (symbol × venue) cell:

- **symbol · venue** — the canonical pair + the LIVE venue the fee/depth overlay prices against.
- **bar_source** — WHERE the scored bars came from (`binance-reference`, `kraken-keyless`, `bybit-keyless`,
  `hyperliquid-keyless`, `ibkr-equity`, `polymarket-odds`). NOT necessarily the live venue.
- **bar_interval** — the bar size scored (`1h`, `1d`, …).
- **first_bar_ts / last_bar_ts / n_bars** — the actual date range + count of bars scored.
- **holdout_split_index** — where validation ends and the embargoed holdout begins (mirrors
  `_purged_embargoed_split`: `max(40, int(0.8·n))`; `None` when too short to hold out).
- **fee_bps / slippage_bps / impact_bps** — the TODAY's-schedule cost overlay charged on every fill
  (fees-always-today rule), recorded — not re-typed — from the per-cell schedule (cross-venue overlay) or the
  primary-venue scalar on the single-venue path.

Populated where the data is assembled:
- `data/price_cells.PriceCell` gains a `bar_source` field, set at build time via `_bar_source(...)` for every cell
  (reference / UNIFY / FALLBACK / per-venue-native paths).
- `lab/finder.StrategyFinder._market` carries each cell's `CellSource` (source / reference-reuse / alignment) out
  alongside the bars; `_build_provenance(...)` assembles one `CellProvenance` per cell once the per-cell fee/depth
  overlay (`build_cost_context`) is known.

Surfaced on:
- **Result object** — `CellResult.provenance` (each brut cell carries its own record).
- **Log** — one `PROVENANCE …` line per cell, emitted at screen time (`cosmu.lab.finder` logger).
- **Persistence / API** — the record is written to the cell's `track_opened` event payload (`provenance` key) and
  served by a new endpoint `GET /strategies/{version_id}/cell-provenance?symbol=&venue=`
  (`CellProvenanceResponse`). Schema-free: reads the event payload, no migration.

### 2. SOURCE ≠ VENUE price divergence — made visible

The `CellProvenance` record states plainly **"backtested on `<source>` price → live venue `<venue>`"** and carries the
divergence metric straight from the alignment decision:

- **source_is_fallback** — True when the price SOURCE differs from the live VENUE (a shared reference book was reused
  for a non-reference venue). Covers BOTH the UNIFY path (with a measured alignment) AND the per-venue-mode
  *"native bars missing → fall back to reference"* path (no alignment measured).
- **align_corr / align_spread_bps / align_overlap** — Pearson corr of returns + median |spread| (bps) + shared-bar
  count.
- **divergence_flagged** — `⚠ DIVERGENT` when a fallback's source tracks the live venue too loosely
  (corr < `PROVENANCE_FLAG_MIN_CORR` = 0.95, or spread > `PROVENANCE_FLAG_MAX_SPREAD_BPS` = 50 bps, or the overlap
  was too thin to even measure). A native-venue cell (source == venue) is NEVER flagged.

These are **LOOSE display thresholds** (the strict gate stays `UNIFY_*`): we flag a cell for the operator to inspect,
we never silently move a number.

## Numbers / Gate / money-path untouched

Strictly additive + display-only:
- New dataclass + a `bar_source` field defaulting to `""` (empty/fallback paths byte-identical).
- `CellProvenance` is READ off bars + the cost overlay + the alignment decision — it is **never** a gate input.
- No change to `data/backtest.py` scoring, the FDR/DSR/PBO math, `promote_brut`, or any money-path code.
- The `track_opened` event gains an extra `provenance` key; the gate verdict, proven-regime passport, and live-arming
  join are unchanged.

## Tests

`apps/engine/tests/test_backtest_provenance.py` (14 tests, all green):
- a cell exposes source/interval/range/#bars/holdout/fee-schedule;
- a UNIFY (source≠venue) cell surfaces the divergence + the fallback flag; a divergent fallback (low corr / wide
  spread / unmeasured) is flagged `⚠ DIVERGENT`;
- a native-venue (reference, or own-bars FALLBACK) cell shows aligned / no-fallback;
- `to_dict()` is JSON-serializable; the log line states the facts;
- the finder's `_build_provenance` populates per-cell records with the cross-venue cost overlay (and the scalar
  fallback on the single-venue path).

Also updated `tests/test_finder_prediction_branch.py` (2 call sites) to unpack `_market`'s new 3-tuple.

Adjacent suites re-run green: `test_universal_price.py`, `test_cell_equity_curve.py`,
`test_per_venue_bars_archive.py`, `test_lab_finder.py`, `test_finder_honesty.py`, `test_strategy_triplet_api.py`,
`test_strategy_summary.py`.

## Honest limitations

- **Provenance is recorded going forward only.** It lands on the `track_opened` event of newly-funded cells; cells
  whose tracks opened before this shipped return `available=false` from the API (no migration, no backfill).
- **`bar_source` is a coarse provider label, not a vendor/URL.** It names the book family (reference vs venue-keyless
  vs asset-class native), which is what the source-≠-venue question needs; it does not record the exact cache file or
  vendor endpoint.
- **API serves provenance only for FUNDED cells** (those that opened a track). A killed/non-funded cell's provenance
  lives on the `CellResult` object + the log line for that run, but is not queryable by the endpoint (it has no
  track event). Persisting provenance on every `backtest_symbols` row would need the held per-cell migration.
- **Holdout split is the documented `0.8` rule re-derived from the bar count**, not read back from
  `data/backtest`'s actual per-cell split (which can shrink when the embargo leaves too few holdout bars). It is the
  intended split, not a guaranteed exact index for a degenerate-length cell.
