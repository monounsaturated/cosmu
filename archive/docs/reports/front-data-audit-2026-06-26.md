# Front ↔ DB ↔ Backend coherence audit — "the paper strategies seem to NOT be trading"

**Date:** 2026-06-26
**Scope:** READ-ONLY. Prod DB (Supabase) + prod API (`https://cosmu.up.railway.app`) + web data path (`apps/web`). No writes, no money moved, no merges.
**Operator concern:** *the 10 paper strategies seem to NOT be trading — front display bug? previous trades not shown?*

---

## TL;DR — VERDICT

**MOSTLY NORMAL, with two small real DISPLAY bugs (neither is the headline concern).**

1. **The 10 paper strategies HAVE traded and ARE shown.** Each has 1–7 real paper fills in the `executions` ledger; the API surfaces them with correct equity / P&L / trade-count; `has_paper_fills=true`, so they pass the front's Paper filter. This is **NOT** a "paper not trading" bug and **NOT** a wiring bug.
2. **Why it *looks* like nothing is happening = NORMAL.** These are **monthly TAA rotation** strategies (DAA/VAA/ADM/GEM/Faber/PAA/TSMOM/RiskParity/Sector/DualMom). All current fills are the **initial entry buys stamped 2026-06-14 18:13**. A monthly strategy funded mid-June rebalances ~mid-July, so **zero new fills over the last ~12 days is expected**. Equity still moves daily via mark-to-market (marks are fresh to 2026-06-26 08:52). The forward clock IS stepping.
3. **DISPLAY BUG #1 (cosmetic, advisory):** future TAA rebalances will update `positions` (via `apply_fill`) but **NOT** add rows to `executions`. The front trade-count + fill blotter read `executions`, so the **trade count will stay frozen** at the 06-14 backfill number even after the strategies genuinely rotate next month. Equity/P&L stays correct; only the trade list goes stale.
4. **DISPLAY BUG #2 (overview hero curve):** `/overview` returns the **OLDEST** 120 aggregate snapshots (`ORDER BY ts ASC LIMIT 120`), so the Overview equity curve is permanently pinned to 2026-06-02 → 06-07 and never advances, even though fresh aggregate snapshots exist through 2026-06-26. The aggregate hero curve looks "stuck."
5. **Minor data gap:** 1 of the 10 paper versions (`Dual Momentum (QQQ/EFA tech-tilt)`) is **absent from the live `/leaderboard` API** despite being valid in the DB — the deployed engine returns only 75 of 200 eligible rows, a sign the **deployed Railway revision is older than `origin/main`** (see §5).

The operator's instinct ("previous trades not shown?") is partially right for the **trade-count dimension going forward** (Bug #1) and for the **Overview curve** (Bug #2), but the core read — "paper strategies aren't trading" — is **NORMAL** monthly-rebalance behaviour, not a broken executor.

---

## 1. DB TRUTH — real trade counts per paper track

Source tables (confirmed): `executions` (the fill ledger; `is_paper=1`), `positions` (held legs via `apply_fill`), `portfolio_snapshots` (marks; `scope='track'` + `scope='aggregate'`), `events` (cadence). There is **no** separate `orders`/`trades`/`sim_fills` table.

`strategy_versions` status distribution: **killed 1370 · screened 77 · paper 10**.

