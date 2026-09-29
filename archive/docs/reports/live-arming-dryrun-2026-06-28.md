# Live-arming dry-run — end-to-end capital-path POC (2026-06-28)

**Roadmap #10.** We had never proven the full capital path fires end-to-end. A first real arm would be the first
time the whole chain runs — risky. This is a **deterministic, seeded, SIM/TESTNET-only** test that exercises that
chain once, reversibly, and surfaces every silent gap **before** the operator clicks launch on real money.

- Test: `apps/engine/tests/test_live_arming_dryrun.py` (7 tests, all passing, deterministic across repeated runs)
- Harness reuse: `tests/conftest.py::seed_track_snapshots` (the existing forward-evidence seeder — not duplicated)
- No engine code changed. No merge. Fully reversible. No real key, no network, no prod/DB mutation.

## The path traced (every step uses the REAL production function — never re-implemented)

| Step | Production entry point | What it proves |
|---|---|---|
| 1. Seed matured cell | `master/zero_capital` shape + `conftest.seed_track_snapshots` | a synthetic matured equity (TAA) cell: backdated `track_opened` clock (> `PAPER_MIN_DAYS`), 2 real forward fills (`executions.is_paper=1`), a `scope='track'` `portfolio_snapshots` trajectory that clears the forward-significance bar, a proven-regime passport, a passed backtest + a BRUT `backtest_symbols` `pass` cell |
| 2. Eligibility verdict | `master/live_eligibility.live_eligibility_verdict` | returns **ELIGIBLE** (matured + net-positive + `forward_dsr > PAPER_MIN_FORWARD_DSR` over `>= PAPER_MIN_FORWARD_OBS` marks + in-regime), `overridden=False` (earned by evidence, not a human override) |
| 3. Arming entry | `api/routers/live.live_launch(confirm=True, venue='alpaca', symbol='SHY')` | returns **ARMED**, writes `status='live'` (the only place it is written), freezes the promotion config; the human-arming interlock holds — `confirm=False` refuses and writes **no** status |
| 4. Executor tick | `orchestrator/paper_step.step_tracks` | one tick routes a **TESTNET** order through a stub Alpaca-sandbox adapter (`mode='paper'` → the `testnet` live book), the stub receives the order, and the fill is read back into the book (`is_paper=0`, `venue='testnet'`, `order_submitted_live` audited) |
| 5. Drawdown breach | `ops/capital_guard.run_capital_guard` | a seeded floor breach (equity 60k vs 100k start, below the 0.70 floor) **DISARMS** the cell: a reduce-only `capital_floor` liquidation flattens the held leg, audited as `capital_guard_action` |
| 6. Invariants | `_resolve_live_adapters`, `registry.live_mode` | the Gate verdict + the BRUT `pass` cell are **byte-identical** before/after arming; with the toggle ON but zero keys the real adapter resolver returns `{}` and `live_mode` is `disabled` — **no real-money path is reachable** |

## Does the full path fire end-to-end?

**Yes.** With the synthetic matured cell, the chain runs cleanly: eligible → armed (confirm-gated) → testnet order
routed + filled + booked → drawdown breach disarms via reduce-only close. The 5 execution interlocks
(toggle + keys + gate-passed + caps + no kill-switch) and the regime gate are all exercised on the real code.

## Silent gaps found (the main value of the exercise)

1. **The arming entry is VERSION-scoped, the eligibility readers are CELL-scoped (BRUT triple).** `live_launch`
   calls `live_eligibility_verdict(store, version_id, reference)` with **no `symbol`/`venue`**, so it reads the
   **version-only** `track_opened` passport + forward snapshots. But the per-cell forward evidence is keyed
   `version:symbol:venue` (and, with `tracks_has_cell_columns=True`, the cell readers have **no** version-only
   fallback — Blocker-B). Result: a cell whose forward proof is written ONLY under the BRUT cell key is judged
   **ELIGIBLE when read cell-scoped** (step 1+2) but **"no proven regime on record" when armed** (step 3). The
   test had to seed the passport + snapshots under **both** keys to arm.
   - **Severity: HIGH (latent), not a money-leak.** It fails **safe** (it BLOCKS arming, never over-arms). But
     once tracks are genuinely re-keyed per BRUT triple, the real funder will write evidence under the cell key
     only, and **a legitimately-proven cell will become unarmable through `live_launch`** until the arming path
     passes `symbol`/`venue` into `live_eligibility_verdict`. The `live_launch` body already carries a comment
     acknowledging "until tracks are re-keyed per-triple, a version has exactly ONE funded cell" — this dry-run
     pins the exact follow-up: **thread the launched cell's `symbol`/`venue` into the eligibility call.**

2. **Equity `lot_size` rejects a sized order on a high-priced ETF.** With `sim_track_capital = $1000` and a
   `size_fraction ~0.5`, an arm on SPY (~$550) sizes to **< 1 whole share** and the order is gauntlet-rejected
   (`lot_size`, `risk.py` `order.qty < instrument.lot_size`), so **nothing routes** — the executor reports
   `opened=0` with an `order_rejected[lot_size]` event, no error. The dry-run uses **SHY** (~$82, a real TAA
   "safe asset") so $1000 buys ~6 shares and the entry routes.
   - **Severity: MEDIUM.** Real TAA/DAA sleeves can hold high-priced ETFs (SPY/QQQ/EFA). A live arm of such a
     cell at the current $1000 per-track sizing would **silently never open a position** (rejected as `lot_size`,
     not surfaced as an arm failure). Follow-up: either raise per-cell capital for equity arms, or warn at arm
     time when `sized_qty < instrument.lot_size` for the chosen cell.

Neither gap is a real-money leak; both fail safe (block / no-op). They are exactly the "silent" wires this POC
was built to surface before a first real arm.

## Confirmation: no real-money path reachable in the test

- Throwaway sqlite Store; `_env_file=None` (never inherits the dev box's `.env.local` keys).
- The only "live" adapter is an in-process **stub** (`mode='paper'` → the `testnet` book) — it never opens a
  socket, never carries a key, never touches a real venue. `_resolve_live_adapters` is monkeypatched so the
  executor can only ever see the stub.
- `conftest`'s autouse network guard fails any test that opens a real TCP/UDP socket — none did.
- Step 6 asserts: toggle ON + zero keys → real `_resolve_live_adapters(store) == {}` and
  `registry.live_mode(settings) == 'disabled'`. Arming the toggle alone can never hand the order path a real
  adapter.
- The Gate (`backtests.passed_gates`) and the BRUT `backtest_symbols` `pass` cell are read but **unchanged** by
  arming.

## How to run

```
cd apps/engine && python3 -m pytest tests/test_live_arming_dryrun.py -q
```

(Run ONLY this file — M2 discipline; deterministic, ~1.2 s, no network.)
