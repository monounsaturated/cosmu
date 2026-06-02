# Cosmu — Coding Standards

> Copy-paste templates for common patterns. Follow these exactly.

## Module header
Every file in `cosmu/` opens with:
```python
# intent: <purpose> · inputs: <what> · outputs: <what> · invariants: <what must hold>
```

## Adding a data source
1. **Provider class** in `cosmu/data/altdata.py`: stdlib `urllib.request` + `_ssl_context()` (certifi), implements `AltDataProvider` protocol (`fetch_series(symbol, metric, *, limit) -> list[AltDataPoint]`). Point-in-time: `available_at` = when we'd have known it (typically `ts + timedelta(days=1)` for daily sources). Handle errors → return `[]`.
2. **Feature** in `cosmu/config/feature_registry.py`: name, tier (tier0/tier1), source, one-line prior hypothesis, pinned `transform_version`.
3. **Ingest** in `cosmu/ingest/run.py`: add field to `Providers` dataclass, add `_safe()`-wrapped call in `run_once()`. Market-wide metrics use `ingest_market_wide_numeric` under the `"MARKET"` key.
4. **Store routing** in `cosmu/data/altdata.py`: add metric → provider name in `_STORE_PROVIDER_OF`. If market-wide, add to `_STORE_MARKET_WIDE`.
5. **Test** in `tests/test_<source>.py`: canned fixture (no network), assert point-in-time lag, assert wrong-metric returns `[]`, assert ingest works.

## Adding a venue / asset class
1. **DataAdapter** in `cosmu/adapters/data/<venue>.py`: implement `core/interfaces.py` `DataAdapter` protocol.
2. **ExecutionAdapter** (optional) in `cosmu/adapters/exec/<venue>.py`: implement `ExecutionAdapter`.
3. **VenueCatalog** entry in `cosmu/spine/venue.py`.
4. **Universe gate** in `cosmu/spine/universe.py`: `VENUES_WITH_DATA` / `CLASSES_WITH_DATA`.
5. **Test** with offline fixtures.

## Tests
- File: `tests/test_<area>.py`
- Deterministic + offline: inject providers, mock HTTP, canned fixtures
- Assert scorer/money path makes ZERO LLM calls where relevant
- Each new module ships its test

## Persistence
- Truth = typed Postgres table via `knowledge/store.py` `Store`
- Every irreversible act → append `events` ledger row (same transaction)
- Web types = generated `@cosmu/contracts-ts` from FastAPI OpenAPI (never hand-type)
- Regenerate: `cd apps/engine && python3 -c "from cosmu.api.app import app; import json; print(json.dumps(app.openapi()))" > /tmp/openapi.json`

## LLM / tool integration
- One gateway = OpenRouter, model IDs from `cosmu/lab/router.py` config
- Structured output: Pydantic `extra="forbid"` validation
- LLM PROPOSES structure only — never scores, never moves money
- Tools live on the read/propose-only bus (`lab/tools/`). Execution is NEVER on the bus.
- Key server-side only. Offline fixture so CI runs with no key/network.
