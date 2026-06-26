# Modal ↔ Railway resilience / cross-fallback — assessment + design

**Date:** 2026-06-26 · **Mode:** READ-ONLY assessment, no money-path code, do-not-merge PR
**Question (operator):** Can we add a FALLBACK for the canary + other vital Modal jobs → Railway? And vice-versa
(Railway vital stuff → Modal)? Feasible? Cost? What would it do? Is it SMART?

---

## TL;DR verdict

- **Feasible: yes, cheaply — and one direction is genuinely worth doing now.**
- **The single high-value move is a Railway-side cross-monitor of Modal** (the "watcher needs a watcher").
  Today the heartbeat dead-man's-switch runs *on the very Modal app it watches* — so **if Modal goes fully dark,
  nothing notices.** That is the real single-point-of-failure. A ~40-line in-process loop on the always-on
  Railway engine closes it for **$0 net new cost** (no new schedule, no new service, no new dependency for the
  DB signals).
- **The reciprocal (Modal watches Railway) is real but lower-value** and is *partially free as a side-effect* of
  the same cross-monitor design — I'd add it as a 3-line check inside the existing hourly Modal heartbeat, not
  as new infra.
- **A true compute FAILOVER** (Railway actually *runs* the backup/ingest when Modal dies, or vice-versa) is
  **over-engineering right now** — skip it. The valuable thing is **detection**, not **takeover**: the jobs are
  idempotent and a missed run is recoverable by hand once you're *paged*. Detection is 95% of the value at 5% of
  the cost.

