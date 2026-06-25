# Runbook — arm Kraken for LIVE trading (venue-agnostic exec layer)

**Status:** READY, not armed. No Kraken account exists today. The exec adapter, settings, and registry
wiring are all already on `main`; this runbook is the exact, ordered procedure to flip a gate-passed,
paper-proven survivor to **real money on Kraken spot** the moment the operator creates a Kraken account and
adds API keys. With the keys absent, arming is impossible — the Kraken adapter resolves to `disabled` and
every routed order sim-fills (see the **Safety invariant** below).

**Scope:** the EXEC / arming layer only. The *keyless price bars* are a separate, already-shipped concern —
see [`kraken-activation.md`](./kraken-activation.md), which flips the keyless OHLCV source and needs **no
account**. This runbook starts where that one ends ("Live trading on Kraken — deferred"). It does NOT change
any Gate constant or money-path logic.

**Venue-agnostic:** the SAME steps arm **Polymarket** (substitute its signing key) and — once an exec
adapter exists — **Hyperliquid**. The only per-venue difference is *which credential env var(s)* you set;
everything downstream (the 5 interlocks, the registry resolver, the launch flow) is venue-agnostic.

---

## Prerequisites (must all be true before you start)

1. **A Kraken account** with **spot trading** enabled, funded with the capital you intend to risk.
2. **An API key pair** created in the Kraken account (Settings → API):
   - Permissions: at minimum **Create & Modify Orders**, **Cancel/Close Orders**, **Query Open
     Orders & Trades**, **Query Closed Orders & Trades**, **Query Ledger Entries**.
   - Do **not** enable Withdraw — the engine never withdraws.
   - Note: Kraken **spot has no public sandbox/testnet**. Unlike Binance (testnet) or Alpaca (paper),
     the only Kraken modes are `disabled` (no keys / not armed) and `live` (keys + `mode="real"`).
     There is no fake-money Kraken dry run — the first real key you add IS the live key.
3. **A gate-passed + paper-proven survivor** on a Kraken cell — i.e. a `strategy_version` whose forward
   (paper) track on the exact `(symbol, venue=kraken)` you intend to arm has:
   - cleared the deterministic edge Gate (it is a fundable survivor), and
   - matured: `>= PAPER_MIN_DAYS` (30) days of net-of-fee-positive forward evidence **and** is in a
     proven regime. The `/live/launch` flow enforces this as a HARD precondition (it reads
     `master/live_eligibility.live_eligibility_verdict`); `override_paper=true` can waive the *paper*
     precondition with a loud `live_override_launch` audit mark, but **never** the regime gate.

---

## Step 1 — add the Kraken API keys to the server env

The keys live wherever the engine reads process env. Two places:

**(a) Local / `.env.local`** (for `modal run` auth + local dev):

```bash
# .env.local — NEVER commit. Real keys, no quotes needed unless the value has spaces.
KRAKEN_API_KEY=<your-kraken-api-key>
KRAKEN_API_SECRET=<your-kraken-private-key>
```

These map straight onto `Settings.kraken_api_key` / `Settings.kraken_api_secret`
(`cosmu/config/settings.py`), declared `repr=False` so they never appear in logs, DB rows, or prompts.

**(b) The always-on backend (Railway)** — set the same two variables on the **engine** service
(Dashboard → engine service → Variables), then let Railway redeploy. This is the box that actually
runs the live tick, so the keys MUST be here for real orders to route in prod.

**(c) The Modal heavy-compute secret** — sync from `.env.local` in one step (the WANTED list now
includes the Kraken keys, so a future arming picks them up automatically; absent keys are skipped):

```bash
python3 scripts/sync_modal_secret.py     # alias: pnpm modal:secret — rebuilds the cosmu-engine secret
```

> The Kraken keys are **optional** in the WANTED list — if they are not in `.env.local`, the sync simply
> skips them (no error). Only when you actually add them do they propagate.

