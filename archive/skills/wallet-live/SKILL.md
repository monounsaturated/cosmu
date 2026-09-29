---
name: wallet-live
description: Review the live (real-money) wallet — arming interlock, live positions, P&L and budget headroom; degrades to "no live yet + armable candidates". Read-only, never trades. Use for "wallet live" / "are we live".
---

# wallet-live

The operator wants the honest state of the **live wallet** — real money on real venues. In COSMU live is **off by default** and **every** live launch is a manual human click behind a hard interlock (`toggle ON` + venue keys + a gate-passed, paper-matured, in-regime survivor + caps + no kill-switch); the gate is *eligibility*, the human *arms*. Today there are typically **0 live tracks**, so this skill is built to **degrade gracefully**: when nothing is armed it still reports the full arming interlock and the armable candidates, so "are we live?" always gets a complete answer.

This skill reads the prod DB + the pure settings resolvers read-only and reports:

1. **Arming interlock** — `live_toggle.enabled`, the resolved aggregate `mode` (`live`/`testnet`/`disabled`, via `adapters/exec/registry.live_mode`), the global caps (`live_caps.max_notional` / `max_daily_loss`), and which venues are **configured** (`keys_present`). *Same signals the `/live` control-plane reports.*
2. **Live cohort** — `strategy_versions.status='live'` versions + their tracks.
3. **Real-money positions** — `positions` where `venue != 'sim'` **AND** the owning version is `live` (venue alone is NOT enough — paper ETF legs book under their *intended* venue, e.g. `ibkr`, while simulated). `invested` = Σ|qty|·avg_price, `realized` = Σ realized_pnl, `unrealized` = 0 until a fresh mark (no live snapshot is persisted yet), `free` = `global_cap − invested` (budget headroom, NOT exchange cash). *Exactly `overview.py::portfolio_summary`.*
4. **Live fills** — `executions` with `is_paper=0`.
5. **Armable candidates (advisory)** — paper cells that look live-ready (traded, net-positive, matured ≥ ~30d). Advisory only — the real gate is `master/live_eligibility.py` (it also checks current regime); the human still clicks launch.

**Read-only and money-safe.** SELECTs only on an `autocommit` connection; the settings resolvers are PURE (keys + interlock, no network). It **NEVER** places, cancels, sizes, arms, or routes an order — it only LOOKS. It reads the local `.env.local` → prod DB (`_pg_dsn` strips the `pgbouncer`/`connection_limit` params that break libpq). Do NOT instantiate the engine `Store` (its `__post_init__` runs `migrate()`, a write). Sister skill: `wallet-paper` (the forward-test cohort).

## When to use
- "wallet live" / "live wallet" / "are we live?" / "real-money summary" — the real-money read-out + arming state.
- Before/after a manual arm, to confirm the interlock and what's deployed (never to arm — that's a human click in the `/live` UI).

