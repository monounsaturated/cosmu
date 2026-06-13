# Task: cosmu.realtime.worker — the always-on Tier-2 service (realtime-data-lane epic P3)

> Launch: cloud session, opus, own branch. Read `AGENTS.md` then `docs/epics/realtime-data-lane.md`
> (§2 Tier 2, §3, §6, §7, §10 P3) first. This is the epic's core build.

## Deliverables
1. **`apps/engine/cosmu/realtime/worker.py`** — one always-on asyncio process (a SECOND Railway service;
   add `apps/engine/railway.worker.toml` or document the service config — startCommand
   `python3 -m cosmu.realtime.worker`):
   - **Binance WS klines consumer** (1m) for the configured universe → on candle CLOSE, append to the
     existing bar cache via the `cosmu.ingest.bars` write path (closed bars only — the data/market guard
     stays the single contract). Reconnect with exponential backoff + jitter; resume-safe (idempotent
     merge on ts); a dropped connection degrades to the Tier-1 crons, never crashes the loop.
   - **Poll collectors** (RSS / Reddit / CryptoPanic at 1–5 min with per-source jitter + a BUDGET GUARD:
     per-source min-interval + daily call budget; on exhaustion skip-and-log, never hammer) → raw items
     into `market_events` (data/events_store.PgEventsStore; available_at = receipt time) → enrichment via
     `ingest.llm_formatter.enrich_market_events` (key-gated, lexicon fallback) → derived numeric counts
     into `alt_data`.
   - **Polymarket WS** (or 1-min REST poll if WS is gnarly — justify) → `pm_implied_prob` ticks into
     alt_data + prob-velocity events into market_events.
   - **Heartbeat:** an `events` row (kind="realtime_heartbeat", payload: per-consumer lag/staleness)
     every 60s. The web Strategies page shows a staleness badge when the last heartbeat is > 5 min old
     (read via an existing or tiny new endpoint — generated contracts only).
2. **Retention:** a daily task inside the worker (or a cron) enforcing the epic's bar retention
   (1m kept 90 days, rolled up to 5m/1h beyond) on the worker-written caches/tables.
3. **Bounded memory:** queues with maxlen; no unbounded dict growth; the process is restart-safe
   (Railway restart = normal, state rebuilt from the stores).
4. **Tests:** offline + deterministic — inject WS frames / poll fetchers; test reconnect/backoff logic,
   closed-candle-only writes, dedup on resume, budget-guard skip, heartbeat emission. NO network in CI.

## Invariants (do not violate)
- The worker NEVER executes orders. It records. The executor lanes stay cron/event-triggered through the
  ONE order path (`orchestrator/forward_step.py`).
- `available_at` = receipt time for everything it writes. Closed bars only. No zero-fill, no fabrication.
- If the worker dies, nothing breaks — freshness decays to Tier-1 (the crons remain configured).
- New spend: the worker instance itself (~$5–15/mo) was approved in the epic; anything beyond needs the
  operator (AGENTS.md ask-first).
- `pnpm verify` before push; feature branch + PR; never push to main.