After this step, `keys_present("kraken", settings)` is `True` and the Kraken venue shows `configured: true`
in `/live/venue-catalog` (the UI un-greys it). **Nothing is armed yet** — presence is not arming.

---

## Step 2 — set `live.mode = "real"`

This is the explicit real-money interlock. With `mode="testnet"` (the default) the Kraken adapter resolves
to `disabled` **even with valid keys** — `resolve_mode` (`cosmu/adapters/exec/kraken.py`) returns `"live"`
only when `settings.live.mode == "real"` AND both keys are present. Set it in the SAME server env as the
keys:

```bash
# .env.local (and the Railway engine + Modal secret, same as Step 1)
LIVE__MODE=real
```

(`LIVE__MODE` uses the `__` nested-delimiter that pydantic-settings maps onto `LiveSettings.mode`.)

After this, `adapter_for("kraken", settings)` returns an **active** adapter (`.active == True`) and
`live_mode(settings)` reports `"live"`. Still not armed — the toggle and a launch are required.

---

## Step 3 — flip the global live toggle ON

The global toggle is a two-click safety gate. Flip it via the API (or the front's Go-Live control):

```bash
curl -s -X POST "<engine-url>/toggle/live" \
  -H "x-api-key: <API_SECRET_KEY>" -H "content-type: application/json" \
  -d '{"enabled": true, "confirm": true}'
```

`confirm` MUST be `true` — without it the route returns `requires_confirm` and mutates nothing
(`cosmu/api/routers/toggle.py`). This sets `live_toggle.enabled = 1` (audited as `live_toggle_changed`).
Flipping the toggle on its own still funds **nothing** — it only opens the `live_enabled` flag the order
path reads; sim-fills continue until a strategy is actually launched on a configured venue.

---

## Step 4 — arm the survivor on the Kraken cell

This is the ONLY path that writes `status='live'` for a strategy. Launch ONE gate-passed, paper-proven
survivor on the exact `(symbol, venue=kraken)` its forward proof was earned on:

```bash
curl -s -X POST "<engine-url>/live/launch" \
  -H "x-api-key: <API_SECRET_KEY>" -H "content-type: application/json" \
  -d '{
        "version_id": "<gate-passed-survivor-version-id>",
        "venue_id": "kraken",
        "symbol": "BTC/USD",
        "budget": 500,
        "per_strategy_cap": 2500,
        "global_cap": 10000,
        "max_daily_loss": 250,
        "confirm": true
      }'
```

The launch flow (`cosmu/api/routers/live.py::live_launch`) enforces, in order:

1. `confirm` must be `true` (two-click safety).
2. **Venue configured** — `kraken` must have keys present (Step 1), else it refuses with
   *"venue 'kraken' has no API keys configured"*.
3. **S×A×V attribution guard** — the forward proof must have been earned on the *same* `(symbol, venue)`
   you are arming. Arming a different cell on another cell's evidence is refused.
4. **Hard live-eligibility gate** — `>= PAPER_MIN_DAYS` net-positive forward evidence AND a proven regime
   (`override_paper` waives only the paper part, never the regime).

On success it upserts the live caps, freezes the EXACT armed config (so the live step only opens orders
matching the frozen `params_hash` / `fee_model` / `registry_version`), and sets `status='live'`. The
survivor is now armed: the next tick's intended orders for this cell route through the real Kraken adapter.

> **Caps** — the per-strategy / global / daily-loss caps you pass here are the live $-blockers. They apply
> **only when live is armed** (the SIM/paper lane is never constrained by a live cap). `budget` is this
> strategy's slice; `global_cap` is the whole live pool's hard ceiling; `max_daily_loss` auto-disarms on a
> bad day. Defaults: per-strategy $2500, global $10000, daily-loss $250
> (`LiveSettings`, `cosmu/config/settings.py`).

---

## The 5 execution interlocks (what a real Kraken order requires)

A real venue submit happens in `master/execution.py::execute_orders` ONLY when **all five** hold
(line 242, `route_live = ...`):

| # | Interlock | Set by |
|---|-----------|--------|
| 1 | `live_enabled` (global toggle ON) | Step 3 (`/toggle/live`) |
| 2 | `adapter.active` (keys present + `live.mode=="real"`) | Steps 1 + 2 |
| 3 | `intent.gate_passed` (the survivor cleared the Gate) | the Gate, at screen time |
| 4 | caps available (per-venue + global + per-strategy + daily-loss) | Step 4 caps |
| 5 | `not kill_switch` AND not regime-blocked | the guardian / regime gate |

Miss any one → the order **sim-fills** (deterministic paper, pays the 5 bps half-spread) and is audited.
There is no path where 4 hold and the 5th is bypassed.

---

## Kill-switch / caps / disarm

- **Kill-switch:** the deterministic risk guardian trips `kill_switch` on a drawdown breach
  (`risk.drawdown_killswitch_pct`, default 0.15) — interlock #5 flips and live routing stops immediately
  (open positions stay; new entries sim-fill). A reduce-only **exit** is never blocked by the kill-switch
  or the regime gate — you can always close.
- **Daily-loss auto-disarm:** `max_daily_loss` (Step 4) caps the live day; breaching it disarms.
- **Manual disarm (flatten):** `POST /live/defund` zeroes positions for a strategy (`scope:"strategy"`,
  `version_id`) or the whole pool (`scope:"all"`), audited as `live_defunded`.
- **Hard stop:** `POST /toggle/live {"enabled": false}` flips the global toggle off — interlock #1 fails,
  all routing reverts to sim-fill. No `confirm` needed to turn OFF (only ON is gated).
- **Full rollback to no-live:** unset `LIVE__MODE` (back to `testnet`) and/or remove the Kraken keys from
  the server env + re-sync the Modal secret. Either makes the adapter `disabled` again → sim-fill.

---

## Same path arms Polymarket and (later) Hyperliquid — venue-agnostic

Nothing above is Kraken-specific except *which credential env var* you set in Step 1 and the
`venue_id` / `symbol` in Step 4. The order path, the registry resolver, the toggle, and the launch flow are
all venue-agnostic.

- **Polymarket** (live today, exec adapter shipped — `cosmu/adapters/exec/polymarket.py`):
  - Step 1: set `POLYMARKET_PRIVATE_KEY` (the signing key) instead of the Kraken keys. The L2 API creds
    (`POLYMARKET_API_KEY` / `_SECRET` / `_PASSPHRASE`) are derived from the signing key by py-clob-client
    when omitted. (`POLYMARKET_TESTNET_PRIVATE_KEY` on Amoy takes precedence and never touches real funds.)
  - Steps 2–4 identical, with `venue_id: "polymarket"` and a real market token symbol. A prediction CLOB
    has no market order, so the executor coerces it to a limit at the current mark automatically.
- **Hyperliquid** (NOT live-wired yet — `live_enabled=False`, no exec adapter):
  - `adapter_for("hyperliquid", settings)` returns `None` today, so it ALWAYS sim-fills regardless of any
    key or toggle. Once an exec adapter is added to `EXEC_ADAPTER_VENUES` + `adapter_for()`
    (`cosmu/adapters/exec/registry.py`) with the same disabled-by-default `from_settings` contract, the
    very same Steps 1–4 arm it. No order-path change is needed.

---

## Safety invariant — an UNKEYED venue can NEVER route real money by accident

This is the load-bearing guarantee and the reason "no Kraken account today" is safe:

> **A venue with no execution credentials resolves to a *disabled* adapter, and a disabled adapter
> sim-fills — it never reaches the network.**

Enforced at every layer:

- `adapter_for(venue_id, settings)` (`cosmu/adapters/exec/registry.py`) returns either an adapter whose own
  `from_settings` produced a `disabled` instance (no keys / `mode != "real"`) or `None` (no adapter wired).
- `KrakenSpotExecutionAdapter.from_settings` returns `disabled` when `resolve_mode` is `disabled`
  (no keys or `mode != "real"`) — `disabled` means **no ccxt client is even built**, so there is no
  network surface at all. `.active` is `False`, and `submit()` *raises* `RuntimeError("kraken adapter
  disabled (no keys) — caller must paper-simulate")`.
- In `execute_orders`, interlock #2 is `getattr(adapter, "active", False)` — a `disabled` adapter (or a
  `None` resolved to a no-op) fails it, so `route_live` is `False` → the order sim-fills and is recorded as
  paper (`is_paper=1`). Secrets are never attributes on the instance, never logged, never returned.

