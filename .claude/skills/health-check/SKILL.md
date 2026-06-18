---
name: health-check
description: Spot-check that a paper-traded cell (strategy_version × symbol × venue) is actually alive — its clock is stepping, it's trading (real fills), and its fees match the venue. Read-only diagnostic; never moves money, no engine change. Use when the operator says "hi" / "health check" to sanity-check a random paper cell.
---

# health-check

The operator pings "hi" and wants to know one thing: **are the paper cells actually working, or just sitting there?** This skill picks ONE random active paper cell — a `(strategy_version × symbol × venue)` triplet — and proves it is (1) **stepping** (the paper clock advanced), (2) **trading** (real fills on the ledger, not stuck flat), (3) **sane** (a fill or two matches the spec's entry intent), and (4) **priced right** (the fill's fee matches the cell's venue `cost_inputs()`), then surfaces the fee bps + venue so the human can eyeball it.

In COSMU **paper = forward test** (one step): `orchestrator/paper_step.py::step_tracks` runs each track's own spec forward, fills through the ONE order path (`master/execution.py`), marks via `orchestrator/loop.py::mark_tracks` (the paper clock → `tracks.updated_at`), fees from `spine/venue.py::default_catalog().venue(v).cost_inputs()`.

**Read-only.** It only LOOKS — never funds, defunds, sizes, routes, or migrates. Out of the gate path and the money path. Cheap by design: ONE random cell (up to 3). It reads the local `.env.local` → prod DB read-only (the engine's `_pg_dsn` strips the `pgbouncer`/`connection_limit` params that break libpq).

## When to use
- The operator says "hi" / "health check" / "are the paper cells alive?" — a fast spot-check, not a full audit.
- After a deploy or a cron change, to confirm the paper clock + order path still produce real fills.

## Run (from `apps/engine`, read-only against prod)
```bash
cd apps/engine && set -a && . /Users/device/cosmu/.env.local && set +a && PYTHONPATH=. python3 - <<'PY'
import os, json, random
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import psycopg2, psycopg2.extras
from cosmu.knowledge.store import _pg_dsn
from cosmu.spine.venue import default_catalog

con = psycopg2.connect(_pg_dsn(os.environ["DATABASE_URL"]), connect_timeout=20); con.autocommit = True  # read-only: no writes
cur = con.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cat = default_catalog()

# 1) PICK a random active paper cell: a paper/screened/live version that HAS a real paper fill (is_paper=1).
#    The symbol×venue come from executions.venue_id (the REAL catalog venue, e.g. binance/ibkr — NOT the
#    positions ledger label 'sim'). One cell per (version, instrument, venue).
cur.execute("""
  SELECT DISTINCT e.strategy_version_id vid, s.name, sv.status, e.venue_id, e.instrument_id, t.updated_at
  FROM executions e
  JOIN strategy_versions sv ON sv.id = e.strategy_version_id
  JOIN strategies s ON s.id = sv.strategy_id           -- display name lives on strategies, not the version
  JOIN tracks t ON t.strategy_version_id = e.strategy_version_id
  WHERE e.is_paper = 1 AND sv.status IN ('paper','forward_test','screened','live')
""")
cells = cur.fetchall()
print(f"active paper cells (version×symbol×venue): {len(cells)}")
cell = random.choice(cells)  # ONE random cell (loop over random.sample(cells, min(3,len(cells))) for up to 3)
vid, venue_id, instr = cell["vid"], cell["venue_id"], cell["instrument_id"]
print(f"\n=== CELL {cell['name']}  [{instr} @ {venue_id}]  status={cell['status']} ===")

# 2) STEPPING? tracks.updated_at advances on every mark_tracks (loop.py:405). Fresh ⇒ the paper clock ran.
upd = cell["updated_at"]; upd = upd if isinstance(upd, datetime) else datetime.fromisoformat(str(upd))
if upd.tzinfo is None: upd = upd.replace(tzinfo=timezone.utc)
age_h = (datetime.now(timezone.utc) - upd).total_seconds()/3600
# Cross-check the cohort heartbeat: master emits a 'paper_stepped' event every executor tick.
cur.execute("SELECT MAX(ts) m FROM events WHERE kind='paper_stepped'")
hb = cur.fetchone()["m"]
print(f"STEP   marked {age_h:.1f}h ago (tracks.updated_at={str(upd)[:19]}) · last paper_stepped={str(hb)[:19]}")
stepping = age_h < 30  # daily clock + 4h ticks: <~30h is healthy; >48h ⇒ cron likely dark

# 3) TRADING? real paper fills exist (not stuck flat). Count + last fill time.
cur.execute("""SELECT count(*) n, max(ts) last FROM executions
               WHERE strategy_version_id=%s AND instrument_id=%s AND is_paper=1""", (vid, instr))
fr = cur.fetchone(); print(f"TRADE  {fr['n']} paper fills · last {str(fr['last'])[:19]}")
trading = fr["n"] > 0

# 4) SANITY: spot-check the last 2 fills — buys near the bar (price>0, qty>0), sides coherent.
cur.execute("""SELECT side, qty, price, fee FROM executions
               WHERE strategy_version_id=%s AND instrument_id=%s AND is_paper=1 ORDER BY ts DESC LIMIT 2""",(vid,instr))
fills = cur.fetchall()
for f in fills: print(f"       {f['side']:>4} qty={float(f['qty']):.6g} @ {float(f['price']):.6g}  fee={float(f['fee']):.6g}")
# Pull the spec's entry rationale so the human can judge "does this fill make sense": e.g. a momentum
# entry should be a BUY in an up-move. (Deep entry-condition replay is debug-strategy's job, not this.)
cur.execute("SELECT spec FROM strategy_versions WHERE id=%s",(vid,))
spec = cur.fetchone()["spec"]; spec = json.loads(spec) if isinstance(spec,str) else spec
print(f"       spec entry hint: {(spec or {}).get('rationale') or (spec or {}).get('thesis') or '—'}"[:160])

# 5) FEES CORRECT? implied bps from the fill vs the venue's cost_inputs() taker bps. SURFACE both.
v = cat.venue(venue_id)
taker_bps, slip_bps, impact_bps = v.cost_inputs()  # (taker, slippage, impact) — the SAME catalog the screen/paper price against
last = fills[0] if fills else None
fee_note = ""
if last and float(last["qty"])*float(last["price"]) > 0:
    implied = float(last["fee"]) / (float(last["qty"])*float(last["price"])) * 10000
    delta = implied - float(taker_bps)
    # A near-0 fill against a NONZERO catalog fee = the fee was never charged (a deploy-lane arm books
    # outside the _pit_fee_for_order order path). Flag it ATTENTION distinctly from a bps DRIFT — don't let
    # a coincidental tolerance hide an uncharged fee. Tolerance is relative: ±0.5bps OR ±10% of the catalog.
    tol = max(0.5, float(taker_bps) * 0.1)
    if implied < 0.05 and float(taker_bps) > 0:
        fee_ok = False; fee_note = "fill paid ~0 fee but catalog is nonzero — uncharged (deploy-lane arm?) "
    else:
        fee_ok = abs(delta) <= tol
    print(f"FEE    catalog {venue_id} taker={taker_bps}bps (slip={slip_bps} impact={impact_bps}) · fill implied={implied:.2f}bps · Δ={delta:+.2f}bps")
else:
    fee_ok = None; print(f"FEE    catalog {venue_id} taker={taker_bps}bps · (no priced fill to imply bps)")

# 6) VERDICT
ok = stepping and trading and (fee_ok is not False)
print(f"\n{'✅ PASS' if ok else '⚠️ ATTENTION'}  step={stepping} trade={trading} fee_ok={fee_ok}  {fee_note}")
print(f"   → VERIFY: {venue_id} charges {taker_bps}bps taker — does that match what {v.name} actually charges?")
con.close()
PY
```

## Read the verdict
- **✅ PASS** — the cell stepped recently, has real fills, and the fee matches the venue. The triple is honest here.
- **⚠️ stepping=False** — `tracks.updated_at` is stale (>~30h): the mark/step cron is likely dark (the canary in [[lifecycle_seed_leak_fix]] / [[modal_fleet_and_review_2026-06-16]] — Modal heartbeat). Check the Modal fleet, not the strategy.
- **⚠️ trading=False** — funded but never filled: a stuck-flat cell (entry never fired, or the order path rejected it). Hand to `debug-strategy`.
- **⚠️ fee_ok=False** — the implied bps ≠ `cost_inputs()` taker. Deploy-lane arm baskets (the TAA/GEM fleet, e.g. `*-ibkr`) book at `fee=0` outside the `_pit_fee_for_order` path, so a 0-bps IBKR fill vs catalog 0.5bps is EXPECTED for an arm, not a bug — but a *gate-lane* (`fstep-…` coid) crypto fill that drifts off 10bps Binance taker IS a real fee bug worth chasing. The line tells the human exactly which.

## Invariants
- **Read-only** — `autocommit` connection, SELECTs only. Never instantiate the engine `Store` here (its `__post_init__` runs `migrate()`, a write); use raw `psycopg2` + `_pg_dsn`.
- **Cheap** — ONE random cell by default (≤3). No backtest, no Modal, no LLM, no engine import beyond the catalog + DSN helper.
- **Fee truth is the catalog** — bps always come from `default_catalog().venue(v).cost_inputs()`, the single source the screen/gate/paper price against (no hardcoded bps).
- **Surfaces, never decides** — it reports PASS/ATTENTION + "here's the fee, verify"; it never funds, kills, or re-prices anything.

## Verify the skill itself
- A dry run prints a cell + verdict against prod (the probe above). Sanity: a healthy Binance paper cell implies ~10.0 bps (catalog taker=10); a deploy-lane `*-ibkr` arm fill implies 0 bps (booked outside the fee path) — both are correctly explained by the verdict notes.