| Strategy (status=paper) | paper fills (`executions`, is_paper=1) | first fill | last fill | marked equity | last mark |
|---|---:|---|---|---:|---|
| Protective Asset Allocation (PAA1 top-6) | 7 | 2026-06-14 18:13 | 2026-06-14 18:13 | $1004.48 | 2026-06-26 08:52 |
| Defensive Asset Allocation (DAA top-6) | 6 | 2026-06-14 18:13 | 2026-06-14 18:13 | $1015.97 | 2026-06-26 08:52 |
| Diversified TSMOM Trend (5-ETF) | 5 | 2026-06-14 18:13 | 2026-06-14 18:13 | $994.93 | 2026-06-26 08:52 |
| Faber GTAA (5-asset 10mo SMA) | 5 | 2026-06-14 18:13 | 2026-06-14 18:13 | $990.10 | 2026-06-26 08:52 |
| Risk Parity (Inverse-Vol SPY/AGG/GLD) | 3 | 2026-06-14 18:13 | 2026-06-14 18:13 | $998.33 | 2026-06-26 08:52 |
| Sector-Momentum Rotation (TAA) | 3 | 2026-06-14 18:13 | 2026-06-14 18:13 | $995.17 | 2026-06-26 08:52 |
| Accelerating Dual Momentum (ADM) | 1 | 2026-06-14 18:13 | 2026-06-14 18:13 | $1000.00 | 2026-06-26 08:12 |
| Dual Momentum (QQQ/EFA tech-tilt) | 1 | 2026-06-14 18:13 | 2026-06-14 18:13 | $1000.00 | 2026-06-26 08:12 |
| Global Equities Momentum (GEM) | 1 | 2026-06-14 18:13 | 2026-06-14 18:13 | $1000.00 | 2026-06-26 08:12 |
| Vigilant Asset Allocation (VAA-G4) | 1 | 2026-06-14 18:13 | 2026-06-14 18:13 | $1000.00 | 2026-06-26 08:12 |

Whole-DB `executions`: **43 paper fills total**, first 2026-06-02, **last 2026-06-14 18:13** — i.e. **no fill anywhere since 06-14**. Fill rows are all `side='buy'` on IBKR equity instruments (e.g. DAA: agg/eem/efa/lqd/qqq/spy) — the **initial allocation entry**, not rotations.

### Is zero-new-fills NORMAL?

**Yes.** These are documented **monthly** rotation arms (spec `horizon.min_hold_days=21, max_hold_days=31`; rationale literally says "monthly"). The fill count (1–7) matches the number of legs each portfolio holds, i.e. the one-time entry. A monthly strategy entered ~06-14 next rebalances ~07-14. Marks moving daily (equity 990–1016, P&L ±) confirm the positions are live and being re-priced. **The executor is not silently dead.**

### How the 06-14 fills got into `executions` (and why future ones won't)

The TAA arms open positions through `Portfolio.apply_fill()` which writes **only the `positions` table** — never `executions`. The `executions` rows exist because a **one-shot, idempotent backfill** ran on 06-14:

- `orchestrator/loop.py :: kickstart_paper_fills()` — for every `screened` version that *holds* positions but has *zero* paper fills, it logs one paper execution per open leg (mirroring the held qty/basis) and promotes it `screened → paper`. Its `NOT EXISTS (… executions …)` guard makes it a **no-op once a version has any fill**.

