# Paper-lane fee parity with the backtest — per-venue `asset_taker_bps` for Polymarket/IBKR

Date: 2026-06-28 · Branch: `claude/paper-fee-parity-2026-06-28` · Scope: a money-honesty fix that TIGHTENS
non-crypto paper fees to match the backtest. Gate LOCKED, no scoring constant/formula touched, no money moved.
Author: autonomous run (Claude Opus 4.8). All file refs under `apps/engine/cosmu/`.

## The gap (from the pipeline-integrity audit, PR #472)

The BACKTEST/SCREEN path charges fees correctly — per-venue, volume-tiered, asset-aware, pinned-to-today — via
`spine/asset_fees.asset_taker_bps` called from `master/screen_universe.build_cost_context` (`_asset_aware_fee`).
But the PAPER/LIVE ORDER path `master/execution._pit_fee_for_order` charged a flat catalog `taker_fee_bps`
(or a flat PIT snapshot) and **never called `asset_taker_bps`**. For plain crypto spot/perp this AGREES with the
backtest. For the two ASSET-AWARE venues it did NOT:

- **Polymarket** — real fee is per-category × (1 − price), 0–720 bps. Paper charged the catalog placeholder ≈0 bps.
- **IBKR equities** — real fee is per-share + per-order min + value cap. Paper charged the flat 0.5 bps placeholder.

Because **paper is the gate that funds live**, an under-charged paper P&L can fund a strategy that is unprofitable
after real fees. Live self-corrects (`reconcile_fills` overwrites the booking estimate with the venue's true fill
and emits `fee_model_drift`); paper does not. This fix closes the paper asymmetry.

## The fix — one shared fee resolver, wired into the paper lane

### 1. Shared resolver `effective_taker_bps` (`spine/asset_fees.py`)
The fee analogue of `master/sizing.size_fraction`. Wraps `asset_taker_bps`:

- ASSET-AWARE venue (Polymarket / IBKR) → the per-asset/per-category effective taker bps the backtest used.
- Any other venue (Binance/Kraken/OKX/HL spot+perp) → **`None`**, the signal to the caller to keep its own flat
  base/tiered bps (or PIT snapshot). This is what keeps crypto byte-identical.

`ASSET_AWARE_VENUES` is now defined ONCE here and imported by `master/screen_universe` (was a duplicate literal),
so the screen and the order path can never disagree on which venues need the override — DRY.

### 2. Wired into the paper lane (`master/execution._pit_fee_for_order`)
`execute_orders` already resolves the cell's `instrument` from the catalog; it is now threaded into
`_pit_fee_for_order`. Resolution order (single chokepoint):

1. `effective_taker_bps(venue, instrument, reference_price=fill_price)` — the asset-aware override (Polymarket /
   IBKR). For crypto this returns `None` and we fall through unchanged.
2. PIT fee snapshot from the alt_data store (crypto, this account's tiered taker bps).
3. Static catalog taker fee (offline / pre-first-ingest).

So a Polymarket/IBKR paper order now pays the SAME per-venue, asset-aware, pinned-to-today fee the backtest used.

## Venues corrected vs unchanged

| Venue / asset | Before (paper) | After (paper) | Direction |
|---|---|---|---|
| **Polymarket** (per-category × (1−price)) | flat catalog ≈0 bps | per-category override (e.g. economics 5% × (1−p) → 300 bps @ p=0.40) | **tightened (much higher)** |
| **IBKR equity** (per-share + min + cap) | flat 0.5 bps | real per-share at the $10k reference (e.g. 0.7 bps @ $50 share) | **tightened where per-share/min dominates; equals the backtest in all cases** |
| **Crypto spot/perp** (Binance/Kraken/OKX/HL) | flat catalog or PIT bps | **identical** (override returns None) | **unchanged (byte-identical)** |

IBKR honest nuance: `asset_taker_bps` evaluates IBKR at a fixed **$10k reference notional** (the same the screen
uses), so paper == backtest **by construction**. At low share prices the per-share + $0.35 min-order floor pushes
the effective bps ABOVE the 0.5 placeholder (tightens); at high prices the real cost can sit below 0.5, but that is
exactly the backtest's number — the fix removes the *asymmetry*, it does not invent a higher fee. The dominant
honesty win is Polymarket (≈0 → up to 720 bps).

## Tests (`tests/test_paper_fee_parity.py`, 10 cases — all green)

- `effective_taker_bps`: returns the override for Polymarket/IBKR, `None` for crypto (with and without instrument).
- `_pit_fee_for_order`: Polymarket charges per-category × (1−price) (not ≈0); IBKR charges per-share (not flat 0.5),
  both strictly above the old placeholder; crypto unchanged (catalog flat AND PIT snapshot paths both preserved).
- End-to-end `execute_orders` (PAPER, `live_enabled=False`): the `executions` row books the parity fee for a
  Polymarket and an IBKR order (> the flat placeholder) and the **byte-identical** flat-10-bps fee for a crypto
  order (on the half-spread-crossed fill price).

Adjacent suites re-run green: `test_asset_fees`, `test_dynamic_fees`, `test_order_path_and_portfolio`,
`test_oco_and_reconciliation`, `test_screen_universe`, `test_sandbox_per_combo`, `test_live_caps_enforced`,
`test_live_ignition`, `test_capital_guard`.

## Invariants honored

- **Only tightens, never loosens** non-crypto paper fees relative to the placeholder; never credits a maker rebate;
  never lowers a crypto fee.
- **Crypto byte-identical** — `effective_taker_bps` returns `None`, the existing PIT-then-catalog path is untouched.
- **Gate untouched** — no scoring constant or formula changed; the resolver is purely on the order-cost path.
- **Live reconciliation untouched** — `reconcile_fills` and `fee_model_drift` are unchanged; live still converges to
  the venue's true fill.
- **No money moved, reversible** — draft PR, not merged.

## Honest limitations / follow-ups

- **Market-impact / sqrt-impact** is NOT charged in paper (the order path still uses the flat 5 bps half-spread and
  has no bar quote-volume). This is the noted follow-up; the seam is the `IntendedOrder` (would need bar volume
  threaded in). The required taker-bps parity is delivered; the impact term is out of scope here.
- **Per-venue half-spread/slippage parity** (Polymarket 30 / IBKR 2 vs the flat 5 bps) is likewise deferred — same
  reason (the order path doesn't see bar depth). Charging the flat 5 bps stays an under-charge on thin venues; this
  PR closes the *taker-fee* half only, which is the larger and exactly-modelled gap.
- The shared resolver is wired into the **paper** lane (the priority — the gate that funds). `research/gate.py` and
  `build_cost_context` already compute the asset-aware fee directly; re-pointing them at `effective_taker_bps` for
  full single-source DRY is a mechanical follow-up (no behavior change — they already produce the same number).
