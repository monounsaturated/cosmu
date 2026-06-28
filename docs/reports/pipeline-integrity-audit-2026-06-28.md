# Backtest → Paper → Live integrity audit — price · fees · settlement currency

Date: 2026-06-28 · Scope: READ-ONLY trace of the whole pipeline · Gate LOCKED, no engine change.
Author: autonomous audit run (Claude Opus 4.8). All file:line refs are under `apps/engine/cosmu/`.

## BLUF

The pipeline is **largely trustworthy on the money-correctness axis, with one real backtest≠paper fee/cost asymmetry that should be closed before more capital arms.** Fees ARE genuinely per-venue, volume-tiered, and pinned-to-today in the *backtest/screen* path (`master/screen_universe.build_cost_context` → `Venue.cost_inputs()` + `spine/asset_fees.asset_taker_bps`); funding is accrued per-venue in both backtest and paper with the identical sign convention; and per-venue prices use a real "universal price layer" (reference-once + per-venue overlay + a thin-book fallback) that IS wired into the screen. The **top issue** is a parity GAP: the *paper/live order path* (`master/execution.py`) charges a **flat catalog `taker_fee_bps` + a flat 5 bps half-spread with no market-impact term and no per-venue slippage**, and it never calls `asset_taker_bps`. For plain crypto spot/perp (Binance/Kraken/OKX/HL) this agrees with the backtest; but for **Polymarket** (backtest: per-category × (1−price), can be 0–720 bps; paper: 0 bps) and **IBKR equities** (backtest: per-share + min + cap; paper: 0.5 bps) **paper under-charges the very cost the screen modelled** — and paper is the gate that funds live. Live self-corrects via fill reconciliation; paper does not. Secondary: the price-source divergence check is computed and persisted but never read or surfaced (write-only). The USDC settlement module (PR #469) is clean and propose-only, but the order/settlement path has hardcoded single-quote (USDT pair) assumptions, so the rest-in-USDC / liquidity-wins-the-trade intent is not yet consumable without the wiring described below.

---

## Area 1 — Venue fees / funding / slippage, per venue, fees-pinned-to-today, with parity

### 1a. Backtest / screen path — **VERDICT: CONFIRMED-correct**

- Fees are per-(symbol×venue) and asset-aware. `build_cost_context` builds a `fee_schedule` (symbol → bps) and a mirror `depth_schedule` (symbol → (slippage_bps, impact_bps)) from **one** `Venue.cost_inputs()` call per venue so a cell can never pair one venue's fee with another's depth — `master/screen_universe.py:169,178` (`p_taker, p_slip, p_impact = primary.cost_inputs()`; `base_taker, slip, impact = venue.cost_inputs()`).
- Asset classes whose real fee is NOT a flat bps are overridden via `_asset_aware_fee` → `asset_taker_bps` — `master/screen_universe.py:102` (`override = asset_taker_bps(venue, instrument, reference_price=_reference_price(bars))`), `:171,181`. This is Polymarket per-category×(1−price) and IBKR per-share/min/cap — `spine/asset_fees.py:159-184`.
- Fees pinned to TODAY's schedule on every bar (operator rule); funding/slippage stay real-historical — `spine/asset_fees.py:53-57` (`as_of` accepted but ignored: "fees pinned to today's schedule on purpose"). Volume-tiered effective fee — `spine/venue.py:60-67`.
- The backtest charges the per-symbol fee + per-venue depth: `data/backtest.py:282` (`sym_fee = fee_schedule.get(symbol, fee_bps)`), `:287` (`sym_slip, sym_impact = depth_schedule.get(symbol, ...)`).
- Funding accrued per-venue, PIT, sign-correct (long pays positive): `data/backtest.py:737-749` (`flow = -d * float(rate) * position * closes[idx_now]`).
- Slippage = fixed half-spread floor + size-aware sqrt market-impact: `data/backtest.py:40` (`DEFAULT_IMPACT_BPS = Decimal("50")`) and the participation curve `_slippage`, plus the liquidity-tiered floor `_liquidity_floor_bps` (`:65-72`). The single-signal Gate shares this exact curve (`research/gate.py`), so Gate↔backtest parity holds.

No hardcoded/default venue fee in the screen path. This half is correct.

### 1b. Paper step — **VERDICT: GAP** (fee asset-aware + slippage)

- Paper does not charge a fee itself; every fill is an `IntendedOrder` pushed through the **shared** `master/execution.py::execute_orders` (paper passes `live_enabled=False`). The fee comes from `_pit_fee_for_order` — `master/execution.py:252,326-341`.
- `_pit_fee_for_order` reads the cell's OWN venue PIT taker bps (`read_pit_fee(store, venue.id, symbol, "venue_fees_taker", now)` — `master/execution.py:335`), so the *venue* is correct (the cell's catalog venue, recovered per fill). **But** the PIT snapshot source is ccxt `fetchTradingFees` — a **flat** maker/taker bps (`data/providers/fees.py:90`), and the fallback when no snapshot exists is the **flat catalog field** `venue.taker_fee_bps` (`master/execution.py:339`). Neither encodes Polymarket per-category×(1−price) nor IBKR per-share/min/cap. The order path never imports `asset_taker_bps` (grep: zero hits).
  - Consequence: a Polymarket paper cell pays ≈0 bps where the backtest charged 0–720 bps; an IBKR equity paper cell pays ≈0.5 bps where the backtest charged the real per-share commission. Plain crypto spot/perp: no gap (the flat tiered bps IS the backtest fee).
