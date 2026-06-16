# HANDOFF — OSINT data sources (jet co-location + SEC EDGAR insider) + branch reconcile

**Date:** 2026-06-16 · **Branch:** `feat/rho-bar-wiring` · **Author:** Opus 4.8

> ## STATUS: ✅ INTEGRATED + TESTED (Step A done). Remaining: full-suite confirm + merge to main.
> The two sources are now fully wired through the lock-step contract (all 6 files in "Step A" below were
> applied) and committed on this branch. Targeted QA is green: catalog↔store consistency, registry↔route
> guard, registry discovery, both new source tests, bb_width, and downstream feature_registry/catalog/ingest
> tests (82 + 29 passed) + a programmatic invariant check (95 enabled features, 86 store metrics).
> The full `-n auto` engine suite OOM-crashes xdist workers on this M2 (pre-existing; not this change) —
> re-run it with reduced parallelism: `pytest apps/engine/tests -n 2 --timeout=120 --timeout-method=thread`.
>
> ### Follow-ups (NON-blocking; live-path efficiency only — correctness/PIT/offline are solid):
> - `jet_colocation` live path issues one OpenSky `/flights/aircraft` call per (window-day × tracked aircraft)
>   ≈ 360 calls per ticker per query. Refactor to ONE call per aircraft over the whole `[latest-window, latest]`
>   range (the endpoint accepts up to a 30-day window) and bucket arrivals by day. Rate-limit friendly.
> - `sec_edgar` live path fetches the ownership XML for EVERY recent Form 4 in submissions. Cap to the most
>   recent ~40 within the window and respect SEC's 10 req/s limit. Both degrade gracefully today (→ []/None).

**Goal:** finish wiring two new OSINT `DataSource`s through the lock-step contract, QA green, merge to main.

> Context: this branch has MULTIPLE agents touching it in parallel. This doc tells you exactly what is DONE,
> what is HALF-DONE, and the precise remaining steps. Everything described as "authored + tested green" has
> been run with `pytest` and passes. The remaining work is mechanical wiring + QA + merge.

---

## TL;DR — what to do

1. **Wire 2 new per-symbol/equity sources** (`jet_colocation`, `insider_buy_ratio`) through the lock-step contract
   (6 shared files — exact snippets below). They are NOT wired yet; only the source files + tests exist.