**Bottom line: build the Railway→Modal cross-monitor (the watcher's watcher). Skip the failover. ~half a day,
$0/mo.**

---

## 1. The vital jobs and their single-point-of-failure TODAY

The cron fleet (`apps/engine/remote/app.py`) is 5 Modal schedules (Modal Free hard-caps schedules at 5):

| Job | Cadence | What it protects | If it dies silently today… |
|-----|---------|------------------|----------------------------|
| `ingest` | hourly (`0 * * * *`) | free alt-data freshness + R2 bar hoard | the heartbeat's `ingest` signal pages (≤3h) — **covered, as long as the heartbeat itself runs** |
| `tick` | every 4h (`0 */4 * * *`) | discovery + paper clock + cohort re-arm + capital-guard monitor | heartbeat `tick`/`mark`/`exec` signals page (9–30h) — **covered, same caveat** |
| `heartbeat` | hourly (`30 * * * *`) | **the dead-man's-switch itself** | **NOTHING notices.** This is the hole. |
| `cold_tier_maintenance` | weekly (Mon 06:00) | alt_data → R2 age-out | not safety-critical; a missed week is recoverable |
| `daily_backup` | daily (05:00) | the *only* money-truth backup (Supabase Free has no managed backups) | heartbeat `backup` signal pages (≤30h) — **covered, same caveat** |

The pattern: **four of the five jobs are watched by the heartbeat, but the heartbeat is watched by nobody.**
The module says so itself (`cosmu/ops/heartbeat.py`, header):

> *CAVEAT: this probe runs ON the same Modal app it watches, so it catches "a job ran but wrote nothing" and
> "one job died" — not a total Modal outage.*

So the live failure modes that go **completely silent today**:

1. **Total Modal outage / app eviction / token rotation** → every cron stops, *including the heartbeat*, so no
   page ever fires. The fleet is dark and the only symptom is stale dashboards — exactly the ~10-day silent
   Railway-cron death this whole module was built to prevent, just relocated to Modal.
2. **Modal Free schedule eviction** (Modal has historically pruned Free-tier schedules) — same silent class.
3. **The heartbeat function specifically erroring every run** (e.g. a Slack webhook rotation + a DB read
   regression) — it exits non-zero on Modal but if you're not watching Modal's run-failure emails, no page.

Note the existing **Railway side** is much simpler: Railway runs **only** the always-on uvicorn API
(`railway.toml` → `python -m uvicorn cosmu.api.app:app`; the file explicitly documents *"scheduling is owned by
Modal, not Railway"*). There are **no Railway crons** anymore — so "Railway vital stuff" is really just the API
process. Its liveness is already covered by Railway's own `healthcheckPath = /health` + restart policy, and a
hard down emits a Slack `down` on lifespan shutdown (`_lifespan.py`). So **Railway is already
self-monitored to a first approximation; Modal is not.** That asymmetry is the whole story.

---

## 2. Why a cross-monitor is the right shape (and failover is not)

The instinct is "fallback = the other platform takes over the job." For this system that's the wrong instinct:

- **The jobs are idempotent and recoverable by hand.** A missed `daily_backup` is one `modal run … daily_backup`
  away once you know. A missed `ingest`/`tick` self-heals on the next run. There is **no money path** in any of
  these (SIM-only by invariant) — so a few hours of staleness costs *nothing* except dashboard freshness. The
  expensive outcome is **not noticing for days**, not the missed run itself.
- Therefore the asset worth buying is **detection latency**, not **redundant execution**. A cross-monitor buys
  detection for ~$0. A failover buys redundant execution for real money + real complexity (duplicate
  scheduling, double-write races, a second pg_dump path, keeping two images in sync) — and a far worse failure
  mode: a *split-brain* where both platforms think they own the backup and you get races or double-spend.

**The key insight to evaluate (operator's #4): a CROSS-MONITOR — each platform checks the OTHER's liveness +
the backup — is the cheapest high-value resilience.** Confirmed. It is the right design. The minimal version
below.

---

## 3. Direction A — Railway → Modal cross-monitor (BUILD THIS)

**Goal:** the always-on Railway engine independently verifies the Modal fleet is alive + the backup is fresh,
and pages if Modal went dark. This is the watcher's watcher.

### Why it's nearly free and nearly trivial

The heartbeat's `check()` is **already a pure read of shared state** — it reads DB freshness
(`alt_data.ingested_at`, `events` rows, `autonomy_status().last_tick_at`) + R2 object age. **None of those
signals care where `check()` runs.** Modal writes them; Railway reads the same Supabase + the same R2 bucket.
So the *exact same* `cosmu.ops.heartbeat.check()` run from Railway detects a total Modal outage that the
Modal-resident heartbeat structurally cannot.

What's already in place on Railway that makes this a near-clone, not new infra:

- An always-on FastAPI process with a **lifespan that already spawns a supervised in-process background task**
  (the realtime worker, `_lifespan.py` + `realtime/worker.py`) — off by default behind an env flag, restarted
  with backoff, writing a periodic heartbeat to the events ledger. **This is the exact pattern** a Modal-monitor
  loop would copy.
- `SlackNotifier` (`cosmu/notify/slack.py`) — same paging path the Modal heartbeat uses.
- `settings.railway_api_token` / `api_secret_key` / `slack_webhook_url` already exist as engine settings; the
  DB + R2 creds are already in the Railway env.
- **Proof the cross-platform API pattern works from the engine:** `cosmu/costs/fetchers.py` already calls
  Railway's GraphQL billing API and shells `modal usage` — so polling a remote platform from inside the engine
  is a solved, tested pattern in this codebase.

### The minimal design (in-process loop — recommended)

A new `_modal_cross_monitor_task` in the FastAPI lifespan, mirroring `realtime/worker.py::_heartbeat_task`:

```
every 30 min, on Railway:
    report = cosmu.ops.heartbeat.check(store)     # the SAME pure check, run from Railway
    if not report["ok"]:
        SlackNotifier.send(":red_circle: MODAL FLEET DARK (seen from Railway) — <stale signals>")
```

- **Lives in:** `apps/engine/cosmu/api/_lifespan.py` (spawn the task) + a tiny new
  `cosmu/ops/modal_watch.py` (the loop + dedup-once-per-stale-window, so it never spams).
- **Gated behind** an env flag (e.g. `MODAL_WATCH_ENABLED=1`), exactly like `REALTIME_WORKER_ENABLED`, so it
  ships dark and is flipped on deliberately — consistent with the lean-infra house style.
- **Dedup:** page once per stale episode (reuse the heartbeat's "stale set" diffing idea), so a long Modal
  outage is one ping, not 48.

**This is strictly additive to the Modal heartbeat — keep both.** The Modal-resident one catches partial
death ("one job wrote nothing") *faster and from inside*; the Railway one catches *total* Modal death the
inside one can't see. Belt and suspenders, and they share one `check()` so they can never drift.

### One real dependency wrinkle (the backup signal)

`heartbeat.check()`'s `backup` signal probes R2 via **`boto3`**, which is in the engine's `[ops]` extra and is
**NOT installed on the Railway image** (`pip install .` skips extras; Dockerfile confirmed). On Railway today
the R2 probe would hit its `except` and return `None` → which the heartbeat treats as **stale → page** (a false
positive on every run). Two clean options:

1. **Add `boto3` to the Railway image** (move it from `[ops]` into base deps, or install `.[ops]`). boto3 is a
   pure-Python wheel, ~adds a few MB to the image and ~nothing to memory. Then the Railway monitor checks
   backup-freshness too — **fully closing the loop**. *Recommended.*
2. **Or** have the Railway monitor check **only the DB signals** (ingest/tick/mark/exec — zero new deps, pure
   psycopg2) and leave backup-freshness to the Modal-resident heartbeat. Cheaper, but then a backup-only failure
   that coincides with a total Modal outage goes unseen. *Acceptable fallback if you want zero image change.*

Given the backup is *the single money-truth artifact on Supabase Free*, option 1 (add boto3) is worth the few MB.

### Cost — Direction A

| Item | Cost |
|------|------|
| Compute | **$0** — runs inside the existing always-on Railway process (no new replica, no new service). A 30-min read of ~5 cheap queries + one R2 `list_objects` is negligible CPU/RAM. |
| Modal schedule slots | **$0** — sidesteps the Free 5-schedule cap entirely (this is the elegant part: the watcher's watcher lives on the platform *with* spare always-on capacity, not the platform that's slot-capped). |
| Dependency | **+`boto3` (~few MB image)** if you want the backup signal (option 1), else $0. |
| Engineering | ~half a day: new `modal_watch.py` loop + lifespan wiring + a couple of tests (clone the realtime-worker heartbeat tests). |

**SMART? Yes — clearly.** It removes the one genuinely silent failure mode (total Modal death) at ~$0, reuses
the existing `check()` (no drift), and respects the slot cap by putting the watcher where the spare capacity is.

---

## 4. Direction B — Modal → Railway cross-monitor (do the cheap version only)

**Goal:** if the Railway engine API dies, does anything on Modal notice? Today: **partially.** Railway's own
`/health` healthcheck + restart policy + the lifespan `down` Slack on shutdown cover a *clean* down, but a
**hung-but-not-crashed** API (e.g. event-loop wedged, pool exhausted, healthcheck passing on a stale process)
would not page.

**Minimal reciprocal check (recommended form):** add **~3 lines to the existing hourly Modal `heartbeat`
function** — no new schedule (respects the 5-slot cap), no new service:

```
# inside the Modal heartbeat run(), after the fleet check:
GET https://<railway-engine>/health   (COSMU_BARS_URL already points at the Railway engine)
if not 200 within timeout:
    SlackNotifier.send(":red_circle: Railway engine /health unreachable from Modal")
```

- **Lives in:** `cosmu/ops/heartbeat.py` (extend `run()`), driven by the existing Modal `heartbeat` cron.
- **Free:** no new slot, no new dep (stdlib `urllib`, same as `costs/fetchers.py`). `COSMU_BARS_URL` (the Railway
  engine URL) is already in the Modal secret.
- Catches the case Railway's own healthcheck can't fully cover (external reachability + a hung process that
  still 200s would still be caught indirectly by the *DB-staleness* signals if the wedge stops writes).

**Why not more than this:** Railway is already largely self-monitored (healthcheck + restart + shutdown-Slack),
so the marginal value of a Modal-side Railway watcher is small. A 3-line `/health` ping inside the existing cron
is the right amount of effort; a dedicated Modal schedule or failover for Railway would be over-engineering.

### Cost — Direction B

| Item | Cost |
|------|------|
| Compute / slots / deps | **$0** — folded into the existing hourly Modal heartbeat, stdlib only, no 6th schedule. |
| Engineering | ~1–2 hours: extend `run()` + one test. |

**SMART? Marginally — yes, because it's nearly free.** It's a 3-line addition riding an existing cron. Worth
doing *with* Direction A, not on its own.

---

## 5. What NOT to build (explicit over-engineering list)

- **Actual compute failover** (Railway runs the pg_dump / ingest when Modal is dark, or Modal runs the API when
  Railway is down). Cost: real engineering (duplicate scheduling, double-write/split-brain races, a second
  pg_dump path, two images kept in lockstep) for a problem (a missed *recoverable, idempotent, SIM-only* run)
  that a page already solves by hand in minutes. **Skip.**
- **A second Modal app to add a 6th "monitor" schedule.** Unnecessary — the watcher belongs on Railway (spare
  always-on capacity), which is *why* the cross-monitor is the elegant fit for the 5-slot cap.
- **A third-party uptime service (e.g. an external pinger).** Adds a vendor + a secret for what one in-process
  loop + one `/health` ping already cover. Revisit only if you ever want *off-stack* monitoring (i.e. something
  that survives both Modal AND Railway being down — but if both are down, the system is down and you'll notice).

---

## 6. The smartest minimal cross-fallback — where each piece lives

```
        ┌─────────────────────────── Supabase (shared state) ───────────────────────────┐
        │  alt_data.ingested_at · events(tracks_marked/paper_stepped) · autonomy tick    │
        └───────────────▲───────────────────────────────────────────────▲───────────────┘
                writes  │                                         reads  │
        ┌───────────────┴───────────────┐                 ┌───────────────┴───────────────┐
        │   MODAL  (5-slot cron fleet)  │                 │   RAILWAY  (always-on API)     │
        │                               │                 │                               │
        │  • ingest / tick / backup /   │   GET /health   │  • uvicorn API + /health       │
        │    cold_tier                  │ ───────────────▶│  • [NEW] modal_watch loop:     │
        │  • heartbeat (watches the     │  (Direction B,  │    every 30m run               │
        │    fleet FROM INSIDE)         │   3 lines in    │    heartbeat.check() FROM HERE │
        │  • [NEW] +/health ping of     │   the existing  │    → page if Modal dark        │
        │    Railway (Direction B)      │   Modal cron)   │    (Direction A — the hole fix)│
        └───────────────────────────────┘                 └───────────────────────────────┘
                          │                                               │
                          └──────────────── Slack (one paging path) ──────┘
                       backup freshness ⇄ R2 (read by both check()s)
```

- **Direction A (the load-bearing piece):** `cosmu/ops/modal_watch.py` (new) + a lifespan task in
  `apps/engine/cosmu/api/_lifespan.py`, reusing `cosmu.ops.heartbeat.check()`. Gated `MODAL_WATCH_ENABLED`.
  Add `boto3` to the Railway image for the backup signal.
- **Direction B (the cheap reciprocal):** ~3 lines in `cosmu/ops/heartbeat.py::run()` doing a stdlib `/health`
  GET against `COSMU_BARS_URL`, riding the existing hourly Modal heartbeat cron.
- **Shared by design:** one `check()`, one `SlackNotifier`, one Slack channel → the two watchers can never drift.

---

## 7. Worth-it-now? — honest call

| | Verdict | Cost | Effort |
|---|---|---|---|
| **A. Railway → Modal cross-monitor** | **BUILD NOW.** Closes the only truly-silent failure (total Modal death = the watcher's watcher). | **$0/mo** (+ few-MB boto3 in image) | ~half a day |
| **B. Modal → Railway `/health` ping** | **Add alongside A** (it's ~free). | **$0/mo** | ~1–2 h |
| **Compute failover (either way)** | **Don't.** Over-engineering — detection already solves the recoverable, SIM-only, idempotent jobs. | n/a | n/a |

**Net:** the minimal cross-monitor is **clearly worth doing now** — it's the cheapest high-value resilience in
the whole stack (one silent-death mode removed for $0), and it's a near-clone of code that already exists
(realtime worker's supervised heartbeat loop + the heartbeat's pure `check()`). The failover layer is a trap;
skip it until there's a *money path* in the crons (there isn't — they're SIM-only by invariant), at which point
revisit. The slot-cap constraint *favors* this design: the watcher rides Railway's spare always-on capacity,
sidestepping Modal Free's 5-schedule ceiling entirely.

---

### Appendix — files read for this assessment (all paths absolute under repo root)

- `apps/engine/remote/app.py` — the 5-cron Modal fleet (ingest/tick/heartbeat/cold_tier/daily_backup) + slot cap
- `apps/engine/cosmu/ops/heartbeat.py` — the dead-man's-switch; pure `check()`; the on-Modal caveat
- `apps/engine/cosmu/data/pg_backup.py` — the daily R2 backup (Supabase Free has no managed backups)
- `apps/engine/railway.toml` + `Procfile` + `Dockerfile` — Railway runs only the always-on uvicorn API; no crons; no extras installed
- `apps/engine/cosmu/api/app.py` + `_lifespan.py` — the always-on process + the supervised in-process worker pattern + `/health`
- `apps/engine/cosmu/api/routers/health.py` — static `/health` (the reciprocal ping target)
- `apps/engine/cosmu/notify/slack.py` — the shared paging path
- `apps/engine/cosmu/realtime/worker.py` — the in-process supervised-heartbeat pattern the monitor clones
- `apps/engine/cosmu/costs/fetchers.py` — proof the engine already polls Railway GraphQL + `modal usage` (cross-platform API pattern is solved here)
- `apps/engine/cosmu/config/settings.py` — `railway_api_token` / `api_secret_key` / `slack_webhook_url` settings
- `apps/engine/pyproject.toml` — base deps vs `[ops]` (boto3) / `[remote]` (modal) extras → the Railway-image dependency wrinkle
- `docs/COMPUTE.md` — the Modal/Railway hybrid decision + spend model
- `.env.local` (read-only, creds not reproduced) — confirmed `MODAL_TOKEN_*`, `RAILWAY_TOKEN`, `VERCEL_TOKEN`, `SLACK_WEBHOOK_URL`, `COSMU_BARS_URL`, `DATABASE_URL` all present
