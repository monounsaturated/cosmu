---
name: wallet-paper
description: Review the paper (forward-test) wallet — aggregate book, per-cell P&L ranked by outlier, open positions, fees, lifecycle funnel. Read-only, never moves money. Use for "wallet paper" / "how's paper doing".
---

# wallet-paper

The operator wants the honest state of the **paper wallet** — what COSMU is forward-testing with simulated capital, and whether it's making or losing (paper) money. In COSMU **paper = forward test** (one step): each survivor proves on its OWN standalone track (`strategy_version × symbol × venue`), there is **NO pooled wallet** — the "wallet" is the **Σ of per-track allocated capital + their marked P&L** (the same read-out the `/overview` hero and `/leaderboard` show).

This skill reads the prod DB read-only and reports, for the **paper cohort** (`strategy_versions.status IN ('paper','forward_test')` = `FORWARD_STATUSES`):

1. **Aggregate hero** — `allocated` (Σ `tracks.starting_capital`) + `pnl_net` (latest `scope='aggregate'` snapshot) → book equity. *Exactly the `/overview` math.*
2. **Per-cell table** — activity flag → seed → marked value → P&L $ / % / trades / **last-trade recency** / age / fees, **gated on a real paper fill** (a marked snapshot with no backing `executions.is_paper=1` fill is NOT a forward result → shown `—`, never a fabricated $0). *Exactly the `/leaderboard` math, plus the "is it actually trading?" columns.*
3. **Ranked by OUTLIER** — top winners + bottom losers by forward return %, **never a pooled mean across cells** (operator rule: rank by outlier, surface every cell).
4. **Open positions** (paper), **total fees paid**, and the **funnel** (paper / live / screened / killed counts).
5. **CLOCK + PULSE** — a liveness line (freshest mark vs freshest trade → is the engine stepping or frozen?) and one **custom one-sentence verdict** that reads the whole book in a breath (equity, green count, last-trade age, plain-language call).