## Run (from `apps/engine`, read-only against prod)
```bash
cd apps/engine && set -a && . /Users/device/cosmu/.env.local && set +a && PYTHONPATH=. python3 - <<'PY'
import os
from datetime import datetime, timezone
import psycopg2, psycopg2.extras
from cosmu.knowledge.store import _pg_dsn
from cosmu.config.settings import get_settings
from cosmu.adapters.exec.registry import live_mode, keys_present  # PURE resolvers — no network, no DB

con = psycopg2.connect(_pg_dsn(os.environ["DATABASE_URL"]), connect_timeout=20); con.autocommit = True  # read-only
cur = con.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
st = get_settings(); now = datetime.now(timezone.utc)
def f(x):
    try: return float(x)
    except (TypeError, ValueError): return None
def age_days(ts):
    if not ts: return None
    d = ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts).replace("Z","+00:00"))
    if d.tzinfo is None: d = d.replace(tzinfo=timezone.utc)
    return (now - d).total_seconds()/86400

# 1) ARMING INTERLOCK — toggle · resolved mode · caps · configured venues. Mirrors api/routers/live.py.
cur.execute("SELECT enabled, enabled_at, enabled_by FROM live_toggle WHERE id='global'")
tog = cur.fetchone(); enabled = bool(tog and tog["enabled"])
mode = live_mode(st)
cur.execute("SELECT max_notional, max_daily_loss FROM live_caps WHERE id='global'")
caps = cur.fetchone()
global_cap = f(caps["max_notional"]) if caps else f(st.live.global_live_cap)
daily_loss = f(caps["max_daily_loss"]) if caps else f(st.live.daily_loss_cap)
armed = enabled and mode != "disabled"
venues = [v for v in ("binance","kraken","alpaca","polymarket") if keys_present(v, st)]
print("=== LIVE WALLET (real money) ===")
print(f"ARMED  {'YES' if armed else 'NO'}  · toggle={'on' if enabled else 'off'} · mode={mode} · "
      f"per-strat ${f(st.live.per_strategy_live_cap):,.0f} · global ${global_cap:,.0f} · daily-loss ${daily_loss:,.0f}")
print(f"KEYS   configured venues: {', '.join(venues) if venues else 'none'}")

# 2) LIVE COHORT — versions in the 'live' lifecycle stage (the honest discriminator; venue alone is not enough).
cur.execute("SELECT sv.id, s.name FROM strategy_versions sv JOIN strategies s ON s.id=sv.strategy_id WHERE sv.status='live'")
live_vers = cur.fetchall(); live_ids = {r["id"] for r in live_vers}

# 3) REAL-MONEY POSITIONS — venue != 'sim' AND owning version is live. Mirrors portfolio_summary.
pos = []
if live_ids:
    cur.execute("""SELECT s.name, p.symbol, p.venue, CAST(p.qty AS REAL) AS qty, CAST(p.avg_price AS REAL) AS px,
                          CAST(p.realized_pnl AS REAL) AS realized, p.strategy_version_id AS vid
                   FROM positions p JOIN strategy_versions sv ON sv.id=p.strategy_version_id
                   JOIN strategies s ON s.id=sv.strategy_id
                   WHERE sv.status='live' AND p.venue <> 'sim' AND CAST(p.qty AS REAL) <> 0
                   ORDER BY ABS(CAST(p.qty AS REAL)*CAST(p.avg_price AS REAL)) DESC""")
    pos = cur.fetchall()

if pos:
    invested = sum(abs(f(p["qty"]))*f(p["px"]) for p in pos)
    realized = sum(f(p["realized"]) for p in pos)
    unreal = 0.0  # mark==basis without a fresh tick; no live portfolio snapshot is persisted yet (honest 0)
    print(f"\nLIVE   {len(live_vers)} live versions · {len(pos)} real positions")
    print(f"MONEY  invested ${invested:,.2f} · realized ${realized:+,.2f} · unrealized ${unreal:+,.2f} "
          f"· P&L ${realized+unreal:+,.2f} · free ${global_cap-invested:,.2f} (cap headroom)")
    for p in pos[:10]:
        print(f"       {p['symbol']:<12} {p['venue']:<10} qty={f(p['qty']):.6g} @ {f(p['px']):.6g} "
              f"realized ${f(p['realized']):+.2f}  ({p['name'][:24]})")
    cur.execute("SELECT COALESCE(SUM(CAST(fee AS REAL)),0) AS fees, COUNT(*) AS n FROM executions WHERE CAST(is_paper AS INTEGER)=0")
    fr = cur.fetchone(); print(f"FILLS  ${f(fr['fees']):,.2f} fees across {fr['n']} live fills")
else:
    # GRACEFUL DEGRADE — no live wallet yet. Report what WOULD show + the armable candidates.
    print(f"\nLIVE   no live wallet yet — {len(live_vers)} live versions, 0 real-money positions.")
    print("       (when armed: invested / realized / unrealized / P&L / free-headroom would print here.)")
    cur.execute("""
      SELECT s.name, CAST(t.starting_capital AS REAL) AS seed, CAST(ps.equity AS REAL) AS marked,
             (SELECT MIN(ts) FROM events WHERE kind='track_opened' AND ref_id=sv.id) AS funded_at,
             EXISTS(SELECT 1 FROM executions e WHERE e.strategy_version_id=sv.id AND CAST(e.is_paper AS INTEGER)=1) AS has_fills
      FROM strategy_versions sv JOIN strategies s ON s.id=sv.strategy_id JOIN tracks t ON t.strategy_version_id=sv.id
      LEFT JOIN (SELECT ref_id, equity FROM portfolio_snapshots p1 WHERE scope='track'
                 AND ts=(SELECT MAX(ts) FROM portfolio_snapshots p2 WHERE p2.scope='track' AND p2.ref_id=p1.ref_id)) ps
             ON ps.ref_id=sv.id
      WHERE sv.status IN ('forward_test','paper')
    """)
    cand = []
    for r in cur.fetchall():
        seed, marked, hf = f(r["seed"]), f(r["marked"]), bool(r["has_fills"])
        if not hf or marked is None or not seed: continue
        ret = (marked/seed - 1)*100; ag = age_days(r["funded_at"])
        if ret > 0 and (ag or 0) >= 30:    # advisory live-ready heuristic (real gate also checks regime)
            cand.append((r["name"], ret, ag))
    cand.sort(key=lambda x: -x[1])
    if cand:
        print(f"\nARMABLE (advisory — net-positive + matured ≥30d; real gate = master/live_eligibility.py, +regime):")
        for n, ret, ag in cand[:8]:
            print(f"       {ret:+6.1f}%  {ag:4.0f}d  {n[:40]}")
    else:
        print("\nARMABLE  none meet the advisory bar (traded + net-positive + matured ≥30d) — keep forward-testing.")
con.close()
PY
```

