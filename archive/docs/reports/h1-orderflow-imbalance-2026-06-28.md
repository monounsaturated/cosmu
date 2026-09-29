# H1 — Aggressive-trade-imbalance REVERSAL on small-cap perps (intraday axis → BRUT Gate)

**Date:** 2026-06-28
**Author:** autonomous Claude Code run (Opus 4.8)
**Type:** OFFLINE kill-experiment — pure read of keyless Binance Vision aggTrades + local file writes. NO prod
side effects, NO Gate-constant change, NO money path.
**Axis:** intraday market microstructure (aggressive trade flow) — the **first genuinely-new, reachable signal
axis** for COSMU. Every prior edge is a daily price/calendar/attention signal and all 96 hit the same regime/fee
wall (0/96 survive). This is the #1 recommended experiment from the feasibility spike
(`docs/reports/intraday-orderflow-feasibility-2026-06-28.md`, PR #462 — GO on data reachability).

---

## TL;DR — VERDICT: **KILL** (clean, on a NEW axis — a valid, valuable result)

The aggressive-trade-imbalance fade on small-cap perps is **dead at a tradeable 1-minute maker cadence**:

- **0 of 7** small-cap perps cleared the locked BRUT Gate. Every cell fails on 5 statistical criteria
  (max_drawdown, folds_positive, pbo, deflated_sharpe, buy_and_hold) and on the economics.
- **The gross edge is microscopic** — per-trade GROSS forward returns are **+0.05 to +1.96 bps**, far below
  the maker round-trip cost (~30 bps catalog, ~14 bps even at the real perp-maker schedule). The strategy
  bleeds fees to a near-total loss on every symbol (net total −67% to −99%).
- **Shuffle-null (the disconfirmer):** for 5 of 7 symbols the real net edge is **indistinguishable** from a
  re-signed-aggressor null (p = 0.24–0.52) — the "edge" carries no order-flow information. For 2 of 7 (FIL
  p=0.040, OP p=0.075) there is a **faint but real** order-flow signal (~2 bps gross), which honestly shows the
  shuffle-null is calibrated (it *can* detect a real signal) — but ~2 bps is economically meaningless at this
  turnover.
- **Pre-registered KILL met:** the signal cannot clear ~10-bps-class round-trip economics net of fees at a 1m
  decision cadence. We did NOT torture the data to manufacture a survivor — one window, one threshold, no sweep.

This is exactly the cost-wall the feasibility spike flagged as the binding risk: **turnover × fees**, not data.
The intraday data axis is genuinely reachable and direction-carrying; this *particular* signal at *this* cadence
does not monetize. (See "What this does and does not close" below — it does NOT exhaust the axis.)

---

## 1. Pre-registration (locked BEFORE looking at any return)

| Parameter | Value |
|---|---|
| Signal | trailing aggressive-trade imbalance `(Σ taker-buy − Σ taker-sell) / Σ total` over a window |
| Imbalance window | **15 minutes** |
| Entry threshold | **\|imbalance\| ≥ 0.40** |
| Direction | **FADE**: short an extreme +imbalance, long an extreme −imbalance (reversal hypothesis) |
| Holding horizon | **5 minutes** (fixed-time exit at close of t+5) |
| No-overlap | a new entry must be ≥ 5 minutes past the last entry |
| Shuffle-null | **K = 200** permutations of the aggressor labels (re-sign, preserve total volume per minute) |
| Symbols | 7 small-cap perps: SEI, ARB, FIL, GALA, RUNE, JUP, OP (USDT, Binance USDⓈ-M) |
| Window | 2025-02-01 → 2025-03-31 (~2 months, ~85k 1m bars/symbol) |
| Cadence | 1-minute decision clock (we are **not** HFT; no taker/latency lane) |
| Trial count | **1 per cell** — ONE pre-registered signal, NO parameter sweep |

ONE signal, ONE threshold. The trial count stays honest: the per-cell DSR deflation uses `trials_counted = 1`
(the brut per-combo gate; no sibling pooling, no family FDR).

## 2. Data — keyless, PIT-honest Binance Vision aggTrades

- Source: `data.binance.vision/data/futures/um/daily/aggTrades/{SYM}/{SYM}-aggTrades-{YYYY-MM-DD}.zip` — keyless,
  immutable daily zips, back to listing. Fetched + resampled to 1m flow bars via the new
  `cosmu/data/intraday_aggtrades.py` (the same zip-fetch pattern as `intraday_binance_vision.py` /
  `BinanceVisionBarBackfiller`, pointed at the `aggTrades/` prefix).
- **Sign convention (read FROM the data, not guessed)** — confirmed against a live ARBUSDT perp day
  (2025-01-15). Column schema: `agg_trade_id, price, quantity, first_trade_id, last_trade_id, transact_time,
  is_buyer_maker`.
  - `is_buyer_maker == false` → the **buyer was the taker** → **aggressive BUY** → adds to buy volume.
  - `is_buyer_maker == true`  → the buyer was the maker (seller is taker) → **aggressive SELL** → sell volume.
- PIT: each aggTrade is stamped at its own `transact_time` (event time, no revision); a 1m flow bar is knowable
  only at its close. The signal at minute t uses only the trailing window through t's close; entry is at t's
  close; the forward return is `close[t+5]/close[t]−1`. No look-ahead. A 404 day is skipped, never zero-filled.

## 3. Economics — MAKER-ONLY (we do NOT play the taker/latency lane)

- Round-trip cost = 2 × (maker_bps + slippage_bps) from `cosmu/spine/venue.py` (Binance catalog):
  **maker 10 bps + slippage 5 bps → 30 bps round-trip.**
- **Honest note:** the Binance catalog `maker_fee_bps = 10` is the *spot* schedule. For USDⓈ-M *perps* the real
  maker is ~2 bps, so a realistic perp-maker round-trip is ~14 bps — this experiment's 30 bps is **conservative**
  (harder on the strategy). It does not matter for the verdict: the largest gross edge across all 7 symbols is
  **1.96 bps**, so even a hypothetical **0-bps** cost leaves a signal too weak to clear the pre-registered
  ~10-bps-class bar — and 5 of 7 cells are statistically indistinguishable from the shuffle-null regardless of
  cost.
- The locked Gate prices the cell against the catalog `venue.py` fee. Maker-fill realism is assumed (limits fill)
  — a generous upper bound; even so, the cell loses.

## 4. Results — per (symbol × venue) BRUT

All cells: venue = `binance`, window 2025-02-01..2025-03-31, ~85k 1m bars each. Edges in basis points (1 bp = 0.01%).

| Symbol | trades | gross edge/trade | net edge/trade | shuffle-null mean | shuffle p-value | net total return | buy&hold | DSR | **Gate** |
|---|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| SEIUSDT  | 1480 | +0.64 bps | −29.36 bps | −29.91 bps | 0.323 | −98.72% | −48.23% | 0.000 | **REJECT** |
| ARBUSDT  |  905 | +0.05 bps | −29.95 bps | −29.95 bps | 0.522 | −93.40% | −49.06% | 0.000 | **REJECT** |
| FILUSDT  |  831 | +1.96 bps | −28.04 bps | −29.96 bps | **0.040** | −90.32% | −42.57% | 0.000 | **REJECT** |
| GALAUSDT |  778 | +0.91 bps | −29.09 bps | −29.96 bps | 0.244 | −89.67% | −52.50% | 0.000 | **REJECT** |
| RUNEUSDT | 1080 | +0.86 bps | −29.14 bps | −29.97 bps | 0.254 | −95.74% | −46.55% | 0.000 | **REJECT** |
| JUPUSDT  |  677 | +0.34 bps | −29.66 bps | −30.08 bps | 0.403 | −86.64% | −59.36% | 0.000 | **REJECT** |
| OPUSDT   |  387 | +1.70 bps | −28.30 bps | −30.08 bps | 0.075 | −66.68% | −48.85% | 0.000 | **REJECT** |

Gate reasons (every cell, identical): `min_drawdown`, `folds_positive`, `pbo`, `deflated_sharpe`,
`buy_and_hold`. Net total return = compounded per-bar net-of-fee equity (base 100k); buy&hold = the symbol's own
net buy-and-hold over the window (each cell beaten on its OWN benchmark — the brut, no-pooling rule).

### Reading the table
- **Gross edge ≤ 1.96 bps everywhere.** The fade has essentially no raw predictive power for a 5-minute forward
  return on these names. ARB's gross edge (+0.05 bps) is statistically zero (p=0.52 — the real net edge sits at
  the *median* of the shuffle-null).