Consequence: this backfill will **never run again** for these versions. The next monthly rebalance (`equity_*_arm.arm()` → `apply_fill` + `arm_rotation.close_stale_legs`) updates `positions` and marks, but **adds nothing to `executions`** → the front trade count is frozen. (This is **Bug #1**.)

### Forward clock IS stepping (cadence evidence)

`events` in last 24h: `tracks_marked` (last 06-26 08:52), `paper_stepped` (last 06-26 08:13), `autonomy_tick_*`, `drift_assessed`, `paper_started`/`track_opened` (06-26 00:22 — the *crypto/explore* cohort re-arm). The Modal `tick` (every 4h) runs `cosmu.research.arm_fleet` (re-arm/advance TAA) + `cosmu.orchestrator.loop` (mark) — `remote/app.py:206-216`. So the TAA clock is advanced; it just hasn't hit a monthly rotation boundary. (Note: `paper_stepped` is logged once per tick with `ref_id='aggregate'`, so it can't be used to prove a *specific* version stepped — that's an event-granularity limitation, not a bug.)

---

## 2. FRONT DATA PATH — endpoints the web app calls

- Web client → same-origin Next proxy `/api/engine/[...path]` (injects `API_SECRET_KEY` server-side; secret never reaches browser) → `${API_BASE_URL}` = `https://cosmu.up.railway.app`. **Front→backend base is correct** (`apps/web/lib/engine.ts`, `.env.local` `NEXT_PUBLIC_API_BASE_URL`/`API_BASE_URL`).
- `/paper` page (`apps/web/app/paper/page.tsx`) calls `getLeaderboard()` + `getOverview()`, then filters with `isPaperRow` (`apps/web/lib/utils.ts:56`): **`isPaper(status) && has_paper_fills === true`**. So a paper-status strategy with **no real fill is hidden** from the Paper dashboard by design (reads "Backtest" instead). For these 10 it passes (all have fills).
- `/overview`, `/leaderboard`, `/strategies/{id}` are the relevant routers (`apps/engine/cosmu/api/routers/`). The leaderboard `has_paper_fills`/`paper_trades` columns and the detail blotter both read the **same `executions` ledger** — one source of truth.

---

## 3. CORROBORATION — does the API match the DB?

**Yes, exactly, for what it returns.** Live `/leaderboard` (read-only) returned the 9 surfaced paper rows with trade-count, `value_usd`, `pnl_usd`, `paper_return_pct` **identical to the DB** (e.g. DAA trades=6 value=$1015.97 pnl=+$15.97; Faber trades=5 value=$990.10 pnl=−$9.90). `/strategies/{DAA}` detail returned the same 6 buy fills (all 06-14), `has_paper_fills=true`, value present. **No DB↔API divergence on the rows that are present.** Not a wiring bug.

---

## 4. DISPLAY BUG #2 — Overview hero curve frozen at 06-07

`/overview` (`routers/overview.py:23`):
```
store.rows("SELECT ts, pnl FROM portfolio_snapshots WHERE scope = 'aggregate' ORDER BY ts ASC LIMIT 120")
```
`scope='aggregate'` snapshots run **06-02 → 06-26** (292 rows, fresh). But `ORDER BY ts ASC LIMIT 120` takes the **oldest** 120 → the returned curve ends **2026-06-07** (verified live: 120 points, last ts 06-07, value 10000.0). The Overview equity hero is therefore permanently pinned to the first 5 days and never advances. **Fix:** return the most-recent window (e.g. `ORDER BY ts DESC LIMIT N` then reverse) or downsample the full range. This is on `origin/main`, not just stale prod.

---

## 5. Minor gap — 1 paper version missing from the live leaderboard + deploy staleness

`Dual Momentum (QQQ/EFA tech-tilt)` (`5629a3a2…`) is `status=paper`, has a valid backtest (DSR 0.465) and 1 fill in the DB, and `derive_facets` parses its spec cleanly — yet it is **absent from the live `/leaderboard`** (API returns **75** rows: 66 screened + 9 paper). The current-branch query (`LIMIT 200`, killed-last) would include it at distinct-rank 76 and return ~200 rows. The deployed engine returning only 75 (vs 87 non-killed versions alone) indicates the **deployed Railway revision is older than `origin/main`** and uses a tighter cut. Action: redeploy the engine to `origin/main` and re-check; if QQQ still drops, inspect the per-row `try/except` build for documented-arm specs. Low urgency (single strategy; equity/marks unaffected).

---

## Recommended fixes (priority order, NOT applied here)

1. **Bug #1 (trade-count freeze)** — make TAA rebalances write to `executions`, not only `positions`. Options: route `arm()`/`close_stale_legs` fills through the order path that logs executions, OR (cheaper) re-run a guarded `kickstart`-style reconcile each tick that appends *new* legs to the ledger. Until then the trade count is honest-at-entry but stale-going-forward.
2. **Bug #2 (Overview curve)** — `routers/overview.py:23` `ORDER BY ts ASC LIMIT 120` → most-recent window.
3. **Deploy staleness** — redeploy engine to `origin/main`; confirm the QQQ paper row reappears and leaderboard returns the full set.

## What is FINE (do not touch)

- The Paper dashboard's `has_paper_fills` gate (correct, honest — hides un-traded arms by design).
- The marks / forward clock (fresh, stepping every 4h via Modal `tick`).
- Front→backend base URL + same-origin secret-injecting proxy.
- DB↔API agreement on equity / P&L / trade count for surfaced rows.

---

### Method note
Read `DATABASE_URL` from `<repo>/.env.local` (stripped inline `#…` comment + `?pgbouncer=true`), connected `psycopg2` in `set_session(readonly=True)`. Hit prod API read-only with `X-API-Key`. No writes; no files under `<repo>` touched.
