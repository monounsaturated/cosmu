# Local session handoff — 2026-06-13

> Paste the prompt at the bottom into a **new local Claude Code session** (env.local present, Supabase
> reachable). This doc is the durable copy; the prompt is the short version. Written after the 2026-06-11
> deep-review + fix run (PRs #170–#173, all merged to `main`).

## Where things stand (verified)
- `main` HEAD = `077b25c`. Working branch `claude/focused-hopper-gc7hz9` == `main`. Tree clean.
- Merged this run: **#170** short-fee inversion + ingest idempotency + groom · **#171** forward-test
  honesty (flat funding, screened symbols, champion-only holdout) · **#172** Alpaca equities lane
  (data + paper exec, key-gated OFF) · **#173** stale-source alarm + closed-session equity bars +
  gate-bar drift guard.
- Full report: `docs/reports/deep-review-2026-06-11.md`. Every fix is regression-tested; `pnpm verify`
  was green (1775 passed) at merge.

## Environment (this is a LOCAL session)
- Python **3.12** required (the engine pins `>=3.12`; 3.11 fails install). Make a venv:
  `python3.12 -m venv .venv && .venv/bin/pip install -e "apps/engine[dev]"`.
- `.env.local` is present here — use it for Supabase reads/writes and for reading the prod alt-data store.
  Keys stay server-side; never commit them.
- Tests: `PYTHONPATH=apps/engine .venv/bin/python -m pytest apps/engine/tests -q -n auto`.
- Pre-push gate: `pnpm verify` (naming + contracts-drift + engine tests + typecheck + next build). The full
  build is RAM-heavy on a 16 GB Mac — if it OOMs, run the heavy parts in a cloud session, or
  `pnpm verify:fast` locally (skips `next build`) and let the cloud do the build.
- Branch policy: develop on a feature branch, **never push to `main`**. Open a PR; merge only when green
  (or leave it for the operator to merge).

---

## TASK 1 — Compact the prod `alt_data` store + enforce uniqueness (needs Supabase; THE reason this is local)

**Why:** before #170, the 15-min ingest cron re-appended a full provider window every pass with no dedup, so
`alt_data` accreted exact duplicate rows (~96 copies/day/series since the 2026-06-11 cadence change). #170
stopped *new* duplicates and made reads collapse them, but the **existing** duplicates still sit in prod,
eating the Supabase cap (~6 GB of 8 GB) and inflating the `n_rows` telemetry.

**Compaction deletes only exact `(provider, symbol, metric, ts, available_at)` photocopies — zero information
loss** (a genuine vendor revision has a *different* `available_at` and is kept). Run against Supabase via
`.env.local`:

```sql
-- 0. Measure first (sanity: exact_duplicates should be most of the table)
SELECT count(*) AS total_rows,
       count(*) - count(DISTINCT (provider, symbol, metric, ts, available_at)) AS exact_duplicates
FROM alt_data;

-- 0b. Confirm the dupes are value-identical (this MUST return 0 — same PIT key, different value would be a
--     real in-place revision and would need a human call before deleting):
SELECT count(*) FROM (
  SELECT provider, symbol, metric, ts, available_at
  FROM alt_data GROUP BY 1,2,3,4,5 HAVING count(DISTINCT value) > 1
) x;

-- 1. Delete exact duplicates, keeping the lowest id per PIT key (value is identical, so id choice is cosmetic)
DELETE FROM alt_data a USING alt_data b
WHERE a.provider = b.provider AND a.symbol = b.symbol AND a.metric = b.metric
  AND a.ts = b.ts AND a.available_at = b.available_at AND a.id > b.id;

-- 2. Enforce it forever at the DB layer
CREATE UNIQUE INDEX IF NOT EXISTS uq_alt_data_pit
  ON alt_data (provider, symbol, metric, ts, available_at);

-- 3. Rebuild the freshness rollup from the compacted truth (n_rows was inflated by the dupes)
TRUNCATE alt_data_provider_summary;
INSERT INTO alt_data_provider_summary (provider, metric, n_rows, latest_available_at, latest_value, updated_at)
SELECT provider, metric, count(*),
       max(available_at),
       (array_agg(value ORDER BY available_at DESC))[1]::text,
       now()::text
FROM alt_data GROUP BY provider, metric;

-- 4. Verify
SELECT count(*) AS rows_after,
       count(*) - count(DISTINCT (provider, symbol, metric, ts, available_at)) AS dupes_after  -- expect 0
FROM alt_data;
```

**Then make the code match the DB (a code change, in a PR):**
- Add `uq_alt_data_pit` to BOTH `apps/engine/cosmu/knowledge/schema_postgres.sql` and `.../schema.sql`
  (SQLite dev) so fresh stores get it by construction.
- Make `PgAltDataStore.append` (and the JSONL `AltDataStore.append` path is fine) insert with **`ON CONFLICT
  DO NOTHING`** — otherwise the new unique index will make a racing duplicate insert RAISE instead of being
  a harmless no-op. The `insert_many` helper in `knowledge/store.py` needs an on-conflict variant or a
  dedicated append path. Add a test: re-appending an identical window writes 0 rows and never raises.
- Run the engine tests; open a PR.

> Scalability note the operator raised (store a LOT, well): compaction is not "store less" — it removes only
> photocopies. The real volume plan is the **hot/cold tier** already in BACKLOG (Postgres hot + Parquet on
> Cloudflare R2 / DuckDB cold), to build when the 8 GB cap actually nears. Don't build it now; just unblock
> the cap with the compaction + uniqueness above.

## TASK 2 — Turn on the Alpaca equities lane (needs free Alpaca keys)

The adapters shipped in #172, key-gated OFF. To activate:
1. Operator creates a free account at alpaca.markets → put `ALPACA_PAPER_API_KEY` / `ALPACA_PAPER_API_SECRET`
   in `.env.local` (and on Railway for prod). That alone lights up US-equities market data (IEX,
   dividend-adjusted) + free paper execution. See `docs/KEYS.md`.
2. Code (PR): in `orchestrator/loop.py` `PricingRouter`, prefer `AlpacaDailyBarsProvider.from_settings(...)`
   for the equity leg, falling back to Yahoo when it returns `None` (no keys). Add `alpaca` to
   `spine/universe.py:VENUES_WITH_DATA` once data flows. Grow the `alpaca` instrument list past SPY in
   `spine/venue.py` (mirror the IBKR ETF set). Add a test that the router routes an equity symbol to the
   Alpaca provider when keys are present.
3. Verify a real paper fetch returns dividend-adjusted closed daily bars; then it's ready to forward-test
   equity survivors on a real broker's paper account instead of internal sim.

## TASK 3 — The money move: deep data, then the first honest survivor (heavy; local or Modal)

This is the highest-leverage work — everything above is plumbing in service of it.
1. **Deep backfill** real bars across the wide perp universe + multi-timeframe via `/manage-data` (needs
   live data-API network a cloud agent lacks — hence local/Railway). Then verify coverage.
2. **Re-run the matrix sweep over the ALT-JOINED feature space**:
   `PYTHONPATH=apps/engine .venv/bin/python -m cosmu.research.matrix_search --sweep` (or the Modal lane for a
   full walk-forward). The prior "search exhausted, 0 survivors" verdict only ever searched bar-TA — the
   ~75 alt features (funding/social/macro/on-chain/news) have never been honestly searched. The first real
   edge is most likely here. Route survivors through the deterministic Gate (FDR); ranking ≠ funding.
3. If a survivor clears, it now forward-tests honestly (flat start, screened symbol, champion-only holdout —
   all fixed this run), so its ≥30-day proof actually means something.

---

## Still-open pre-live gates (code-only; can be a cloud session, NOT blocking SIM)
From `docs/reports/deep-review-2026-06-11.md` + the 2026-06-10 review, recorded in `BACKLOG.md`:
- **M1** fill-convention mismatch screen (next-bar open) ↔ executor (latest close) — quantify via
  variance-attribution, align or document per-venue.
- **M2** gap-through stops fill AT the stop (optimistic) + entry-bar stop never checked — fill at
  `min(open, stop)` long / mirror short.
- **M5** FarmLoop's BH family isn't deduplicated (finder is) + the novelty gate fails OPEN
  (`except: return True`) — cluster correlated mutants before BH; make novelty fail CLOSED.
- **M6** `/live/defund` zeroes qty in SQL instead of closing via the order path — dangerous shape if ever
  copied into a live lane.
- **M7/M8** before ANY live wiring: live fills book at intended price (best-effort reconcile only); derive
  `gate_passed` from the store *inside* `execute_orders` instead of trusting the caller's literal.
- Older 2026-06-10 gates: live-exit lane for `reduce_only`, neutral-track funding cliff, dust trap.

## Guardrails (non-negotiable — see AGENTS.md)
- Gate + money path stay deterministic, out of any LLM reach. LLM proposes; the FDR gate disposes.
- Never display synthetic data / never run fixtures in prod. Point-in-time, no look-ahead.
- No magic numbers in specs. Live OFF behind the 5 interlocks. Generated TS from OpenAPI only.
- **Ask the operator first** on: schema changes, new vendor/spend, live-execution changes, broad renames.
- `pnpm verify` before every push. Feature branch + PR. Never push to `main`.

## Housekeeping
- Stale background sub-agents (the "Audit …" entries at 2400m+ in the tasks panel) are orphaned read-only
  auditors from the review run; nothing depends on them. They can't be stopped from a chat session — tick
  their boxes in the background-tasks panel to clear them.
