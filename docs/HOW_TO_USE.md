# How to use Cosmu

This is the one doc you read to operate the machine. Cosmu is a self-learning crypto
trading system: it discovers strategies, forward-tests each on its own standalone SIM
track, and (only when you arm it) trades live on Binance spot. You don't babysit it —
you steer it.

## The lifecycle

Every strategy walks one path. It can only move forward by earning it.

```
Lab  ->  Strategies  ->  Forward-test  ->  Live (capital ramp)
```

1. **Lab** — ideas become typed `StrategySpec`s. You run heavy search **locally**
   on the Mac; the cloud also authors and screens candidates on its own schedule.
2. **Forward-test** — each survivor gets its **own standalone $100k SIM track** and is
   **held and marked-to-market** across real bars. There is **no pooled wallet** — each
   track proves itself in isolation. A track must show positive net-of-fee SIM P&L over
   **N>=30 forward days** before it is live-eligible.
3. **Live** — once a track clears the gate and you arm it, capital ramps up gradually.
   Live is **OFF by default** (see Safety below).

The only judge that promotes a strategy from the Lab to a fundable state is the
**single funding gate**: FDR + global-trial-ledger (must-beat-buy-and-hold, real
CSCV-PBO, deflated Sharpe, regime breadth). Nothing else funds anything.

## What each web route shows

The web app (Vercel) reads the engine API (Railway, `https://cosmu.up.railway.app`).

- **Overview** (`/`) — the home dashboard. One-glance health: what's running, the
  aggregate read-out (Σ of all standalone tracks), what cleared the gate, what's live.
  Start here.
- **Lab** (`/lab`) — the research route. What the research loop is finding, gate
  verdicts, candidate specs under evaluation.
- **Strategies** (`/strategies`) — the roster of authored specs and their state. Click
  one (`/strategy/[id]`) for its detail, params, and history.
- **Forward-test** (`/paper`) — funded SIM tracks and their forward-test clock
  (net-of-fee P&L, days held, distance to the N>=30 bar). Each track is standalone;
  there is no pooled wallet.
- **Live** (`/live`) — real-money tracks and the capital ramp. Hidden/dimmed until
  Live is actually armed; it only appears in the nav dock when armed.
- **Steer** (`/steer`) — talk to the machine: natural-language ops and ML asks. This is
  where you nudge behavior. (`/console` redirects here.)
- **Settings** (`/settings`) — toggles, keys, and the live interlocks.

Rule: the app **never displays synthetic data**. Everything shown is from real Binance
bars. Synthetic edge-bearing fixtures exist only in CI/tests and never reach the UI or prod.

## Running discovery: local Mac vs cloud

**Heavy compute runs LOCALLY on the M2 Mac, for $0.** Grid-search, walk-forward, and
backtest sweeps are deterministic and offline-capable, so the whole discover/verify loop
runs on your machine with no keys and no cloud cost. Local search emits only the
*winning* `StrategySpec`s to Postgres.

Run it from the engine:

```bash
cd apps/engine
python3 -m cosmu.research.loop      # discover locally; winners persist to Postgres
python3 -m cosmu.research.gate      # run the funding gate and read the verdict
```

(See the `/run-gate` skill for the full ingest + gate flow and how to read the verdict.)

**The cloud only does light, scheduled work** (from `apps/engine/railway.toml`):

- the **always-on API** that serves the UI,
- **gate disposition** on authored specs and **mark-to-market** of SIM tracks,
- a **research ingest pass** every 6h: `python3 -m cosmu.research.loop --ingest`
  (bounded — one free-data ingest + gate run, then exits; not a daemon),
- the **full autonomous cycle** every 4h: `python3 -m cosmu.master.scheduler`
  (ingest -> author -> gate/screen -> fund survivor tracks -> recommendations),
- the **forward-test clock** hourly: `python3 -m cosmu.orchestrator.loop`
  (re-marks held SIM positions to the latest real close — no orders).

The deployed autonomous tick runs on **real Binance bars** (`edge_market=False`).

**Clean cutover (one-time).** When switching from a synthetic-era DB to the honest
loop, purge the old SIM/discovery state so the displayed aggregate read-out is real:

```bash
python3 -m cosmu.master.reset            # dry-run: shows what would be purged
python3 -m cosmu.master.reset --confirm  # purge (keeps config, live toggle/caps, real alt-data)
```

## Adding a strategy

Use the **`/create-strategy`** skill — it authors a uniform, auditable `StrategySpec` so
hand-written and machine-written strategies are identical. To import a TradingView idea,
use **`/import-pine`**.

Either way the spec lands in `apps/engine/strategies/inbox/` as JSON, where the gate
picks it up for screening. You can also drop a plain-text thesis in the inbox
(see `strategies/inbox/BRIEF_TEMPLATE.md`).

## Verify before every push

One command, fully offline, no keys:

```bash
pnpm verify      # = contracts:generate && engine:test && typecheck
```

Run it before every push. **Push = deploy** — pushing the working branch auto-deploys
the engine to Railway and the web to Vercel.

## Safety model

- **Live is OFF by default**, behind **5 interlocks** — all must hold to trade real money:
  1. live toggle on,
  2. real Binance keys present,
  3. the funding gate passed for that track,
  4. capital caps available,
  5. no kill-switch tripped.
- **Never display synthetic data.** Synthetic fixtures are quarantined to CI/tests only.
- **Profit is the only metric.** Net-of-fee P&L on real bars decides everything.
