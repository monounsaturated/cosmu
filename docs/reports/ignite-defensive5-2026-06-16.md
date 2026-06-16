# TASK I — Ignite `defensive5` SIM→live (operational ignition against Alpaca) — 2026-06-16

Operational run of the **already-built** SIM→live order wire against **Alpaca PAPER** (zero real money),
plus the one real code bug it surfaced. Live trading stays OFF in prod (`live_toggle.enabled=0`); nothing
here arms it.

## 1. What was OBSERVED (not asserted)

**1b — the real-venue `submit()` path works end-to-end (first time ever).** Before today, all **43**
`executions` rows were `is_paper=1` — the real venue submit() path had only run against mocks. Driving one
gate-passed entry (`BUY 1 IEF`) through the **real** `master.execution.execute_orders` with the **real**
`AlpacaExecutionAdapter` (paper keys from `.env.local`, `live_enabled=True`):

- `OUTCOME: accepted=True, routed_live=True` — routed LIVE through the 5-interlock (`execution.py:192`).
- The order **really landed on Alpaca's paper API**: a real venue order id was returned
  (e.g. `c8d7f427-…`, `status=accepted`, `submitted_at=2026-06-16T02:37Z`) and was visible via
  `GET /v2/orders:by_client_order_id`. Not a mock.
- The `executions` row wrote `is_paper=0`; `order_submitted_live` + `execution_filled (is_paper:false)`
  events were emitted.
- The order was then **cancelled** on Alpaca (market was closed → it would otherwise fill at the next open);
  the paper account was left clean (0 orders / 0 positions).

> Market hours: the Alpaca clock was **closed** at run time (next open 2026-06-16 09:30 ET), so a market
> order is *accepted* and fills at the open. The proof here is the real **submit()** integration; the fill
> itself is a market-open event outside this run's control.

**1a — the slow/monthly hold path.** `StrategySpec.horizon.bar_size` is `Literal["1h","4h","1d"]` — there is
**no monthly bar**, so a "monthly-rebalanced" equity sleeve runs the **daily** clock. `step_tracks` was
verified to OPEN a slow track once and then HOLD it across many daily ticks **without churn** (no re-entry /
no double-fill — the decision-bar-stamped `client_order_id` makes a same-bar re-tick a no-op, and a held
position is only re-touched on an actual exit signal), while `mark_tracks` keeps marking equity. Test:
`test_step_tracks_slow_strategy_holds_no_churn_and_marks_equity`.

## 2. The bug this surfaced (fixed)

`master.execution._live_venue` mapped only `testnet`/`live` to a live book and let everything else fall to
`"sim"`. **Alpaca's sandbox mode is `"paper"`**, so an Alpaca-paper order that genuinely routed to the real
venue wrote `is_paper=0` **but booked its position under `venue="sim"`** — colliding with the deterministic
offline-paper book and, worse, making it invisible to `step_tracks`' `held_live` (which reads
`venue in ("live","testnet")`), so the live executor could never manage/exit it.

Fix: `_live_venue` now normalizes a venue **sandbox** (`paper`→`testnet`) to the live book — mirroring
`registry.live_mode`'s existing paper→testnet normalization. After the fix the same order books to
`venue="testnet"` with `is_paper=0`, and `step_tracks.held_live` manages it. The 5-interlock
(`execution.py:192`) and `_resolve_live_adapters`' SIM-only safe default (`paper_step.py:265-281`) are
**untouched**. Tests: `test_live_venue_normalizes_paper_to_testnet`,
`test_alpaca_paper_order_books_on_live_testnet_book_not_sim`.

## 3. What is BLOCKED (honest)

**1c — the first real dollar: BLOCKED on a missing credential, not the regime gate.** `.env.local` has
`ALPACA_PAPER_API_KEY/SECRET` but **no live `ALPACA_API_KEY/ALPACA_API_SECRET`**, and `live.mode=testnet`.
`resolve_mode` therefore can only return `paper`; real money is impossible until the operator adds live
Alpaca keys (and flips `live.mode=real` with paper keys removed). No keys were invented or committed. When
keys exist, the launch still has to clear the **hard regime gate** (`live_eligibility.py`) — never bypassed.

## 4. Architecture reality found along the way (for the next step)

- **`defensive5` is not a DB row.** It exists only as a research 1/N **monthly ensemble** of 5 published TAA
  rotations (`research/equity_taa_ensemble.py`: DAA+PAA+GTAA+TSMOM+HAA) evaluated on *monthly return
  streams* — not a per-bar tradeable `StrategySpec`. A `step_tracks` track manages a single-symbol spec; it
  does **not** rebalance a multi-asset basket (that's the deploy-lane arms' job, which `step_tracks` skips).
- **The TAA member tracks are booked on `venue='ibkr'`, which is `enabled=0` and has no execution adapter.**
  So they are neither `step_tracks`-managed (wrong venue label) nor live-routable. The **only** wired
  equities exec venue is **`alpaca`**. Re-pointing the equity sleeve from the dead `ibkr` venue to `alpaca`
  (a spec/catalog change with screening implications) is the genuine next step toward a defensive5 live
  launch — deliberately **not** done here to avoid fabricating an unmanageable "track".
