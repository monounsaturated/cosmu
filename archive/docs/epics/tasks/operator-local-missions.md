# Operator missions — local machine / .env.local / dashboards (compiled 2026-06-11)

> For the OPERATOR (or the next LOCAL agent with network + creds a cloud session lacks).
> Source of truth for keys: `docs/KEYS.md` · setup walkthrough: `docs/OWNER_SETUP.md` · backlog: `BACKLOG.md`.

## P0 — required by work just merged

1. **Apply the two 2026-06-11 migrations in Supabase** (after this branch deploys) — open the SQL
   editor and run, in either order (both idempotent):
   - `apps/engine/cosmu/knowledge/migrations/2026-06-11_forward_test_to_paper.sql` — finishes the
     paper rename (until then readers tolerate both values; nothing breaks).
   - `apps/engine/cosmu/knowledge/migrations/2026-06-11_strategy_blocks.sql` — creates the
     building-block registry tables (until then the engine detects their absence and the registry
     cleanly no-ops: no dedup, no block lineage).
   A later cleanup PR drops the legacy `forward_test` read-fallbacks once this has run.
2. **Confirm `API_SECRET_KEY` matches on Railway AND Vercel** — the engine enforces it now; a
   mismatch 401s the web proxy. (BACKLOG operator action.)
3. **Vercel env: add `NEXT_PUBLIC_API_BASE_URL`** if still missing (OWNER_SETUP §F.3) — without it the
   client-side interactive panels can't reach the engine. `ENGINE_API_URL` is unused — delete it.


> ⚠️ COMPANION FILE on main (from the realtime session, PR #168): `docs/epics/tasks/local-agent-post-merge-actions.md`
> — it carries the realtime DDL blocks, voices registration, 1m backfill, event-study run, cron checks.
> The local agent should execute BOTH files in one session: that one first (post-merge realtime actions),
> then this one (paper/blocks migrations + keys + QA). Note: this branch's vocabulary rename means any
> main-side code merged AFTER it must say `paper`, never `forward_test` — the naming guard enforces it.

## P0.5 — QA pass (the local agent CAN and SHOULD test end-to-end with .env.local)

- **Engine locally:** `pip install -e "apps/engine[dev]"` (Python ≥3.12) → `pnpm engine:api` → hit
  `http://127.0.0.1:8000/health`, `/leaderboard`, `/population`, `/blocks` (expect `available:false`
  until the strategy_blocks migration runs — that's the honest no-op, not a bug).
- **Web locally:** `pnpm dev` → check `/strategies`, `/paper` (the renamed page), `/forward-test`
  (must redirect to /paper), `/live`, `/costs` — all should render honest states against the local engine.
- **Tests:** `PYTHONPATH=apps/engine python3 -m pytest apps/engine/tests -n auto -q` (1693 green as of
  2026-06-11) and `pnpm verify:fast` before any push.
- **Supabase edits:** the agent has write access via the SQL editor creds — run the migrations listed
  in P0 + the DDL blocks from the companion file, then verify with the queries each file provides
  (e.g. `SELECT status, COUNT(*) FROM strategy_versions GROUP BY status` should show `paper`, no
  `forward_test`, after the rename migration).

## P1 — the honest-edge path (need live network/creds, cheap)

4. **.env.local (local dev)** — make sure it carries:
   `FRED_API_KEY` (free, fredaccount.stlouisfed.org — unblocks the macro feature),
   `OPENROUTER_API_KEY` (optional ~$5, the preferred LLM gateway), plus the standard
   `API_BASE_URL` / `NEXT_PUBLIC_API_BASE_URL` / `API_SECRET_KEY` / `DATABASE_URL`.
   NO Binance keys anywhere while validating — the adapter resolves to `disabled` → honest sim-fills.
5. **Run the deep backfill + activate all FREE sources** via `/manage-data` (local or Railway —
   needs data-API network): the #1 unblock for the wide-universe gate re-run. (BACKLOG "Now".)
6. **Re-run the matrix sweep over the ALT-JOINED feature space**:
   `python3 -m cosmu.research.matrix_search --sweep` locally or via Modal. The previous
   "0 survivors" verdict never searched the ~75 alt features. (BACKLOG operator action.)
7. **Set `AUTONOMY_CRON_ENABLED` on Railway to taste** (default ON, sim-only) and verify the 4 crons
   fire: ingest 6h · tick 4h · paper clock 22:10 · arm-fleet 22:40. (BACKLOG operator action.)
8. **Check the prod trials ledger for synthetic pollution**:
   `SELECT source, COUNT(*) FROM trials GROUP BY source` — eyeball for fixture/demo sources.

## P2 — when wanted

9. **First end-to-end Modal run** — `pnpm modal:secret` (syncs .env.local → Modal secret
   `cosmu-engine`) then `pnpm modal:gate`; confirm it writes to Supabase. Note: the Modal job
   `forward_mark` is now `paper_mark` (legacy alias still accepted).
10. **Real-time lane** — being handled in a separate chat (epic: `docs/epics/realtime-data-lane.md`).
    Do NOT duplicate here; the operator-side part will be: confirming the new cron cadences on Railway
    and watching Supabase growth (§5 of the epic).
11. **LunarCrush $15 Builder mega-grab** (optional, when wanted) — see BACKLOG for the exact command;
    grab → store → CANCEL.
12. **Go-live prerequisites checklist** (only after a real Gate PASS + ≥30 paper days): add real
    `BINANCE_API_KEY/SECRET` on Railway, then the 2-click Live modal. The 5 interlocks stay the hard gate.
    Reminder: the PRE-LIVE gates in BACKLOG (bar-cache freshness · live-exit lane · fill-convention ·
    funding cliff · dust trap) MUST land first — none are done yet.
