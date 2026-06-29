# USDC liquidity-first base-currency decision module (propose-only)

Date: 2026-06-28
Branch: `claude/usdc-base-currency-2026-06-28`
Status: **PROPOSE-ONLY — DO NOT MERGE yet** (autonomous-run POC). No live order/settlement behavior changed.

## The rule (operator's directive)

Settlement should be **USDC-first when it makes sense**, but **liquidity wins the trade leg**. It is *not* a
blanket USDC-first. Two separate legs:

- **(a) TRADE leg — liquidity wins.** For a `(symbol, venue)`, route the order into whichever stable quote has the
  deeper book. If `BTCUSDT` ~1MM and `BTCUSDC` ~1k, trade **USDT** — routing into the thin USDC book would pay
  spread + impact that dwarfs any settlement preference. When the two books are **comparable**, prefer **USDC**.
- **(b) STORAGE / settlement — defaults to USDC.** When a bot is killed or a position is realized, settle the
  resting balance back to **USDC** by default (the stable end-state).
- **(c) keep USDT only when needed.** Hold USDT while a USDT pair is actively traded, or on a USDT-first venue;
  never churn USDT↔USDC for no reason (every conversion pays a spread).

Net: **store both, trade in whichever quote is liquid, rest in USDC.**

## What was built

`apps/engine/cosmu/spine/base_currency.py` — a **pure, offline** decision module (no store, no network, no clock),
modelled on `spine/fee_router.py` (also pure planning, never the money path). API:

| Function | Signature | What it decides |
| --- | --- | --- |
| `choose_trade_quote` | `(symbol, venue, liquidity_by_quote, *, tolerance=0.25) -> TradeQuoteDecision` | Trade-leg quote — deeper book wins; USDC breaks a near-tie. Returns `(quote, rationale, usdc_liquidity, usdt_liquidity)`. |
| `settlement_quote` | `(venue) -> "USDC" \| "USDT"` | Storage-leg rest currency — USDC default, with venue exceptions. |
| `needs_usdt` | `(symbol, venue, *, actively_trading) -> bool` | Whether USDT must be held now vs swept to USDC. |
| `normalize_quote` | `(quote) -> str` | Folds fiat `USD` → `USDT` for trade-leg depth comparison (never for settlement). |

Constants: `DEFAULT_SETTLEMENT_QUOTE = "USDC"`, `COMPARABLE_BOOK_TOLERANCE = 0.25` (the thinner book must be ≥75%
of the deeper one to count as a tie), `USDC_ONLY_VENUES = {polymarket, hyperliquid}`, `USDT_FIRST_VENUES = {}`.

The module **reuses the existing liquidity representation** rather than inventing one: the caller passes
`liquidity_by_quote` grouped straight off `data.universe.UniverseRow` (`.quote` → `.liquidity_usd_24h`, the
liquidity-ranked `universe_pairs` table). The function stays pure by accepting those figures as inputs.

## Per-venue facts encoded (verified against `spine/venue.py` + `data/venue_universe.py`)

- **Polymarket** — USDC-native settlement (CLOB on Polygon, `quote="USDC"`, 0 fee). USDC-only → trade & rest USDC.
- **Hyperliquid** — USDC collateral perp DEX (`quote="USD"` in rows, but margins in USDC). USDC-only.
- **Kraken** — lists **both** USDC and USDT quotes → resting in USDC is feasible → default USDC.
- **Coinbase** — USD/USDC-first → rest USDC.
- **Binance** — pairs are largely USDT-liquid, so the trade leg will usually pick USDT for majors; but rest still
  defaults to USDC (Binance lists deep USDC pairs too). USDT only persists there while a USDT pair is actively
  traded (`needs_usdt`), not as the resting default.

## Tests — `apps/engine/tests/test_base_currency.py` (18 tests, all green)

Acceptance criteria covered:
- BTCUSDT-deep vs BTCUSDC-thin ⇒ trade USDT (and the mirror, deep-USDC ⇒ USDC).
- comparable books ⇒ prefer USDC; just-outside-tolerance ⇒ liquidity wins.
- settlement defaults to USDC (binance/kraken/coinbase).
- Polymarket ⇒ USDC-native (trade + settle); Hyperliquid ⇒ USDC.
- actively-trading a USDT pair ⇒ `needs_usdt` True; idle / USDC pair / USDC-only venue / bare-base ⇒ False.

Run (this file only, per M2 discipline):

```
python3 -m pytest tests/test_base_currency.py -q   # 18 passed
```

Functional lint (`ruff --select F,B,I,UP`) clean. (E501 long-banner comments match the existing spine house
style — `venue.py`/`fee_router.py` carry the same wide banners; ruff exits 0.)

## The wiring seam (documented, NOT wired)

Live behavior is **byte-identical** — the module is exercised only by its tests. Two future seams, each gated on a
default-off flag (e.g. `settings.base_currency_routing_enabled`):

1. **Trade leg / order routing** — in `orchestrator/paper_step.py` → `adapters/exec/<venue>.submit`, before
   building the `Order`, call `choose_trade_quote(base, venue, liquidity_by_quote)` (figures from
   `data.universe.load_universe(store, venue=venue)`), then resolve the instrument for the chosen quote; fall back
   to the existing pair if that instrument is absent (no behavior change).
2. **Storage leg / settlement on kill-realize** — in the `liquidate_reason` path, convert the resting balance to
   `settlement_quote(venue)` unless `needs_usdt(...)` is True for an adjacent still-active USDT cell at that venue.

Until the flag is flipped, realized cash stays in its current quote exactly as today.

## Honest limitations

- **Not wired** — zero impact on live trading; this is the decision *brain* only. The order-symbol resolution
  (mapping a chosen quote to a catalog instrument) and the actual stable-swap execution are NOT built.
- **Depth figures are caller-supplied** — quality depends on `universe_pairs.liquidity_usd_24h` (24h quote-volume,
  a proxy for true order-book depth at trade size, not the live top-of-book). Good enough to pick the obviously
  deeper book; a thin-margin call should ideally use live book depth at the intended notional.
- **`USDT_FIRST_VENUES` is empty** — no current catalog venue is settlement-USDT-first; the seam exists but is
  unexercised by real data.
- **`_quote_of` is a fallback parser** — `needs_usdt` is most accurate when the caller passes the authoritative
  `UniverseRow.quote`; the bare-symbol parse is only the last resort.
- **Tolerance (25%) is a judgment call** — pinned by a guard test, but not empirically tuned against realized
  slippage; revisit once live book depth is ingested.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
