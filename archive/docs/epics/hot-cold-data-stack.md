# Hot/cold data stack — Postgres (hot) + Parquet/DuckDB/R2 (cold)

> Realigns to `VISION.md`: *"history lives in the columnar catalog; Postgres is control-plane + money-truth
> ONLY, never row-per-bar."* Status: **Phase 1 shipped** (the cold-tier store + export + tests, default OFF —
> zero behaviour change). Phases 2–3 are operator-gated (need a Cloudflare R2 token).

## The problem (measured on prod, 2026-06-13)
`alt_data` is **99.6 %** of the 6.58 GB Supabase DB; the rest of the control plane is ~13 MB. And it's the
wrong *shape* for Postgres:

| alt_data in Postgres | size |
|---|---|
| heap (the data) | 2735 MB |
| **indexes** (4 btrees) | **3819 MB** — *1.4× the data* |
| **total** | **6555 MB** |

A time-series hoard indexed 4× per row is structurally expensive in an OLTP store, and the 8 GB Supabase cap
binds on indexes you don't need for analytical scans.

## The benchmark (the whole argument in one line)
Exporting all **13,566,067 rows** of prod `alt_data` to Parquet:

| | size | note |
|---|---|---|
| Postgres `alt_data` | **6555 MB** | heap + 4 indexes |
| **Parquet lake** | **71 MB** | **~92× smaller**, columnar, no btrees |
| export time | **51 s** | DuckDB postgres-scanner, one COPY |
| R2 cost @ 71 MB | **~$0.001/mo** | zero egress |

Read-back parity verified on real series (fred/vix_level, defillama/defi_tvl, binance funding) — `read_asof`
is **byte-identical** to `PgAltDataStore`.

## Architecture — use both
- **HOT — Supabase Postgres:** the control plane (strategies, versions, tracks, gate_verdicts, events,
  portfolio — ~13 MB) + (Phase 2) a *recent* alt window for the live gate's low-latency PIT reads. Money-truth.
- **COLD — R2 + Parquet + DuckDB:** the full alt-data + (later) bars hoard, append-only Parquet on R2, scanned
  by embedded DuckDB. This is "hoard everything + analyze big-data-first." Cheap, scales to TB, no egress.

## What shipped (Phase 1)
- `data/providers/parquet_store.py` — `ParquetAltDataStore`: same `append`/`read_asof`/`read_all` as
  `PgAltDataStore` (PIT-identical; ISO-8601 TEXT timestamps mirror the PG table), Hive-partitioned
  `provider=…/metric=…`, local dir **or** `r2://bucket` (DuckDB-native R2 secret, no boto3). `compact()` merges
  append-files.
- `data/alt_join.py::resolve_alt_store` — routes to the cold tier when `alt_data_backend == "parquet"`.
- `data/export_alt_parquet.py` — one-shot PG/SQLite → partitioned Parquet migration (DuckDB ATTACH + COPY).
- Settings: `alt_data_backend` (`pg` default), `alt_data_parquet_root`, `R2_*` creds (gated like Alpaca).
- `[lake]` extra (`duckdb`) — opt-in, so the Railway image stays lean.
- `tests/test_parquet_cold_tier.py` — read_asof/read_all parity vs Postgres, append, compact, routing.

## Cost (lean-startup framing)
| | Supabase Pro | Cloudflare R2 |
|---|---|---|
| price | **$25/mo**, hard cap 8 GB | **~$0.015/GB/mo**, no cap |
| egress | included but capped tier | **$0 (zero egress)** |
| 24 GB hoard | overage / tier bump | **~$0.36/mo** |
| role | hot control-plane + money-truth | the data lake |

Keep Supabase for what it's good at (transactional truth); let R2 be the hoard. Net: stay lean, scale data
without scaling cost.

## Operator migration (Phase 2 — when you're ready)
1. Create a Cloudflare R2 bucket (e.g. `cosmu-lake`) + an API token (Account ID + Access Key + Secret).
2. Put `R2_ACCOUNT_ID` / `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` / `R2_BUCKET` in `.env.local` (and Railway).
3. Install the extra where the migration/backend runs: `pip install -e "apps/engine[lake]"`.
4. Export the hoard: `PYTHONPATH=apps/engine python -m cosmu.data.export_alt_parquet` (→ R2 when keyed).
5. Flip `ALT_DATA_BACKEND=parquet`. The gate/finder/sweep read from the lake (backend-agnostic via the seam).
6. (Optional) Once verified, stop writing alt_data to Postgres → the DB drops to ~13 MB + the recent hot window.

## Phase 3 (later)
- A *recent hot window* in Postgres for the live gate (last ~90 d) so live PIT reads stay sub-ms while the full
  history lives cold; a daily `compact()` cron on the lake; move OHLC bars into the same Parquet catalog
  (Nautilus-style) per VISION. DuckDB becomes the analytical engine for sweeps (Modal/local).
