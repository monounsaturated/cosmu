# Schedule the capital-guard watchdog + config-driven equity-arm venue (safety only)

Date: 2026-06-28
Branch: `claude/capital-guard-schedule-2026-06-28`
Scope: money-path-ADJACENT. This change makes an existing SAFETY watchdog actually RUN on every tick, and makes
the equity-arm venue config-driven. It NEVER arms anything, moves money, deploys capital, or weakens the
human-arming interlock.

---

## The two gaps (roadmap #5)

### Gap A — the capital-guard watchdog was effectively unscheduled
`apps/engine/cosmu/ops/capital_guard.py::run_capital_guard()` is a complete reduce-only capital-protection
supervisor (capital-floor LIQUIDATE + profit-lock TRIM, both REDUCE-ONLY). But it was reachable from only two
places:

1. The **API kill-switch** (`apps/engine/cosmu/api/routers/ops.py`) — which calls `capital_guard.kill()`, the
   MANUAL operator stop, never the automatic `run_capital_guard()`.
2. The **Modal `tick`** in `apps/engine/remote/app.py`, which ran `python -m cosmu.ops.capital_guard` as a
   separate subprocess gated by a `_live_armed()` check.

Neither the **Railway paper-clock cron** (`python -m cosmu.orchestrator.loop`) nor the orchestrator/paper-clock
tick itself invoked the automatic supervisor. So the actual marking clock — the thing that runs every cycle on
both Railway and Modal — never ran the watchdog. A first live arm would have had **no automatic disarm** if the
Modal-specific subprocess line was absent, not deployed, or if Railway (not Modal) was the active scheduler.

### Gap B — the equity arm hardcoded a venue with no execution adapter
`apps/engine/cosmu/research/equity_daa_arm.py` hardcoded `VENUE = "ibkr"`. IBKR has DATA but **no
ExecutionAdapter** in `adapters/exec/registry`, whereas Alpaca equity execution is fully wired on main (and
`orchestrator/loop._FUNDING_VENUE_BY_ASSET_CLASS` already maps `equity -> alpaca`). An IBKR-funded equity
survivor is structurally unable to ever go live — it sim-fills forever while the UI shows "armed". This was the
last broken rung.

---

## The fix — where it hooks

### A. The watchdog now runs INSIDE the paper clock
New function `run_capital_guard_pass(store, *, catalog=None, router=None)` in
`apps/engine/cosmu/orchestrator/loop.py`. It is called from the paper-clock entrypoint `loop._main()` **right
after `mark_tracks(store)`**, so the guard always judges the freshest marked equity:

```
snap = mark_tracks(store)               # the paper clock: mark held positions to the latest real close
...
guard = run_capital_guard_pass(store)   # <-- NEW: reduce-only safety pass over the fresh marks
```

Because `loop._main()` is the canonical paper clock, this makes the watchdog run on **every** cycle it drives:

- Railway full-clock crons (`python -m cosmu.orchestrator.loop`, 00:10 + 22:10 UTC)
- the hourly intraday lane (`--intraday`)
- the mark-only lane (`--mark-only`)
- the Modal `tick` (which runs `python -m cosmu.orchestrator.loop` as one of its steps)

The now-redundant separate `python -m cosmu.ops.capital_guard` subprocess (and its `_live_armed()` helper) were
removed from `apps/engine/remote/app.py` — the orchestrator-loop step the Modal tick already runs now carries the
guard. `python -m cosmu.ops.capital_guard` remains a valid standalone entrypoint for on-demand `modal run`.

Defensive properties:
- **Wrapped in try/except** — a guard error can NEVER crash the marking tick. Worst case is a skipped pass,
  audited as a `capital_guard_failed` event.
- **Strict no-op with nothing funded/armed** — `run_capital_guard()` already returns a clean empty report when no
  funded track holds an open position (no order path touched).
- **Default ON via `COSMU_CAPITAL_GUARD_ENABLED`** (a cadence/cost knob, mirroring `AUTONOMY_CRON_ENABLED`). OFF
  only means the next pass doesn't run; the manual API kill-switch is unaffected (it does not read this flag).
  Default ON is acceptable because the guard can only PROTECT (reduce-only), never deploy.