## Read the result
- **ARMED NO / mode=disabled** — the normal resting state: no real money can move. `toggle=off` is the master interlock; even `on`, `mode=disabled` (no live keys) means nothing routes live.
- **KEYS** — venues with credentials present (testnet keys count as configured). Configured ≠ armed.
- **LIVE / MONEY** — only prints real figures when there are positions on `venue != 'sim'` owned by a `live` version. `unrealized=$0` is honest (no fresh mark / no live snapshot persisted yet) — `realized` is the booked truth; `free` is cap headroom, not exchange cash.
- **ARMABLE (advisory)** — paper cells that *look* live-ready. This is a heuristic (net-positive + matured); the binding check is `master/live_eligibility.py` (which also requires the current regime to be in the strategy's proven set), and a human still clicks launch in the `/live` UI. Never auto-arm.

## Present (operator's standard summary format)
Render as the operator's **clean-emoji FRENCH résumé** (per `[[feedback_summary_format]]`): lead with **ARMED yes/no + mode**, then MONEY (or the graceful "pas encore de live" + armable candidates), a compact positions table if any, and a short **Décisions / À surveiller** line. Terse.

## Invariants
- **Read-only & money-safe** — `autocommit`, SELECTs only; the settings resolvers are pure (no network, no order). NEVER place/cancel/size/arm/route — only LOOK. Never instantiate the engine `Store` (it migrates = write).
- **Honest live discriminator** — a position is live money only when `venue != 'sim'` AND its owning version is `status='live'` (mirrors `portfolio_summary`); venue alone counts paper legs as live (the bug that note fixed).
- **Degrade gracefully** — 0 live tracks is the expected state; always still report the interlock + armable candidates so "are we live?" gets a full answer.
- **Live is a human click** — eligibility is computed; arming is manual. This skill informs, it never arms.

## Verify the skill itself
- A dry run prints the ARMED line + KEYS + (today) the graceful "no live wallet yet" + armable candidates against prod. Sanity: `ARMED` should be `NO`/`mode=disabled` and live positions `0` unless the operator has manually armed (the project state is 0 live tracks). The MONEY math mirrors `portfolio_summary` (invested = Σ|qty|·avg_price, free = global_cap − invested).