- **Shuffle-null disconfirmer:** 5/7 cells (SEI, ARB, GALA, RUNE, JUP) are indistinguishable from the re-signed
  null at p ≫ 0.05 → those "edges" are not order-flow. 2/7 (FIL p=0.040, OP p=0.075) show a *faint, genuine*
  order-flow signal — the null is calibrated, it just confirms the real signal is ~2 bps, economically dead.
- **Economics:** with a 30-bps maker round-trip and ~700–1500 round-trips over 2 months, fees compound to a
  −67% to −99% wipeout. This is the canonical intraday turnover×fee wall.

## 5. Gate path (locked, unchanged)

Each cell routed through the EXISTING brut path with zero Gate-constant change:
`equity stream → cosmu.data.backtest._symbol_metrics → metrics_for_run(trials=1, buy_and_hold=<own>) →
cosmu.master.cohort.promote_brut(GateSettings())`. GateSettings defaults (LOCKED): min_deflated_sharpe_prob
0.95, min_trades 30, max_drawdown 0.25, max_pbo 0.50, min_folds_positive 0.60, require_beat_buy_and_hold True.
No constant was touched; `promoted == passed` per cell on its OWN streams.

## 6. What this does and does NOT close

**Closes:** the H1 hypothesis as pre-registered — a single fixed-window/fixed-threshold imbalance FADE at a 1m
maker cadence on small-cap perps **does not monetize**. A KILL on a new axis is a real result; we spent only a
research harness to learn it, and we built clean, reusable plumbing (`intraday_aggtrades.py` + tests) for the
whole intraday-microstructure axis.