- Slippage: paper crosses the spread at a **flat 5 bps with no impact and no per-venue slippage** — `master/execution.py:29` (`_SIM_SLIPPAGE_FRACTION = Decimal("0.0005")`), `:250`. The backtest charged the per-venue `slippage_bps` (Polymarket 30, Kraken 7, IBKR 2 — `spine/venue.py:48`,`162-314`) **plus** sqrt-impact (impact_bps up to 150 for Polymarket). Documented as intentional ("the order path doesn't see bar volume"), but it means paper under-charges trading cost vs the screen that funded the track — worst on the thin venues where the modelled edge lives.
- Funding: **CONFIRMED-correct** — paper reuses the backtest's own `_funding_series` and the identical sign (`flow = -float(rate) * qty * float(mark)`) — `orchestrator/paper_step.py:213-253,535`.

### 1c. Live executor — **VERDICT: CONFIRMED-correct** (with the same booking-time gap, self-corrected)

- Live is the same `execute_orders` path with `live_enabled=True`; the real submit is `adapter.submit(order)` — `master/execution.py:283`. Booking-time fee = the same `_pit_fee_for_order` (same asset-aware gap at the *estimate*).
- Crucially, live does NOT trust the estimate: `reconcile_fills` fetches the venue's actual fill (`adapter.fills()` — `master/execution.py:569`), overwrites price+fee with the real values (`:589-599`), and emits `fee_model_drift` when drift > 2 bps (`:592-621`). So the persisted live fee converges to the venue's TRUE fee. Wired adapters: binance/kraken/alpaca/polymarket — `adapters/exec/registry.py`.

### 1d. Parity — **VERDICT: GAP** (no single shared cost source)

There is a sizing-parity helper (`master/sizing.size_fraction`, backtest=paper=live) but **no fee/slippage analogue**. Three cost computations exist and diverge for asset-aware venues + slippage:
1. Backtest/screen: `build_cost_context` → `cost_inputs()` + `asset_taker_bps` + sqrt-impact (richest, correct).
2. Gate: `research/gate.py` shares the backtest `_slippage` but its fee fallback is hardwired to Binance's bps (`_FEE_FALLBACK_BPS = default_catalog().venue("binance").taker_fee_bps`).
3. Paper/live order path: flat catalog `taker_fee_bps` + flat 5 bps half-spread, no impact, no asset-aware override.

**Recommended fix (1).** Introduce one shared `effective_taker_bps(venue, instrument, price)` (wrapping `spine/asset_fees.asset_taker_bps` with the catalog/tier fallback) and one shared half-spread/impact resolver from `Venue.cost_inputs()`; have `build_cost_context`, `research/gate.py`, and `master/execution.py::_pit_fee_for_order` all call them — the fee/slippage equivalent of `size_fraction`. Highest-value target is the **paper** lane (Polymarket/IBKR effective fee + per-venue half-spread), because paper is what decides live. Live already self-corrects via reconciliation. Threading bar quote-volume into `IntendedOrder` would let paper also charge the sqrt-impact term and fully close the asymmetry.

