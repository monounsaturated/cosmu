---
name: add-data-source
description: Wire a new point-in-time alt-data source (free or paid) into the ingest pipeline and feature registry. Use when adding a data feed, API, or signal source (funding, sentiment, on-chain, macro, OSINT, etc.).
---

# add-data-source

Add a real, point-in-time data source behind the alt-data seam. Everything stays offline-testable (inject providers; no network in CI) and **point-in-time** (`available_at` = when we'd actually have known it — no look-ahead).

## Steps (mirror `docs/CODING_STANDARDS.md` "Adding a data source")
1. **Provider class** in `cosmu/data/altdata.py`: stdlib `urllib.request` + `_ssl_context()` (certifi). Implement the `AltDataProvider` protocol: `fetch_series(symbol, metric, *, limit) -> list[AltDataPoint]`. Set `available_at` (typically `ts + timedelta(days=1)` for daily sources). Errors → return `[]` (one dead source never aborts the run).
2. **Feature** in `cosmu/config/feature_registry.py`: name, tier (tier0/tier1), source, a one-line prior hypothesis, pinned `transform_version`. Low-confidence/speculative sources start tier1 with a small confidence and "must earn via OOS".
3. **Ingest** in `cosmu/ingest/run.py`: add the field to `Providers`, add a `_safe()`-wrapped call in `run_once()`. Market-wide metrics use `ingest_market_wide_numeric` under the `"MARKET"` key.
4. **Store routing** in `cosmu/data/altdata.py`: add metric → provider in `_STORE_PROVIDER_OF`; if market-wide, add to `_STORE_MARKET_WIDE`.
5. **Test** in `tests/test_<source>.py`: canned fixture (no network), assert the point-in-time lag, assert wrong-metric → `[]`, assert ingest works.
6. **Audit before you trust it** — run **profile-source** on the freshly-ingested feed (`python3 -m cosmu.ingest.profile_source <provider> <symbol> <metric> --declared-lag-hours N`). It must be **GO** (or a consciously-accepted **REVIEW**) before the feed is allowed to shape the gate; a **NO-GO** (look-ahead leak or a dishonest PIT lag) means fix the `available_at` stamping first.

## Keys / cost
- Free sources: no key. Paid (LunarCrush/Tavily-style): read the key server-side from settings; with no key the provider returns `[]` and the system degrades honestly. Never commit secrets.

## Verify
- `cd apps/engine && python3 -m pytest tests/test_<source>.py tests/test_ingest.py -q`
- The feature is referenceable from a spec and joins point-in-time in `data/backtest.py` (`align_asof`).