**Does NOT close (the axis remains open):** this is ONE signal/threshold/horizon, not the axis. The faint real
signal on FIL/OP (and the calibrated shuffle-null) shows order-flow information *exists* in the tape — it is just
too weak to clear 1m turnover×fees. Lines that remain unexplored and are NOT refuted by this run:
- **H2 — book depth-imbalance** (Binance futures `bookDepth`), a different and possibly stronger microstructure
  signal with lower required turnover.
- **Lower-turnover variants of flow** — a much higher entry threshold (rarer, larger overshoots) and/or a longer
  horizon, which would cut the round-trip count by 10–100× and could let a 1–2 bps gross edge survive. (Any such
  variant is a NEW pre-registration with its own trial count — not a sweep on this one.)
- **Cross-symbol / portfolio flow** (relative imbalance), unseen by a per-symbol fade.

## 7. Compute note (M2 discipline)

Run on the local M2: 7 symbols × ~2 months of keyless aggTrades, resampled to 1m flow bars (the per-symbol 1m
cache is tiny — a few MB; raw zips are not retained). The shuffle-null (200 perms × ~85k bars/symbol) is the
CPU-bound cost; the rolling-O(n) imbalance keeps it M2-tractable. **A fuller run is NOT warranted by these
numbers** — the gross edge is so far below cost that more symbols/months/permutations would only re-confirm the
KILL. A fuller run (wider universe, 6+ months, finer fill model) would be justified only for a NEW hypothesis
(e.g. H2 bookDepth, or a low-turnover flow variant), at which point it belongs on **Modal** (raw aggTrades bulk +
the heavy null), not the M2.

---

## Reproduce

```
cd apps/engine
python3 scripts/research/h1_orderflow_imbalance_2026_06_28.py            # full run (downloads aggTrades)
python3 scripts/research/h1_orderflow_imbalance_2026_06_28.py --self-test  # tiny synthetic end-to-end, no network
pytest tests/test_intraday_aggtrades.py tests/test_h1_orderflow_imbalance.py -q
```

Result blob: `apps/engine/scripts/research/h1_orderflow_imbalance_results_2026_06_28.json`.
