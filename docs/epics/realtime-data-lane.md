# EPIC — Real-time data lane (bots live · data live · marks live)

> Status: PROPOSED (2026-06-11, operator-requested). Owner: operator + next engine session.
> North star fit: this is the single biggest latency unlock between "the machine knows" and
> "the machine acts". Goal stated by the operator: *bots that react very quickly to news,
> Polymarket, tweets — smart, with access to quality data — to make money asap.*

## 1. Problem

Everything in the deployed loop is **cron-shaped, not stream-shaped**. Measured reality today:

| Loop | Cadence | Effect on latency |
|---|---|---|
| Alt-data ingest (`cosmu.research.loop --ingest`) | every 6h | a news/funding/sentiment shift is seen 0–6h late |
| Autonomy tick (author → gate → fund) | every 4h | new specs wait up to 4h |
| Paper executor (`orchestrator/paper_step.py`) | daily 22:10 UTC | paper bots act **once a day** |
| Arm-fleet rotation re-arm | daily 22:40 UTC | rotation legs move once a day |
| Mark-to-market | daily (inside the 22:10 clock) | dashboards/"24h perf" are stale up to 24h |

Market bars are 1h/4h/1d pulled on demand (ccxt/yfinance), no websockets, no always-on worker.
Worst-case reaction time to an external event: **~24h**. Target: **seconds-to-minutes** for the
sources that justify it.

## 2. Target (tiered — each tier is shippable and useful alone)

| Tier | What changes | Reaction latency | Incremental cost / mo (estimate — verify before buying) |
|---|---|---|---|
| **0 — today** | nothing | 6–24h | $0 |
| **1 — fast crons** | ingest cron 6h → 15min · NEW hourly mark-to-market cron · hourly executor lane for intraday-horizon specs | 15–60 min | ~$2–5 (Railway cron compute only; all sources stay free) |
| **2 — always-on worker** | one small always-on Railway service: Binance WS (trades/klines), Polymarket WS, short-poll collectors (RSS/Reddit/CryptoPanic 1–5 min) · 1m/5m bar store with retention · event-driven executor trigger on bar close | seconds (market) · 1–5 min (news/social proxies) | ~$5–15 worker + ~$0–25 Supabase growth (within Pro 8 GB; see §5) · data $0 |
| **3 — paid real-time social** | X/Twitter API (Basic ~$200/mo — verify current pricing), LunarCrush paid tier (~$24–240), CryptoPanic Pro | seconds (social) | ~$230–450 — **only when live net profit justifies it** |

Recommended path: **ship Tier 1 immediately** (pure config + one small cron), build Tier 2 as this
epic's core, hold Tier 3 behind a profit gate (e.g. trailing-30d live net P&L > 2× the social spend).

## 3. Architecture (Tier 2 core)

```
                ┌────────────────────────────────────────────┐
                │  cosmu.realtime.worker  (Railway, always-on)│
                │                                            │
  Binance WS ──▶│  ws consumers (reconnect+backoff, dedup)   │
  Polymarket WS▶│  poll collectors (RSS/Reddit/CryptoPanic)  │──▶ alt_data (PIT: available_at = receipt ts)
                │  bar builder (1m/5m → bars store)          │──▶ bars_intraday (retention, §5)
                │  heartbeat → events table every 60s        │──▶ event bus: "bar_closed" / "source_updated"
                └────────────────────────────────────────────┘
                                   │
                                   ▼
                  executor trigger (intraday lane): on bar_closed for a
                  symbol×timeframe with an active intraday track → run the
                  SAME paper_step path (one order path, real fees, slippage)
```

Principles (non-negotiable, inherited from AGENTS.md):
- **One order path.** The intraday lane calls the existing `paper_step` / `execute_orders`
  gauntlet — no second execution code path, sim and live identical, kill-switch checked every tick.
- **PIT honesty.** `available_at` = wall-clock receipt time, never the event's claimed time.
  A real-time source has **no trustworthy backfilled history** — it must accumulate recorded-live
  history before the Gate may use it (`/profile-source` GO/REVIEW/NO-GO applies). Never synthesize
  history retroactively.
