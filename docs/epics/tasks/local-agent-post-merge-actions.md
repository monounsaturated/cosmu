# Task: post-merge actions for the LOCAL agent (has `.env.local` + network)

> Launch: LOCAL Claude Code session on the operator's machine (needs `.env.local` creds — a cloud agent
> cannot run these). Context: PR #168 (realtime-data-lane P0+P1+P2) merged to main on 2026-06-11.
> Read `docs/epics/realtime-data-lane.md` first. Work top to bottom; each step is independent and idempotent.

## 1. Apply the new Postgres DDL on Supabase (REQUIRED — prod tables don't exist until this runs)
The PG schema applies out-of-band. Run the three new blocks from
`apps/engine/cosmu/knowledge/schema_postgres.sql` against the production Supabase DB:
- `market_events` (+ its two indexes)
- `voice_claims` (+ its index)
- `voice_scoreboard`

Either paste them in the Supabase SQL editor, or run them via psql with the `DATABASE_URL` from
`.env.local`. All are `create table if not exists` — re-running is safe. VERIFY:
`SELECT COUNT(*) FROM market_events; SELECT COUNT(*) FROM voice_claims; SELECT COUNT(*) FROM voice_scoreboard;`
(zeros are the expected honest state).

## 2. Register the first voices (the credibility panel ships EMPTY by design)
Edit `apps/engine/cosmu/config/voices.py` → `VOICE_PANEL`. One line per voice with a one-line `why`
written BEFORE any outcome is known (pre-registration = the anti-survivorship discipline; never add an
account because a post aged well). Commit + push on a branch → PR. The hourly `voices_pass` cron starts
filling the scoreboard on the next tick after merge. X voices need `XAI_API_KEY` on Railway (already
there per MASTER_PLAN); Reddit/RSS voices are keyless.

## 3. Backfill 1m bars for event-study experiment 1 (heavy download — local or Modal, never Railway)
```bash
cd apps/engine
PYTHONPATH=. python3 -m cosmu.data.binance_vision_backfill \
  BTCUSDT ETHUSDT SOLUSDT BNBUSDT XRPUSDT --spot \
  --start 2023-01-01 --end 2026-06-10 --timeframes 1m
```
Free, no key (data.binance.vision static archive). Idempotent — a re-run writes 0.

## 4. Run pre-registered event-study experiment 1 (news → majors on minute bars)
The GDELT GKG corpus (115k items, 2023→2026) lives on the Modal volume from the llm-narrative run
(`apps/engine/remote/gkg_narrative.py` built it). Export/locate it as JSONL with one
`{ts, title, symbol|symbols, source}` per line, then:
```bash
PYTHONPATH=apps/engine python3 -m cosmu.research.event_study_run \
  --corpus <gkg_majors.jsonl> --availability publish-time \
  --bars-dir .cosmu/market_data/binancevision --timeframe 1m \
  --symbols BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT \
  --out docs/runs/event_study_exp1.json
```
Heavy → run on Modal/local, NOT a Railway cron. The verdict table prints per-cell: mean SCAR per window,
RI p-value, pre-window leakage flag, FDR pass/fail/insufficient. An honest FAIL or INSUFFICIENT is a
valid, bankable result — record it in `docs/DECISIONS.md` either way. If any cell PASSES: per the
locked light-gate decision (epic §8), bring the result back to the operator before authoring specs.

## 5. Verify the deployed crons fire (Railway dashboard or logs)
After the merge deploys: ingest `*/15` · forward-test clock `10 0` + `10 22` · hourly `5 * * * *`
(`--intraday`) · voices `25 * * * *` · re-arm `40 22`. Acceptance (epic P0): `tracks.updated_at` never
older than ~70 min. Also confirm the paid-LLM throttle works: `xai` / `llm_index` rows in
`alt_data_provider_summary` should advance ~hourly, NOT every 15 min.

## 6. Optional same-session: Polymarket CLOB backfill (event experiment 2 prerequisite)
```bash
cd apps/engine && PYTHONPATH=. python3 -m cosmu.ingest.run --provider polymarket_clob --backfill-days 365
```
(Per `polymarket_backfill_coverage.md` — never run in prod; needs live network.)

Delete this file once all steps are done (it's a launch prompt, not documentation).
