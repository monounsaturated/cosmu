# Cosmu v2 — Data Index

Reference for where everything lives, how to connect, and what each table/prefix contains.

---

## Rule of Thumb

| What | Where | Why |
|------|-------|-----|
| Business state + last hot window (≤30d alt_data) | **Supabase** (309 MB Free tier) | Low-latency reads for the engine, API, paper loop |
| Full history + Parquet lake + PG backups + research | **R2** `cosmu-lake` bucket | Cheap bulk storage; read via DuckDB / boto3 |

**Alt-data cut-line**: `alt_lake_watermark` row `alt_data` holds the last synced `available_at`. Everything older than that date (2026-06-14) lives ONLY in R2 `alt_lake/`. The Supabase `alt_data` table keeps a rolling 30-day hot window for the engine's `read_asof`.

---

## Supabase Connection Footgun

The `.env.local` `DATABASE_URL` contains two params that BREAK direct psycopg2 connections:

1. **Trailing `# comment`** — strip everything after the `#`.
2. **`pgbouncer=true`** query param — remove it (PgBouncer is a pooler proxy on port 6543; psycopg2 needs the direct Postgres port).
3. **Port 6543 → 5432** — for any DDL (`ALTER TABLE`, `CREATE INDEX`, `ANALYZE`) use port **5432** (direct). Port 6543 is the PgBouncer pooler (fine for queries, FATAL for DDL due to missing `SET` commands).

```python
# Safe connection string builder
import re
raw = os.environ["DATABASE_URL"]
url = re.sub(r'#.*', '', raw).strip()          # strip comment
url = re.sub(r'[?&]pgbouncer=true', '', url)   # remove pgbouncer param
url = re.sub(r'[?&]$', '', url)                # clean trailing ? or &
url = url.replace(':6543/', ':5432/')           # DDL port
```

---

## Supabase Table Reference

> Tables matching `ducklake_%` (about 40) are DuckDB catalog bookkeeping for the cold-tier DuckLake. Filter them with `WHERE table_name NOT LIKE 'ducklake_%'` in any `information_schema` query — they are not business tables.

### Control-plane (strategy authoring & lifecycle)

| Table | Description |
|-------|-------------|
| `strategies` | One row per named strategy (the idea, not a parameterization) |
| `strategy_versions` | Every parameterized version of a strategy; `status`, `kind` (quant/llm), `authored_by` |
| `version_combos` | `combo_hash` per version — structural dedup so the same hypothesis is never re-screened |
| `version_blocks` | Per-block decomposition (signal/filter/setup/exit/sizing) keyed to `version_combos` |
| `strategy_blocks` | Content-hashed reusable building blocks with `kind` + `label` |
| `strategy_promotions` | FROZEN gate-survivor snapshot: `params_hash`, `fee_model_snapshot`, `gate_score` — what live replicates exactly |

### Backtest & gate

| Table | Description |
|-------|-------------|
| `backtests` | One row per gate run: DSR, PBO, holdout, per-symbol JSON, cost assumptions |
| `backtest_symbols` | Per-(backtest × symbol) breakdown — the honest, non-pooled visibility row. `equity_curve_json` is a **recomputable cache** (the API rebuilds it from spec/bars on view) pruned to a ~1-day keep-window by `cosmu.data.backtest_curve_retention` so it stops TOASTing to hundreds of MB; the scalars (return/sharpe/dd/verdict) are permanent |
| `gate_verdicts` | Every gate pass/fail logged for the UI |
| `trials` | Global multiple-testing ledger (trial count for BH-FDR deflation) |
| `holdout_ledger` | One-shot holdout: each version may be evaluated exactly once |
| `rejects_watch` | Gate-rejected-but-close candidates zero-capital paper-tracked (Type-II rate measurement) |
| `correlation_findings` | PIT IC scan results — propose-only, NEVER consulted by the Gate |

### Lifecycle / money

| Table | Description |
|-------|-------------|
| `tracks` | One forward-proof cell per (strategy_version × symbol × venue); `equity`, `return_pct`, `target_vol` |
| `portfolio_snapshots` | Equity curve snapshots per scope/ref |
| `positions` | Open sim/live positions marked-to-market; net-zero rows kept for audit |
| `executions` | Every fill (paper and live); `is_paper` flag |
| `runs` | Sim/live run boundaries |
| `live_caps` | Per-scope hard position/loss caps (the money interlock) |
| `live_toggle` | Single `global` row — live arm interlock (0 = all orders blocked) |
| `costs` | Vendor compute cost ledger (USD-canonical; see `operating_costs.py`) |
| `events` | Append-only actor/kind event bus (discovery, gate, arm, error events) |