- **Crons stay as the fallback lane.** The worker degrades to "cron-only" cleanly: if the worker
  dies, nothing breaks — freshness just decays to Tier-1 levels. Worker health is visible
  (heartbeat events; stale heartbeat = badge on the web Strategies page, not a silent failure).
- **LLMs stay out of the hot path.** Real-time data feeds *features*; the deterministic
  spec/Gate machinery decides. No "LLM reads a tweet and fires an order", ever.

## 4. What this epic explicitly unblocks

- **Honest "24h perf"** per strategy on the web (needs hourly marks at minimum — Tier 1).
- **Intraday strategies** (1m/5m/15m horizons) in backtest AND paper with matching cadence —
  today a 1h-bar spec executed daily is a fill-convention lie (see BACKLOG pre-live gate on
  fill-convention alignment; this epic must not widen that gap).
- **News/Polymarket/social reaction strategies** — the operator's stated goal. These become
  *authorable* only once their feeds are minutes-fresh and have weeks of recorded-live history.
- Faster web dashboards (fresh marks) without any frontend change.

## 5. Storage & load math (why this is safe)

- 1m bars × ~30 symbols ≈ 43k rows/day ≈ **1.3M rows/mo** (~150–300 MB/mo with indexes).
  Retention: keep 1m for 90 days, roll up to 5m/1h beyond → bounded. Tick data is **out of scope**.
- Poll collectors at 1–5 min on free APIs stay within published rate limits (Reddit, RSS,
  CryptoPanic free tier); add per-source jitter + budget guard (skip-and-log, never hammer).
- Supabase Pro headroom is ~2 GB today (6/8 GB used) — fine for months; the hot/cold tiering
  item in BACKLOG ("archive to parquet on R2") is the long-term relief valve, not a blocker.

## 6. Tech-debt & risk register (eyes open — a daemon is a commitment)

| Risk | Mitigation |
|---|---|
| WS disconnects / silent staleness | reconnect with exponential backoff; staleness watchdog flips the source's freshness badge; heartbeat events |
| Duplicate/missed messages on reconnect | idempotent writes keyed (provider, symbol, metric, ts); resume from last stored ts |
| Memory leaks in a long-lived process | bounded queues; restart-safe (Railway restarts are normal, not incidents) |
| Railway worker cost creep | one small instance, scale-to-zero stays for Modal; alert if monthly compute > budget line in `costs` |
| In-progress candle decisions | only act on **closed** bars (the bar-cache freshness PRE-LIVE gate in BACKLOG.md is a hard prerequisite for the executor lane) |
| Two execution cadences (daily + intraday) diverging | both lanes call the same `paper_step` path; per-spec `horizon.bar_size` decides the lane — no per-lane logic forks |

## 7. Phases & acceptance criteria

- **P1 (Tier 1, ~½ day):** ingest cron 15min · hourly mark cron · web shows fresh "24h" deltas.
  ✓ when: `tracks.updated_at` never older than 70 min while Railway is up.
- **P2 (worker + market WS, the core):** `cosmu.realtime.worker` deployed · Binance WS klines →
  1m/5m bar store with retention · heartbeat + staleness badges.
  ✓ when: a 5m bar is queryable < 30s after close, 7 consecutive days, zero manual restarts.
- **P3 (fast alt-data + event-driven executor):** Polymarket WS + RSS/Reddit/CryptoPanic 1–5 min ·
  `bar_closed` triggers the intraday executor lane through the one order path.
  ✓ when: an intraday paper track reacts to a signal within one bar period, with fills logged
  through the standard gauntlet (fees + slippage), and the daily lane is untouched.
- **P4 (paid social, profit-gated):** X API / LunarCrush evaluation behind the profit gate in §2.
  ✓ when: a `/profile-source` GO verdict on ≥30 days of recorded-live history before any spec uses it.

## 8. Dependencies / ordering

1. **PRE-LIVE gate: bar-cache freshness fix** (BACKLOG) — prerequisite for any executor cadence increase.
2. **Live/sim split in the backend** (BACKLOG, redesign prerequisite) — independent, but lands in the
   same season; the worker should write marks tagged by mode from day one.
3. Fill-convention alignment (BACKLOG) — quantify before adding intraday lanes.

## 9. Out of scope

HFT, order-book/microstructure strategies, colocation, tick storage, any paid feed before the
profit gate, and any LLM in the order path.