2. **Run QA** (the guard tests + new tests + `pnpm verify`). Fix to green.
3. **Reconcile the parallel `bb_width` work** (already on disk — verify coherent, don't duplicate).
4. **Commit + merge `feat/rho-bar-wiring` → main** (push = deploy; run `pnpm verify` first).

---

## State of the world (git, as of checkpoint)

### ✅ DONE + tested green (my OSINT work — untracked new files)
- `apps/engine/cosmu/data/sources/jet_colocation.py` — `JetColocationSource`
- `apps/engine/cosmu/data/sources/sec_edgar.py` — `SecEdgarInsiderSource`
- `apps/engine/tests/test_jet_colocation.py`
- `apps/engine/tests/test_sec_edgar.py`
- **Verified:** `pytest test_jet_colocation.py test_sec_edgar.py test_bb_width.py` → **69 passed**.
- Both sources are standalone, free, no-key, PIT-honest, offline-safe (offline fixtures, degrade to None, no HTTP in tests),
  low-confidence (jet 0.12, edgar 0.30), `kind="osint"`, satisfy the `DataSource` Protocol, register cleanly.
- **They are NOT yet referenced anywhere** — no store route, no catalog spec, no provider, no registry registration,
  no feature_registry entry. That is the remaining work (Step A below).

### ✅ DONE by a PARALLEL agent (`bb_width` feature — already on disk; verify, don't redo)
- `M apps/engine/cosmu/data/backtest.py` — `_bb_width()` compute + `bb_width` in `_BAR_TA_FEATURES` (→ `PRICE_FEATURES`)
- `M apps/engine/cosmu/config/feature_registry.py` — `bb_width` `FeatureDefinition` added (source=parquet_bars, tier0)
- `apps/engine/tests/test_bb_width.py` — passes
- `M scripts/seed_inbox_strategies.py` + `apps/engine/strategies/inbox/bollinger-squeeze-release-reversion-regime-break.json`
  — an example strategy that uses `bb_width`.
- **`bb_width` looks fully wired** (compute + PRICE_FEATURES + registry + test). Just confirm the guard test passes; don't duplicate.

### 📦 Pre-existing branch leftovers (keep — they're complete)
- `M scripts/ingest_hyperliquid_bars.py` — certifi TLS context fix (macOS). Good.
- `?? docs/research/ASTRO_ULTIMATE_DEEPDIVE_PLAN.md` — untracked planning doc (decide: commit or drop).

---

## Why these two sources (scoping rationale — don't re-litigate)

The source video (IG France macro live) is all macro: oil→rates→USD→equities, VIX, yield-curve 2s10s, credit spreads,
DXY, put/call, breadth. **Every one of those is ALREADY ingested** (FRED `vix_level`/`yield_curve_2s10s`/`credit_spread`/
`dxy`/`fed_funds_rate`, CBOE `putcall_ratio`, etc. — see `feature_registry.py`). The genuine gap matching the operator's
"OSINT / companies / deals / plane movements / thousands of strats like these" ask is **corporate intelligence**:
- `jet_colocation` = the headline "two companies' jets at the same airport → deal signal" generalized into a per-ticker feature.
- `insider_buy_ratio` = wiring the **already-declared but disabled** `sec_edgar` stub in `feature_registry.py`.

Both are causally-plausible (NOT non-causal controls), low-confidence, and the Gate falsifies them OOS.

---

## Exact source identifiers (for the wiring)

| | jet_colocation | sec_edgar |
|---|---|---|
| file | `cosmu/data/sources/jet_colocation.py` | `cosmu/data/sources/sec_edgar.py` |
| class | `JetColocationSource` | `SecEdgarInsiderSource` |
| name == metric | `jet_colocation` | `insider_buy_ratio` |
| kind | `osint` | `osint` |
| confidence | `0.12` | `0.30` |
| transform_version | `jet-colocation-v1` | `sec-edgar-insider-v1` |
| ctor | `JetColocationSource(offline=False)` | `SecEdgarInsiderSource(offline=False)` |
| scope | per equity ticker | per equity ticker |
| market_wide | **NO** (per-symbol) | **NO** (per-symbol) |
| store bucket | `jet_colocation` | `sec_edgar` |
| pure helper | `detect_colocation_events(arrivals_by_ticker, target)` | `net_buy_ratio(txns, *, as_of, window_days)` |

---

## Step A — Wire both through the lock-step contract (6 files)

> **Critical ordering rule:** the registry↔route guard (`tests/test_alt_features.py::test_every_enabled_feature_is_routable_or_computed`)
> AND the catalog consistency test (`tests/test_catalog.py::test_catalog_metrics_match_store_routing`,
> which asserts `catalog_metric_set() == set(_STORE_PROVIDER_OF)`) mean **all six edits must land together** —
> enabling a feature without its store route + catalog spec FAILS the suite. Do A1–A6 in one commit.

### A1. `apps/engine/cosmu/data/providers/store.py` — add to `_STORE_PROVIDER_OF` (before the closing `}`, ~line 292)
```python
    # --- OSINT corporate-intelligence (free, no key, PIT-honest; PER-SYMBOL/equity; NOT market-wide) ---
    "jet_colocation": "jet_colocation",   # corporate-jet co-location intensity (OpenSky); per equity ticker
    "insider_buy_ratio": "sec_edgar",     # Form 4 net insider buy/sell pressure; per equity ticker
```
**Do NOT** add either to `_STORE_MARKET_WIDE` (they are per-symbol).

### A2. `apps/engine/cosmu/data/sources/altdata_bridges.py` — add 2 bridge classes + `__all__` entries
```python
class JetColocationIngestProvider:
    """fetch_series bridge for JetColocationSource (metric=jet_colocation, PER-SYMBOL/equity: scope=ticker)."""

    def __init__(self, *, offline: bool = False) -> None:
        self.offline = offline

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        if metric != "jet_colocation":
            return []
        from cosmu.data.sources.jet_colocation import JetColocationSource

        return _snapshot(JetColocationSource(offline=self.offline), symbol)


class SecEdgarIngestProvider:
    """fetch_series bridge for SecEdgarInsiderSource (metric=insider_buy_ratio, PER-SYMBOL/equity: scope=ticker)."""

    def __init__(self, *, offline: bool = False) -> None:
        self.offline = offline

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        if metric != "insider_buy_ratio":
            return []
        from cosmu.data.sources.sec_edgar import SecEdgarInsiderSource

        return _snapshot(SecEdgarInsiderSource(offline=self.offline), symbol)
```
Add `"JetColocationIngestProvider"`, `"SecEdgarIngestProvider"` to `__all__` (keep it sorted).

### A3. `apps/engine/cosmu/ingest/catalog.py` — add 2 fetch closures + 2 `SourceSpec`s
Fetch closures (near the other `_fetch_*`):
```python
def _fetch_jet_colocation(store: Any, symbols: list[str], providers: Any) -> int:
    return ingest_numeric(store, providers.jet_colocation, symbols, "jet_colocation", provider_name="jet_colocation")


def _fetch_sec_edgar(store: Any, symbols: list[str], providers: Any) -> int:
    return ingest_numeric(store, providers.sec_edgar, symbols, "insider_buy_ratio", provider_name="sec_edgar")
```
In `managed_sources()` `specs` list (per_symbol defaults True — leave it; both are per-symbol/equity):
```python
        SourceSpec("jet_colocation", "alt", ("jet_colocation",), _fetch_jet_colocation, note="OSINT corporate-jet co-location intensity per equity ticker (free OpenSky; per-symbol; PIT T+1; low-confidence)."),
        SourceSpec("sec_edgar", "alt", ("insider_buy_ratio",), _fetch_sec_edgar, note="SEC EDGAR Form 4 net insider buy/sell pressure per equity ticker (free, no key; PIT via acceptanceDateTime; low-confidence)."),
```

### A4. `apps/engine/cosmu/ingest/run.py` — import bridges + add Providers fields
Add to the `from cosmu.data.sources.altdata_bridges import (...)` block:
```python
    JetColocationIngestProvider,
    SecEdgarIngestProvider,
```
Add to the `Providers` dataclass (near the other alt providers):
```python
    jet_colocation: AltDataProvider = field(default_factory=JetColocationIngestProvider)
    sec_edgar: AltDataProvider = field(default_factory=SecEdgarIngestProvider)
```

### A5. `apps/engine/cosmu/data/sources/registry.py` — register in `default_source_registry()` (before `return reg`)
```python
    # OSINT corporate-intelligence (free, no key, PIT-honest, per-equity-ticker; low-confidence — Gate falsifies OOS).
    from cosmu.data.sources.jet_colocation import JetColocationSource
    from cosmu.data.sources.sec_edgar import SecEdgarInsiderSource

    reg.register(JetColocationSource())
    reg.register(SecEdgarInsiderSource())
```

### A6. `apps/engine/cosmu/config/feature_registry.py`
**(a)** Add a NEW entry (near the other OSINT / equity features):
```python
    FeatureDefinition(
        name="jet_colocation", source="opensky", tier="tier1", asset_classes=["equity"],
        asof_semantics="daily co-location count; available_at = obs_day + 1 day 00:00 UTC (>=1-day OpenSky publication lag; no look-ahead); gap / no tracked aircraft => None",
        prior="OSINT corporate-jet co-location: count of days a company's tracked aircraft arrived at the same airport as ANOTHER tracked public company's jet (a deal/M&A/partnership proximity proxy). Causally plausible but very noisy with partial coverage; low-confidence — must earn its place OOS.",
        transform_version="jet-colocation-v1",
    ),
```
**(b)** Replace the EXISTING disabled `insider_buy_ratio` line (~line 80) with the enabled, retiered version:
```python
    FeatureDefinition(name="insider_buy_ratio", source="sec_edgar", tier="tier1", asset_classes=["equity"], asof_semantics="Form 4 acceptanceDateTime; only filings accepted <= as_of are used (no look-ahead); window aggregate available_at = the latest used filing's acceptance time", prior="Net open-market insider buy/sell pressure (Form 4 code P minus S, shares-weighted, in [-1,+1]) over a trailing 90d window. Open-market insider buying is a causally-plausible bullish tell; noisy with partial coverage — low-confidence, must earn its place OOS.", transform_version="sec-edgar-insider-v1"),
```

---

## Step B — QA (run to green)

```bash
source .venv/bin/activate
PYTHONPATH=apps/engine python -m pytest \
  apps/engine/tests/test_catalog.py \
  apps/engine/tests/test_alt_features.py \
  apps/engine/tests/test_data_source_registry.py \
  apps/engine/tests/test_jet_colocation.py \
  apps/engine/tests/test_sec_edgar.py \
  apps/engine/tests/test_bb_width.py -q
```
Then the full deploy-check gate (the `/deploy-check` skill):
```bash
pnpm verify   # naming:check + contracts + engine:test (-n auto) + typecheck + build
```
Engine-only fast loop while iterating: `pnpm engine:test`.

**Likely-only failure modes & fixes:**
- `test_catalog_metrics_match_store_routing` fails → a `_STORE_PROVIDER_OF` key has no matching `SourceSpec` metric (or vice-versa). Make A1 and A3 metric names identical: `jet_colocation`, `insider_buy_ratio`.
- `test_every_enabled_feature_is_routable_or_computed` fails → you enabled a feature_registry entry (A6) without its store route (A1). Land both.
- `test_each_metric_owned_by_one_source` fails → a metric is in two `SourceSpec`s. Each new metric must appear in exactly one.

---

## Step C — Reconcile parallel work + merge

1. `git status` — confirm the `bb_width` parallel work is coherent and the guard tests pass (don't re-add `bb_width`).
2. Decide on `docs/research/ASTRO_ULTIMATE_DEEPDIVE_PLAN.md` (commit or drop).
3. Commit. Suggested message:
   ```
   feat(data): wire 2 OSINT corporate-intel sources — jet co-location + SEC EDGAR Form-4 insider

   - jet_colocation: per-equity-ticker corporate-jet co-location intensity (free OpenSky, PIT T+1, low-confidence)
   - insider_buy_ratio: wires the disabled sec_edgar stub — Form 4 net buy/sell pressure (free, PIT via acceptanceDateTime)
   - both per-symbol/equity, offline-safe, gate-falsifiable; full lock-step (store route + catalog + provider + bridge + registry + feature)
   - also: bb_width bar feature registry entry + Bollinger-squeeze inbox example; ingest_hyperliquid_bars certifi TLS fix
   ```
4. `pnpm verify` green → merge `feat/rho-bar-wiring` → `main` and push (push = deploy). Confirm Vercel/Railway/Modal health after.

---

## Gotchas / invariants (do not break)

- **Gate is LOCKED** — never loosen thresholds. These sources are tier1/low-confidence by design; the Gate is supposed to be able to kill them.
- **No LLM on the data/query path.** These sources are deterministic + offline-safe.
- **PIT honesty is sacred** — gaps return `None`, never `0`; `available_at` is a conservative floor. The tests enforce this; keep them.
- **Parallel-agent collisions:** `feature_registry.py`, `run.py`, `backtest.py` are touched by multiple agents. `git pull`/coordinate before committing; re-run the guard tests after any merge.
- Live data paths (OpenSky, SEC EDGAR) are free + keyless but were NOT exercised live here (offline fixtures only). After merge, a manual `manage-data fetch jet_colocation`/`sec_edgar` (or the Modal ingest cron) will surface real coverage; expect thin/partial coverage initially (honest).