### Universe / venue

| Table | Description |
|-------|-------------|
| `universe_pairs` | All tradable pairs across all venues: `venue`, `symbol`, `asset_class`, `instrument_type`, `tier` (0/1/2), `liquidity_usd_24h`, `multiplier` (futures only — USD/EUR per price point per contract), `listed_at`/`delisted_at` (PIT survivorship) |
| `venues` | Small catalog of execution venues with `kind`, `adapter`, `fee_schedule` |
| `instruments` | Small curated execution catalog (what the engine executes against); distinct from `universe_pairs` |

### Alt-data (hot window)

| Table | Description |
|-------|-------------|
| `alt_data` | Append-only PIT series (provider, symbol, metric, ts, available_at, value). **Never full-count** — 13.6M+ rows; always filter by provider/symbol/metric + `available_at` range. The hot window is the last 30 days; older rows are in R2 `alt_lake/` |
| `alt_data_provider_summary` | Coverage cheat-sheet: per-(provider, metric) `n_rows`, `latest_available_at`, `latest_value`. **Use this for freshness checks** instead of `COUNT(*)` on `alt_data` |
| `alt_lake_watermark` | Single-row watermark: `last_available_at` = the sync boundary between Supabase hot and R2 cold. Rows older than this date exist ONLY in R2 |

### LLM / research

| Table | Description |
|-------|-------------|
| `research_notes` | Per-version notes, graveyard entries, and structured research; `embedding` column for RAG |
| `llm_calls` | Metered LLM call ledger (tokens, cost, model, account_id) |
| `mind_reflections` | Agent's PIT market reads (consensus, conviction, agreement) — memory, never money |
| `model_accounts` | Failover router registry: one row per OpenRouter/xAI key with spend + status |
| `llm_work_units` | Work-unit persistence for mid-call crash recovery |
| `experiments` | Reproducibility ledger: every finder/gate run with seed + data_version + metrics |
| `indexes` | Operator-defined composite series (rubric definitions); VALUES in `alt_data` metric `idx_<id>` |

---

## R2 Bucket: `cosmu-lake`

Access via boto3 with endpoint `https://<ACCOUNT_ID>.r2.cloudflarestorage.com` (creds in `.env.local` as `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` / `R2_ACCOUNT_ID`).

| Prefix | Contents | Key pattern |
|--------|----------|-------------|
| `alt_data/` | Raw Parquet exports of alt_data rows | `alt_data/<provider>/<YYYY-MM>/<metric>.parquet` |
| `alt_lake/` | DuckLake full history (13.5M rows; replaces the pruned Supabase rows) | `alt_lake/<provider>/<metric>/<ts>.parquet` (DuckDB catalog via `ducklake_%` tables) |
| `backups/pg/` | Daily pg_dump backups (gzipped plain SQL) | `backups/pg/YYYY-MM-DD_cosmu.sql.gz` |
| `universe/` | Daily universe_pairs snapshots + latest | `universe/YYYY-MM-DD.json`, `universe/latest.json` |
| `astro_lab/` | Astrology research outputs (ephemeris panels, IC matrices) | `astro_lab/<study>/<date>/...` |
| `research_registry/` | Strategy research output blobs (gate run artifacts, scan_signals results) | `research_registry/<run_id>/...` |

---

## Common Queries

```sql
-- How fresh is the ingest fleet?
SELECT provider, metric, latest_available_at, n_rows
FROM alt_data_provider_summary
ORDER BY latest_available_at DESC
LIMIT 40;

-- IBKR universe by asset class and instrument type
SELECT asset_class, instrument_type, COUNT(*), COUNT(multiplier) AS has_multiplier
FROM universe_pairs
WHERE venue = 'ibkr'
GROUP BY asset_class, instrument_type
ORDER BY COUNT(*) DESC;

-- Futures with multipliers
SELECT symbol, quote, multiplier
FROM universe_pairs
WHERE venue = 'ibkr' AND instrument_type = 'future'
ORDER BY symbol;

-- All venues, pair counts
SELECT venue, asset_class, COUNT(*) AS n
FROM universe_pairs
WHERE active = 1
GROUP BY venue, asset_class
ORDER BY n DESC;
```