So until the operator deliberately completes **all** of Step 1 (keys) **and** Step 2 (`mode="real"`)
**and** Step 3 (toggle) **and** Step 4 (launch a proven survivor), Kraken stays a pure paper venue. No
single mis-set flag arms real money.

---

## Read-only verification — confirm the interlocks are venue-agnostic

These checks need no account and move no money. They confirm the arming layer is generic, not
Binance-hardcoded.

### V1 — the order path is venue-agnostic (the single arming gate)

`master/execution.py::execute_orders` takes `adapter` as a parameter and gates a live submit on the abstract
`adapter.active`, not any concrete venue:

```bash
grep -n "route_live = bool" apps/engine/cosmu/master/execution.py
# 242:  route_live = bool(live_enabled and not kill_switch and intent.gate_passed
#                         and getattr(adapter, "active", False) and not regime_blocked)
```

Line **242** is the ONLY place a live route is decided, and it references the injected `adapter` — swap in
the Kraken adapter and the exact same gate applies. The venue-shaping at line **259–261** (`to_ccxt_symbol`
for crypto, limit-at-mark for a prediction CLOB) is keyed on `venue.kind`, not a venue id.

### V2 — the registry resolves any venue + is safe-by-construction

`adapters/exec/registry.py`:

```bash
grep -n "EXEC_ADAPTER_VENUES\|def adapter_for\|kraken\|polymarket" apps/engine/cosmu/adapters/exec/registry.py
# 15:  EXEC_ADAPTER_VENUES: frozenset[str] = frozenset({"binance", "kraken", "alpaca", "polymarket"})
# 18:  def adapter_for(venue_id: str, settings: Settings) -> ExecutionAdapter | None:
# 26:      if venue_id == "kraken":
# 27:          from cosmu.adapters.exec.kraken import KrakenSpotExecutionAdapter
# 28:          return KrakenSpotExecutionAdapter.from_settings(settings)
```