---

## Area 2 — Per-venue price, per-symbol fallback, corroboration

### 2a. Per-venue price — **VERDICT: CONFIRMED-correct** (full-native is flag-gated)

- Cells are built per (pair × venue) by `build_crypto_cells`, called from all three screen paths: finder `lab/finder.py:451` (inside `_market`), FarmLoop `evolution/loop.py:945`, API recompute `api/routers/strategies.py:410`.
- Per-venue bars are loaded via `_fallback_provider(venue)` then `provider.fetch_bars(...)` — `data/price_cells.py:330-334`; kraken→Kraken provider, binance→reference, keyless venues (bybit etc.) only with the `COSMU_PER_VENUE_BARS` flag — `data/price_cells.py:186-193`, `data/market.py:240-257`.
- Caveat (deliberate, not a bug): the default is **reference-collapse-on-match** — a venue whose returns track the Binance reference at corr≥0.99 and spread≤25 bps is scored on the reference series (`data/price_cells.py:378-382`, flag default OFF `:174-176`). A divergent/thin venue still falls back to its OWN bars (leakage-safe). Full always-native per-venue bars require `COSMU_PER_VENUE_BARS=on`.

### 2b. Per-symbol reference fallback + per-venue overlay — **VERDICT: CONFIRMED-correct / WIRED**

- `data/reference.py` is the resolver and is actually called (not dead). Reference series computed ONCE per (pair, timeframe, limit) and memoized — `data/market.py:284-294` (`self._memo[key] = bars`); fetched once per pair in the build loop — `data/price_cells.py:320-322`.
- Thin/missing native book → substitute the per-symbol reference (`bars=reference_bars, reuses_reference=True`) — `data/price_cells.py:358-365`; thinness threshold `len(venue_bars) >= UNIFY_MIN_OVERLAP (=60)`.
- Per-venue fee overlay applied downstream via `build_cost_context` (the "fees-only" half), with the real venue stamped per cell — `lab/finder.py:466`.

### 2c. Corroboration / divergence flag — **VERDICT: GAP** (computed + persisted, never read/surfaced)

- The check is real at compute time: `cross_venue_alignment` computes Pearson corr of returns on common timestamps + `median_spread_bps` + overlap — `data/reference.py:187-194`; `decide` flags divergence with strict thresholds biased to FALLBACK (corr≥0.99 AND spread≤25 bps AND overlap≥60) — `:211-222`; persisted per (pair,venue) to `price_alignment` via `persist_decision` — `:243-271`, called at `data/price_cells.py:353,374`.
- The GAP: the verdict + stats are **write-only**. `load_decision` has zero production callers (only a test — `tests/test_universal_price.py:177`), so the "screen reads the inspected decision" promise is unfulfilled (every run re-decides + overwrites). No API router or web code reads `price_alignment`/`median_spread_bps` (grep empty). There is no alert, no "large divergence" flag, no dashboard. A persistent basis/premium correctly FALLS BACK (not a leakage bug), but the operator is never told which (pair,venue) diverged or by how many bps.
- Distinction confirmed: `data/backtest.py:547 _avg_cross_correlation` is strategy-RETURN correlation for the n_obs haircut — NOT price-source corroboration.

**Recommended fix (2).** Call `load_decision` on the screen path (skip the redundant recompute) and add a surface — an API endpoint / leaderboard column / log line — that flags any (pair,venue) whose verdict flips to FALLBACK or whose `median_spread_bps` exceeds a warn threshold, turning the already-measured divergence from write-only into visible.

---

## Area 3 — Settlement currency (USDC-first-when-sensible, liquidity-wins-the-trade-leg)

### Module (PR #469) — clean, propose-only, NOT wired