**Read-only.** SELECTs only on an `autocommit` connection. It never funds, defunds, sizes, routes, kills, or migrates — out of the gate path and the money path. It reads the local `.env.local` → prod DB (the engine's `_pg_dsn` strips the `pgbouncer`/`connection_limit` params that break libpq). Do NOT instantiate the engine `Store` (its `__post_init__` runs `migrate()`, a write) — raw `psycopg2` only. Sister skill: `wallet-live` (the real-money cohort).

## When to use
- "wallet paper" / "paper wallet" / "how's the paper book / forward test doing?" — a money read-out, not a per-cell liveness probe (that's `health-check`).
- After a deploy / cron change, to confirm the paper book's P&L moved (the hero advanced).

## Run (from `apps/engine`, read-only against prod)
```bash
cd apps/engine && set -a && . <repo>/.env.local && set +a && PYTHONPATH=. python3 - <<'PY'
import os
from datetime import datetime, timezone
import psycopg2, psycopg2.extras
from cosmu.knowledge.store import _pg_dsn

con = psycopg2.connect(_pg_dsn(os.environ["DATABASE_URL"]), connect_timeout=20); con.autocommit = True  # read-only
cur = con.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
PAPER = "('forward_test', 'paper')"   # knowledge.lifecycle_status.FORWARD_STATUSES — the single source for "paper"
now = datetime.now(timezone.utc)
def f(x):
    try: return float(x)
    except (TypeError, ValueError): return None
def age_days(ts):
    if not ts: return None
    d = ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts).replace("Z","+00:00"))
    if d.tzinfo is None: d = d.replace(tzinfo=timezone.utc)
    return (now - d).total_seconds()/86400

# 1) AGGREGATE HERO — Σ allocated (paper cohort) + latest aggregate-snapshot P&L. Mirrors api/routers/overview.py.
#    NO pooled wallet: the book = allocated capital + P&L, never the $100k sim bankroll.
cur.execute(f"SELECT COALESCE(SUM(CAST(t.starting_capital AS REAL)),0) AS allocated, COUNT(*) AS cells "
            f"FROM tracks t JOIN strategy_versions sv ON sv.id=t.strategy_version_id WHERE sv.status IN {PAPER}")
hero = cur.fetchone(); allocated = f(hero["allocated"]) or 0.0
cur.execute("SELECT pnl, ts FROM portfolio_snapshots WHERE scope='aggregate' ORDER BY ts DESC LIMIT 1")
snap = cur.fetchone(); pnl_net = f(snap["pnl"]) if snap else 0.0; agg_ts = snap["ts"] if snap else None
equity = allocated + pnl_net
print(f"=== PAPER WALLET (forward test) ===")
print(f"BOOK   allocated ${allocated:,.2f} + P&L ${pnl_net:,.2f} = equity ${equity:,.2f}  "
      f"({hero['cells']} cells · {(pnl_net/allocated*100) if allocated else 0:+.2f}% · marked {str(agg_ts)[:19]})")

# 2) PER-CELL (mirrors api/routers/leaderboard.py): version-keyed latest scope='track' marked equity, gated on a
#    REAL paper fill (is_paper=1). seed = Σ this version's track starting_capital. One display row per version.
cur.execute(f"""
  SELECT sv.id AS vid, s.name, sv.status, t.id AS track_id, t.symbol, t.venue_id,
         CAST(t.starting_capital AS REAL) AS seed, CAST(ps.equity AS REAL) AS marked,
         (SELECT COUNT(*) FROM executions e WHERE e.strategy_version_id=sv.id AND CAST(e.is_paper AS INTEGER)=1) AS trades,
         (SELECT COALESCE(SUM(CAST(e.fee AS REAL)),0) FROM executions e WHERE e.strategy_version_id=sv.id AND CAST(e.is_paper AS INTEGER)=1) AS fees,
         (SELECT MAX(e.ts) FROM executions e WHERE e.strategy_version_id=sv.id AND CAST(e.is_paper AS INTEGER)=1) AS last_fill,
         (SELECT MIN(ts) FROM events WHERE kind='track_opened' AND ref_id=sv.id) AS funded_at,
         EXISTS(SELECT 1 FROM executions e WHERE e.strategy_version_id=sv.id AND CAST(e.is_paper AS INTEGER)=1) AS has_fills
  FROM strategy_versions sv
  JOIN strategies s ON s.id=sv.strategy_id
  JOIN tracks t ON t.strategy_version_id=sv.id
  LEFT JOIN (SELECT ref_id, equity FROM portfolio_snapshots p1 WHERE scope='track'
             AND ts=(SELECT MAX(ts) FROM portfolio_snapshots p2 WHERE p2.scope='track' AND p2.ref_id=p1.ref_id)) ps
         ON ps.ref_id = sv.id
  WHERE sv.status IN {PAPER}
""")
ver = {}
for r in cur.fetchall():
    v = ver.setdefault(r["vid"], {"name": r["name"], "status": r["status"], "marked": f(r["marked"]),
                                  "trades": int(r["trades"] or 0), "fees": f(r["fees"]) or 0.0,
                                  "funded_at": r["funded_at"], "last_fill": r["last_fill"], "has_fills": bool(r["has_fills"]),
                                  "seed": 0.0, "seeds": set(), "cells": []})
    if r["track_id"] not in v["seeds"]:           # sum DISTINCT track seeds (a version fans out per cell)
        v["seeds"].add(r["track_id"]); v["seed"] += f(r["seed"]) or 0.0
    v["cells"].append(f"{r['symbol'] or '—'}@{r['venue_id'] or '—'}")
out = []
for vid, v in ver.items():
    value = v["marked"] if (v["has_fills"] and v["marked"] is not None) else None   # never a fabricated $0
    pnl = (value - v["seed"]) if value is not None else None
    ret = (pnl / v["seed"] * 100) if (pnl is not None and v["seed"]) else None
    out.append({**v, "value": value, "pnl": pnl, "ret": ret,
                "age": age_days(v["funded_at"]), "last_days": age_days(v["last_fill"])})

def actflag(d):                        # recency of the LAST real paper fill (raw, cadence-agnostic)
    if d is None: return "▫"           # never traded → not a forward result
    if d < 2:     return "🟢"           # traded in last 48h
    if d < 8:     return "🟡"           # traded this week
    return "🔴"                         # >1wk silent (EXPECTED for a MONTHLY rebalancer between month-turns)
print(f"\n--- {len(out)} paper cells · seed→marked→P&L · 'last'=days since last trade · '—'=no real fill yet ---")
print(f"   {'RET':>7}  {'seed':>6} {'marked':>8} {'P&L':>7}  {'tr':>3} {'last':>6} {'age':>5}  {'fee':>6}  strategy [cell]")
for v in sorted(out, key=lambda x: (x["ret"] is None, -(x["ret"] or 0))):
    vs = f"${v['value']:,.0f}" if v["value"] is not None else "—"
    pn = f"{v['pnl']:+,.0f}" if v["pnl"] is not None else "—"
    rt = f"{v['ret']:+.2f}%" if v["ret"] is not None else "  —  "
    ag = f"{v['age']:.0f}d" if v["age"] is not None else "—"
    ld = f"{v['last_days']:.0f}d" if v["last_days"] is not None else "—"
    cells = ",".join(sorted(set(v["cells"])))[:26]
    print(f"  {actflag(v['last_days'])}{rt:>7}  ${v['seed']:>5,.0f} {vs:>8} {pn:>7}  {v['trades']:>3} {ld:>6} {ag:>5}  ${v['fees']:>5.2f}  {v['name'][:26]:<26} [{cells}]")

# 3) OUTLIER ranking — top winners / bottom losers among TRADED cells (never a pooled mean).
traded = [v for v in out if v["ret"] is not None]
if traded:
    rk = sorted(traded, key=lambda x: -x["ret"])
    print(f"\nWINNERS  " + " · ".join(f"{v['name'][:18]} {v['ret']:+.1f}%" for v in rk[:5]))
    print(f"LOSERS   " + " · ".join(f"{v['name'][:18]} {v['ret']:+.1f}%" for v in rk[-5:][::-1]))
    print(f"         {sum(1 for v in traded if v['ret']>0)}/{len(traded)} traded cells green")
else:
    print("\n(no traded paper cells yet — all marks are seed-only, P&L unproven)")

# 4) OPEN POSITIONS (paper), TOTAL FEES, FUNNEL.
cur.execute(f"""SELECT s.name, p.symbol, p.venue, CAST(p.qty AS REAL) AS qty, CAST(p.avg_price AS REAL) AS px,
                       CAST(p.realized_pnl AS REAL) AS realized
                FROM positions p JOIN strategy_versions sv ON sv.id=p.strategy_version_id
                JOIN strategies s ON s.id=sv.strategy_id
                WHERE sv.status IN {PAPER} AND CAST(p.qty AS REAL) <> 0
                ORDER BY ABS(CAST(p.qty AS REAL)*CAST(p.avg_price AS REAL)) DESC""")
pos = cur.fetchall()
pos_val = sum(abs(f(p["qty"]))*f(p["px"]) for p in pos) if pos else 0.0
print(f"\nOPEN   {len(pos)} paper positions · notional ${pos_val:,.0f}")
for p in pos[:8]:
    print(f"       {p['symbol']:<12} {p['venue']:<10} qty={f(p['qty']):.6g} @ {f(p['px']):.6g}  realized ${f(p['realized']):+.2f}  ({p['name'][:24]})")
cur.execute("SELECT COALESCE(SUM(CAST(fee AS REAL)),0) AS fees, COUNT(*) AS n FROM executions WHERE CAST(is_paper AS INTEGER)=1")
fr = cur.fetchone(); print(f"FEES   ${f(fr['fees']):,.2f} paid across {fr['n']} paper fills")
cur.execute("SELECT status, COUNT(*) n FROM strategy_versions GROUP BY status ORDER BY n DESC")
funnel = {r["status"]: r["n"] for r in cur.fetchall()}
print(f"FUNNEL " + " · ".join(f"{k}={funnel[k]}" for k in funnel))
# RECONCILE the badge column vs reality: a version is stamped 'paper' but only TRADES once it logs a real
# is_paper=1 fill. orchestrator/loop.py::reclassify_unforwarded_paper demotes any paper w/ no fills back to
# 'screened' (reason='no_fills_yet') on the next tick. So a transient `status=paper` count can exceed the
# trading cells until that tick runs — surface the gap here so it self-explains instead of looking like drift.
cur.execute(f"""SELECT COUNT(*) AS paper_status,
  SUM(CASE WHEN EXISTS(SELECT 1 FROM executions e WHERE e.strategy_version_id=sv.id
      AND CAST(e.is_paper AS INTEGER)=1) THEN 1 ELSE 0 END) AS trading
  FROM strategy_versions sv WHERE sv.status IN {PAPER}""")
rec = cur.fetchone(); awaiting = int(rec["paper_status"]) - int(rec["trading"] or 0)
print(f"       {rec['paper_status']} status=paper · {rec['trading'] or 0} actually trading"
      + (f"  ⚠ {awaiting} stamped-paper w/ no fills yet → demote to 'screened' next reclassify tick" if awaiting else "  ✓ reconciled"))

# 5) CLOCK — is the engine stepping? Compare the freshest MARK (snapshot) vs the freshest TRADE (fill). A fresh mark
#    with a stale last-trade = engine alive & marking, just no recent rebalance (NORMAL for a MONTHLY cohort between
#    month-turns). A STALE mark = frozen clock → a real problem (run health-check). This is the true liveness signal —
#    a wall of 🔴 in the table alone does NOT mean dead; the mark age does.
cur.execute("SELECT MAX(ts) mx FROM portfolio_snapshots WHERE scope='track'")
snap_age = age_days(cur.fetchone()["mx"])
cur.execute("SELECT MAX(ts) mx FROM executions WHERE CAST(is_paper AS INTEGER)=1")
fill_age = age_days(cur.fetchone()["mx"])
clock_live = snap_age is not None and snap_age < 1.5
print(f"\nCLOCK  last mark {('%.2fd'%snap_age) if snap_age is not None else '—'} ago "
      f"({'🟢 alive' if clock_live else '🔴 STALE — frozen?'}) · "
      f"last trade {('%.1fd'%fill_age) if fill_age is not None else '—'} ago")

# 6) PULSE — one custom human sentence: the whole book in a breath (equity, green count, freshest trade, verdict).
grn = sum(1 for v in traded if v["ret"] > 0); tot = len(traded)
if not clock_live:                       verdict = "⚠ horloge GELÉE — le moteur ne marque plus → health-check"
elif fill_age is not None and fill_age > 7: verdict = f"moteur vivant & marque, 0 trade depuis {fill_age:.0f}j → cadence mensuelle ? (rebalance dû au tournant de mois)"
elif not tot:                            verdict = "aucune cellule n'a encore tradé — forward non prouvé"
else:                                    verdict = "cohorte active, forward en cours"
sign = "🟢" if pnl_net > 0 else ("🔴" if pnl_net < 0 else "⚪")
print(f"\nPULSE  {sign} Book ${equity:,.0f} ({(pnl_net/allocated*100) if allocated else 0:+.2f}%) · "
      f"{grn}/{tot} vertes · dernier trade {('il y a %.0fj'%fill_age) if fill_age is not None else '—'} · {verdict}")
con.close()
PY
```

## Read the result
- **BOOK** — the honest paper equity = `allocated + P&L` (never the sim bankroll). If `P&L ≈ $0` with cells funded, the marks are mostly seed-only — confirm fills are landing (`health-check`).
- **Activity flag / `last`** — the leftmost 🟢/🟡/🔴/▫ and the `last` column are the **days since that cell's last real trade** (🟢 <2d · 🟡 <8d · 🔴 ≥8d · ▫ never). This is the answer to "are they active?". **A wall of 🔴 is NOT death** — a monthly TAA cohort is *supposed* to sit still between month-turns. Read it together with **CLOCK**: fresh mark + old last-trade = alive but not rebalancing; only a stale mark = actually frozen.
- **Per-cell `—`** — a funded cell with **no real paper fill yet** (entry never fired, or only a seeded snapshot). It is NOT a forward result and is ranked last. Hand a stuck-flat cell to `debug-strategy`.
- **CLOCK** — `last mark` = freshest `scope='track'` snapshot age (the engine's heartbeat); `last trade` = freshest paper fill age. **🟢 alive** = a mark within ~1.5d. **🔴 STALE** = the engine stopped marking → real problem, run `health-check`. A fresh mark with a week-old last-trade is the normal monthly-cadence resting state, not a fault.
- **PULSE** — the custom one-liner: equity + %, green-cell count, last-trade age, and a plain-language verdict (frozen clock / alive-but-monthly-quiet / no-trades-yet / active). This is the single sentence to read if reading nothing else.
- **WINNERS / LOSERS** — the outliers carry the verdict. Do **not** average them — a few real edges + a long tail of duds is the expected shape; the question is whether the *top* cells are genuinely net-positive over a meaningful age.
- **FEES** — paid from the real fill ledger (today's venue schedule). Rising fees with flat P&L = churn.
- **FUNNEL** — `killed ≫ paper` is healthy (the Gate is strict by design). `paper` is the forward cohort; `screened` = backtest-only, not funded; `live` should be the `wallet-live` count. The reconcile line catches a **transient**: `status='paper'` is a badge that only becomes "trading" on the first real fill — `orchestrator/loop.py::reclassify_unforwarded_paper` demotes any fill-less `paper` back to `screened` (`no_fills_yet`) on the next tick, while `_promote_screened_on_first_fill` does the inverse. A `⚠ N stamped-paper w/ no fills` gap is this window, **not** drift — the money figures above already ignore those rows (`has_paper_fills` gate), so the BOOK is correct regardless.

## Present (operator's standard summary format)
Render the read-out as the operator's **clean-emoji FRENCH résumé** (per `[[feedback_summary_format]]`): emoji section headers + a compact table for the cells + a short **Décisions / À surveiller** line. **Open with the PULSE sentence** (the custom one-liner) so the whole book lands in the first line, then the BOOK figure and the WINNERS/LOSERS outliers; never a pooled mean across cells (per `[[feedback_surface_all_compute]]`). The per-cell table **must** carry the activity flag + `last`-trade column and the `age` column alongside seed→marked→P&L — the operator reads "are they active / latest trade day" straight from the table, no follow-up query. Keep it terse.

## Invariants
- **Read-only** — `autocommit`, SELECTs only; never instantiate the engine `Store` (it migrates = write). No engine import beyond `_pg_dsn`.
- **Honest forward** — money figures come from the marked `scope='track'` snapshot **gated on a real `is_paper=1` fill**; an un-traded cell reads `—`, never a fabricated $0 or its rosy backtest (mirrors `leaderboard.py::_paper_return_pct` / `_money_or_none`).
- **No pooled wallet** — `allocated` = Σ per-track `starting_capital` over the paper cohort (mirrors `overview.py`); there is no cross-track allocation.
- **Rank by outlier** — top/bottom by return %, every cell surfaced; NEVER a mean across cells.
- **Surfaces, never decides** — reports the book; it never funds, kills, sizes, or arms anything.

## Verify the skill itself
- A dry run prints the BOOK line + a cell table + WINNERS/LOSERS + positions/fees/funnel against prod. Sanity-check the BOOK `equity` ≈ the `/overview` hero and the per-cell `value`/`P&L%` ≈ the `/leaderboard` rows (this skill replicates both queries). `killed ≫ paper` in the funnel is expected.