Line **15** lists `kraken` + `polymarket` as wired venues. Lines **26–29** resolve Kraken. The module
docstring states the resolved adapter "is SAFE by construction (its own `from_settings` returns a disabled
adapter when keys/mode are absent, so submit raises and nothing routes)".

### V3 — the disabled-by-default interlock (no keys ⇒ no network)

`adapters/exec/kraken.py::resolve_mode` (lines **122–128**) returns `"live"` ONLY with both keys present AND
`live.mode == "real"`; otherwise `"disabled"`. `from_settings` (lines **152–161**) builds NO ccxt client
when disabled, and `.active` (line **171–174**) is `False` unless a real client is wired:

```bash
grep -n "def resolve_mode\|mode == .real.\|return .disabled.\|def active" apps/engine/cosmu/adapters/exec/kraken.py
```

### V4 — the catalog flag does not arm, and the launch flow key-gates the venue

`spine/venue.py` marks Kraken `live_enabled=True` (the adapter exists) but the inline comment is explicit
that "a real order still needs `KRAKEN_API_KEY/SECRET` + `live.mode=="real"` + a gate-passed survivor +
caps + the toggle ... so the catalog flag does NOT arm anything by itself." The launch route refuses an
unconfigured venue:

```bash
grep -n "_venue_connected\|no API keys configured" apps/engine/cosmu/api/routers/live.py
```