`spine/base_currency.py` (240 lines, via `gh pr diff 469`) is pure/offline/deterministic, no store/network/clock, never touches the money path — same posture as `spine/fee_router.py`. It encodes exactly the two-leg rule:
- `choose_trade_quote(symbol, venue, liquidity_by_quote)` — LIQUIDITY WINS, USDC breaks a near-tie (`COMPARABLE_BOOK_TOLERANCE = 0.25`), USDC-only venues (polymarket, hyperliquid) force USDC.
- `settlement_quote(venue)` — defaults to USDC, with a documented (currently empty) `USDT_FIRST_VENUES` seam.
- `needs_usdt(symbol, venue, actively_trading)` — keep USDT only when load-bearing.
The module's own docstring marks the two future wiring seams behind a default-off flag (`base_currency_routing_enabled`). It is unit-test-only today.

### Readiness of the rest of the pipeline — **VERDICT: GAP** (not yet consumable; hardcoded single-quote assumptions)

The order/settlement path currently builds the order symbol straight from the cell's **fixed instrument** — a single USDT pair — with no quote-selection seam:
- The catalog's tradable crypto instruments are overwhelmingly `*USDT` pairs (e.g. `BTCUSDT`, `ETHUSDT`, the whole `*-usdt-binance` set) — `spine/venue.py:319-356`; there is no parallel USDC instrument set for the same bases, so even if `choose_trade_quote` returned USDC, `catalog.instrument(symbol, venue)` would not resolve a USDC pair (the module's seam #1 explicitly says "if the chosen quote's instrument is absent, fall back to the existing pair").
- The order is shaped from `intent.symbol` (the cell's instrument symbol) at submit time — `master/execution.py` (`adapter.submit(order)` path, the order symbol comes from the IntendedOrder built in `orchestrator/paper_step.py`). No call to `choose_trade_quote` / `settlement_quote` exists anywhere in the live or paper path (grep: `base_currency` not imported outside its test).
- The kill/realize (settlement) path liquidates a position in its **current quote** — there is no conversion-to-USDC step on `liquidate_reason` in `orchestrator/paper_step.py`; settlement-to-USDC is exactly seam #2, unimplemented.
- Accounting: paper/live P&L and the portfolio book are denominated by the instrument's quote (USDT for the crypto majors). A USDC-rest end-state would need the wallet/ledger to (a) track balances per stable quote and (b) book a cross-stable conversion (its small spread) when sweeping — neither exists today.

**What currently breaks the intent.** (1) No USDC instruments in the catalog for the majors → the trade-leg router has nothing to route INTO. (2) No call site invokes the module. (3) No settlement/sweep step and no per-quote balance accounting → the "rest in USDC" leg has nowhere to land.

**Where it plugs in / recommended fix (3).**
- Trade leg: in `orchestrator/paper_step.py`, BEFORE building the `IntendedOrder`, call `choose_trade_quote(base, venue, liquidity_by_quote)` where `liquidity_by_quote` is grouped from `data.universe.load_universe(store, venue=venue)` rows (UniverseRow.quote → liquidity_usd_24h), then resolve the instrument for that quote; fall back to the existing pair when absent. Gate on `settings.base_currency_routing_enabled` (default False). **Prerequisite:** add USDC instruments for the routable bases to `spine/venue.py` (else there is nothing to route to).
- Storage leg: on `liquidate_reason`/realize, convert the resting balance to `settlement_quote(venue)` unless `needs_usdt(...)` holds for an adjacent still-active USDT cell; requires per-quote balance tracking in the wallet/ledger and a modelled cross-stable conversion cost. Same default-off flag.

---

## Summary table

| Area | Verdict | Top evidence |
|---|---|---|
| 1. Fees/funding/slippage per venue, fees-today | **GAP** (backtest correct; paper/live order path GAP) | backtest `screen_universe.py:102,169,178` correct · paper/live `execution.py:29,339` flat fee + flat 5bps slippage, no `asset_taker_bps` |
| 2. Price per venue + per-symbol fallback + corroboration | **GAP** (per-venue + fallback correct; divergence write-only) | `price_cells.py:320-365` wired · `reference.py:187-222` computes, but `load_decision` has no prod caller |
| 3. USDC settlement readiness | **GAP** (module clean; pipeline not ready) | `base_currency.py` propose-only · catalog is `*USDT`-only (`venue.py:319-356`), no call site, no sweep step |

Net: no leakage bug and no live mis-accounting (live reconciles to true fills). The actionable issue is the **paper-lane fee/slippage parity** for Polymarket/IBKR — it is the gate that funds live, and it currently under-charges exactly the cost the backtest modelled.