### B. The equity-arm venue is config-driven
`equity_daa_arm.py`: `VENUE = os.environ.get("COSMU_EQUITY_VENUE", "alpaca").strip() or "alpaca"`. Default is now
`alpaca` (the venue with a real exec adapter, and the same venue the funding loop already routes equity to);
overridable with `COSMU_EQUITY_VENUE=ibkr` for back-compat. Both venues carry all 10 DAA symbols in the catalog
(verified). The per-side ETF fee constant was aliased to a venue-neutral name `EQUITY_ETF_BPS_PER_SIDE` (1.0
bps/side, unchanged value; `IBKR_ETF_BPS_PER_SIDE` kept as a legacy alias). 1.0 bps/side is CONSERVATIVE for both
venues (Alpaca is 0 bps, IBKR ~0.5 bps), so a paper track can never look better than reality by under-charging.

---

## The test
`apps/engine/tests/test_capital_guard_scheduled.py` (6 tests, all passing) exercises the SCHEDULED entrypoint
`loop.run_capital_guard_pass` (not `run_capital_guard` called by hand):

1. **auto-liquidates a drawdown breach** — a funded/armed track whose marked equity (650) breaches the capital
   floor (1000 × 0.70 = 700) is auto-liquidated (reduce-only) by the scheduled pass; position flat, audited.
2. **leaves a healthy track untouched** — equity 1080, no breach -> no action, position held.
3. **no-op with nothing funded** — clean empty report, no order path touched.
4. **disable-by-flag** — `COSMU_CAPITAL_GUARD_ENABLED=0` skips the pass; the breaching track is left for next
   time; the manual kill-switch is unaffected.
5. **never crashes the tick** — an exploding router is swallowed (fail-safe skip), audited as
   `capital_guard_failed`.
6. **does not arm live or touch the interlock** — `_live_enabled(store)` reads False before AND after a pass that
   DID liquidate a breach; the audited close carries `routed_live=False`, `venue='sim'`.

Run: `cd apps/engine && APP_ENV=test python3 -m pytest tests/test_capital_guard_scheduled.py -q` -> 6 passed.
The pre-existing `tests/test_capital_guard.py` (10 tests) still passes unchanged.

---

## Safety analysis — why this cannot arm/deploy/move money

1. **The guard only ever REDUCES.** Every order it builds is `reduce_only=True`, `side=-1` (sell). It has no code
   path that opens or grows a position. The kill/liquidate/trim actions are all closes.
2. **It never flips the live interlock.** Nothing in `run_capital_guard` / `run_capital_guard_pass` writes the
   `live_toggle` row. Live arming stays a human action (the Go-Live modal). Test 6 asserts the interlock is
   unchanged (False) across a pass that actively liquidated a breach.
3. **SIM by default.** With no armed venue, `_resolve_live_adapters(store)` is empty and every protective close
   routes to the SIM/paper book — byte-identical to the paper executor's own exits. Real money can move ONLY once
   the operator has independently armed a venue, and even then only ever to REDUCE exposure.
4. **The Gate is untouched.** No change to `master/`, the FDR gate, the per-combo BRUT model, deflation, or any
   selection logic. The watchdog is downstream of selection — it protects FUNDED capital, it does not decide what
   gets funded.
5. **The venue change is a label/routing default**, not an arm. `equity_daa_arm.arm()` is SIM-only by invariant
   (it opens held SIM positions via `apply_fill`, never a live order). Pointing it at Alpaca only labels the
   track on the venue that could execute IF the operator later arms it — it does not arm it.
6. **Fail-safe, not fail-open-into-trading.** A guard exception is swallowed and audited; the worst outcome is a
   missed protection pass (the next tick retries), never a spurious order.

## Honest limitations
- The implemented breach condition is `GuardConfig.floor_fraction` (liquidate at equity <= starting_capital ×
  0.70, i.e. ~30% drawdown) + the profit-lock give-back, NOT a field literally named `drawdown_killswitch_pct`.
  The test breaches the real implemented floor. If a distinct hard "kill-switch %" threshold is wanted, that is a
  follow-up config addition, not part of this wiring change.
- The guard runs at the paper-clock cadence (daily full clock + hourly intraday). It is NOT a sub-second
  real-time stop; a fast intraday crash between ticks is only caught on the next mark. For the current paper /
  first-live-arm POC this matches the daily/4h rebalance horizon of the funded strategies (TAA/DAA), but a live
  intraday strategy would want a tighter cadence or an exchange-side stop.
- `COSMU_CAPITAL_GUARD_ENABLED` defaults ON; an operator who sets it to 0 disables the AUTOMATIC pass (the manual
  API kill-switch still works). This is intentional (cadence knob) but worth noting.
- Not merged: this is an autonomous-run POC, money-path-adjacent. Review before merge.
