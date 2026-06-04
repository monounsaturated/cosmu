---
name: manage-data
description: Manage the data layer as a capability — fetch, backfill, verify (coverage report), and update market bars + all alt sources through one idempotent, point-in-time path. Use to pull data, deepen history, or check what we have / what's stale / what's missing.
---

# manage-data

Data is a **managed capability**, not a pile of one-off scripts: one CLI (`scripts/manage_data.py`, engine `cosmu.ingest.manage`) does **fetch / backfill / verify / update** over BOTH the multi-venue bar cache AND the append-only point-in-time alt-data store. Everything is idempotent (dedup on `(provider,symbol,metric,ts)` for alt, on `ts` for bars — a re-run writes 0), point-in-time (`available_at` = when we'd actually have known it; no look-ahead), free where possible (key-gated sources degrade to `[]`), and offline-testable (inject providers; no network in CI).

## When to use
- "Pull / refresh the data" → `update` (one incremental pass over all sources) or `fetch <source>` (one source).
- "Get more history" → `backfill <source> --days N` (paginated deep history).
- "What data do we actually have? what's stale/missing?" → `verify` (the coverage report).

## Commands (run from repo root; `PYTHONPATH=apps/engine` is auto-added by the script)

```bash
python3 scripts/manage_data.py list                              # the managed sources + their metrics
python3 scripts/manage_data.py verify                            # coverage report (text)
python3 scripts/manage_data.py verify --json                     # machine-readable coverage
python3 scripts/manage_data.py verify --symbols BTCUSDT,ETHUSDT --no-bars
python3 scripts/manage_data.py update                            # ONE incremental pass over ALL sources (cron tick)
python3 scripts/manage_data.py fetch funding                     # one source, incremental
python3 scripts/manage_data.py backfill funding --days 730       # ≥1yr paginated funding history
python3 scripts/manage_data.py backfill bars --days 730 --timeframe 1d        # Binance + Kraken OHLCV via ccxt
python3 scripts/manage_data.py backfill bars:kraken --symbols BTCUSDT          # one venue
```

- **fetch `<source>`** — pull ONE source incrementally (`list` shows names: funding, fear_greed, news, macro, defi, risk_on, liquidations, putcall, open_interest, basis, netflow, osint, polymarket_clob, reddit, lunarcrush, xai, venue_fees).
- **backfill `<source>` `--days N`** — deep history. `funding` walks the paginated Binance funding endpoint; `bars`/`bars:<venue>` walks paginated multi-venue OHLCV via ccxt (Binance + Kraken). Other alt sources have no history endpoint → backfill falls back to one incremental fetch (logged).
- **verify** — the data-quality report: per `source/symbol/metric` it reports **row count, span, freshness, gap detection, and a look-ahead integrity check** (`available_at >= ts`), then buckets every series into **ok / stale / gappy / missing / look-ahead**. This is the "what we have / what's stale / what's missing" view.
- **update** — one incremental pass over every source (delegates to `cosmu.ingest.run.run_once`, the single full-sweep implementation — no duplication).

## Coverage report shape
Each series → `{provider, symbol, metric, kind, rows, first_ts, last_ts, span_days, freshness_seconds, cadence_seconds, gaps, missing_buckets, max_gap_seconds, lookahead_violations, status}`. `status` precedence: **missing > look-ahead > stale > gappy > ok**. Stale floors at 3 days but also trips at 3× the series' own cadence (a fast funding series is judged faster than a daily macro series). `--json` emits `{generated_at, summary, series[]}` for tooling.

## Architecture (compose, never duplicate)
- `cosmu/ingest/catalog.py` — the declarative source catalog; the alt-metric set is kept in lock-step with `altdata._STORE_PROVIDER_OF` (a consistency test fails if a source is added to ingest but not the catalog). `expected_alt_specs` / `expected_bar_specs` define what coverage *should* find.
- `cosmu/ingest/coverage.py` — the pure, offline VERIFY engine (clock injected; read-only).
- `cosmu/ingest/manage.py` — `DataManager` + the CLI; composes `run_once` (update), `backfill_funding` + `CcxtBarBackfiller` (backfill), and the coverage engine (verify).
- `cosmu/ingest/bars.py` — `CcxtBarBackfiller` (paginated multi-venue history) + `write_bars_cache` (dedup merge); composes `cosmu/data/market.py` (the live bar providers + `Bar`).

To ADD a source, use the **add-data-source** skill (provider + feature_registry + run_once + `_STORE_PROVIDER_OF`); it then shows up automatically in `verify` and is fetchable by name once added to the catalog.

## Scrape path — sources with NO API (niche sentiment sites, project docs, forum threads)
When a source has no API, do NOT bolt a brittle live scraper into the engine. Use the **standardized agent-scrape seam** (`cosmu/data/sources/scrape_stub.py`) so a scrape flows through the EXACT same ingest / dedup / point-in-time store as every API source:

1. **Fetch + extract (agent step, out-of-band)** — a Claude-Code / Cowork agent opens the page(s) and extracts observations. This is the deliberately-unbuilt step: `stub_scrape(source, symbol, metric, url)` is the documented signature; replace its inert body with the agent call when a specific no-API source is actually needed. Keep extraction to **one numeric `value` per observation** (do the text→number step once, at scrape time — never on the gate path).
2. **Stamp point-in-time** — each row is a `ScrapedRecord` whose **`available_at` = the moment the agent read the page** (NEVER back-dated to the article's own timestamp unless you can prove you'd have seen it then — back-dating manufactures look-ahead). `metric` must be a `feature_registry` name to be gate-usable.
3. **Persist** — `write_scraped_records(scrape_dir, source, records)` appends to `<scrape_dir>/<source>.jsonl` (append-only, same discipline as the alt store).
4. **Ingest** — `ScrapedAltDataProvider(scrape_dir)` serves those rows through the standard `AltDataProvider` seam, so `ingest_numeric(store, provider, symbols, metric, provider_name="scrape")` dedups + stores them point-in-time exactly like funding or fear&greed. A missing scrape dir → `[]` (honest 'no data', never fabricated).

This keeps the messy, non-deterministic scraping OUT of the deterministic engine: the agent produces standardized point-in-time rows; the engine treats them like any other source. Bump `SCRAPE_TRANSFORM_VERSION` when the extraction convention changes so survivors stay reproducible.

## Invariants / guardrails
- Idempotent + point-in-time: re-runs never rewrite the view; backfill of an already-covered window writes 0.
- Each `(source, symbol, window)` is fetched ONCE (providers paginate internally — no redundant external calls).
- ZERO keys required for the free path; key-gated sources (LunarCrush, xAI) degrade to `[]` and report `missing` in `verify` (honest, never a fabricated read).
- ccxt is optional: with no ccxt installed and no injected fetcher, bar backfill returns `[]` (never a fabricated bar).

## Verify (the skill's own check)
```bash
cd apps/engine && python3 -m pytest tests/test_manage_data.py tests/test_coverage.py tests/test_bar_backfill.py tests/test_catalog.py tests/test_scrape_stub.py -q
```
