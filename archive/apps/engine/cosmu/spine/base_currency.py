# intent: the BASE-CURRENCY decision module — "which stablecoin quote do we trade in, and which do we rest in?"
# Two SEPARATE legs, deliberately not collapsed into one blanket rule:
#   (a) TRADE leg  — LIQUIDITY WINS: route into whichever quote (USDT vs USDC) has the deeper book for THIS
#       (symbol, venue). Routing a real order into a thin book pays spread + impact that dwarfs any settlement
#       preference, so the deepest book is the cheap fill. USDC only wins the trade when the two books are
#       COMPARABLE (a configurable tolerance), as the documented tie-break toward the stable end-state.
#   (b) STORAGE / SETTLEMENT leg — DEFAULTS TO USDC: when a bot is killed or a position is realized, the resting
#       balance settles back to USDC by default (the stable, regulator-clean, cross-venue-portable end-state),
#       with documented venue exceptions (a USDT-first venue rests in USDT to avoid a pointless cross-stable hop).
#   (c) needs_usdt — keep USDT ONLY when it's actually load-bearing: the bot is actively trading a USDT pair, or
#       the venue is USDT-first. Don't churn USDT↔USDC for no reason (every conversion pays a spread).
# Net: store BOTH, trade in whichever quote is liquid, rest in USDC.
#
# inputs: the per-(symbol, venue) liquidity figures the CALLER already has (read from data.universe.UniverseRow /
# the universe_pairs table — liquidity_usd_24h per quote), plus a venue id. outputs: a (quote, rationale) decision
# for the trade leg, a settlement quote for the rest leg, and a needs_usdt predicate. invariants: PURE + offline
# (no store, no network, no clock) so it is trivially unit-testable and deterministic; it NEVER sends an order or
# touches the money path — it is PLANNING ONLY, exactly like spine.fee_router. The live order/settlement path is
# unchanged: see WIRING SEAM at the bottom for where this WOULD plug in (behind a default-off flag), not how it does
# today. The per-venue facts (Polymarket USDC-native, Hyperliquid USDC-collateral, Kraken lists both, Binance
# USDT-liquid) are verified against spine/venue.py + data/venue_universe.py.

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# The two stablecoin quotes this module reasons about. (USD is a fiat quote, not a stablecoin balance we hold; it
# is treated as USDT-equivalent for the trade leg only — see normalize_quote — and never as a settlement target.)
USDC = "USDC"
USDT = "USDT"
Quote = Literal["USDC", "USDT"]

# When the two books are within this RELATIVE tolerance of each other, treat them as "comparable" and let the
# settlement preference (USDC) break the tie on the TRADE leg. 0.25 = the thinner book is at least 75% as deep as
# the deeper one. Outside this band, liquidity wins outright (the spread/impact gap is real money). Conservative:
# a real fill cares about depth, so we only divert to USDC when the depth cost is genuinely negligible.
COMPARABLE_BOOK_TOLERANCE = 0.25

# The DEFAULT settlement / resting end-state. Killing a bot or realizing a position settles here unless a venue
# exception applies. USDC: the stable, MiCA-aligned, on-chain-portable end-state the operator asked to rest in.
DEFAULT_SETTLEMENT_QUOTE: Quote = USDC

# Per-venue settlement facts (verified against spine/venue.py + data/venue_universe.py):
#   polymarket   — USDC-native: the CLOB settles in USDC on Polygon; there is no USDT leg, so rest = USDC always.
#   hyperliquid  — USDC collateral: the perp DEX margins in USDC; rest = USDC (no reason to hold USDT there).
#   kraken       — lists BOTH USDC and USDT quotes, so resting in USDC is feasible → default USDC.
#   coinbase     — USD/USDC-first venue → rest = USDC.
#   binance      — pairs are largely USDT-liquid, BUT the operator's rule is rest=USDC by default; Binance lists
#                  deep USDC pairs too, so USDC-rest is feasible. We do NOT mark Binance USDT-first for SETTLEMENT
#                  (that would defeat rest=USDC); USDT only persists on Binance while a USDT pair is ACTIVELY traded
#                  (handled by needs_usdt), not as the resting default.
# A venue listed here as USDT-first rests in USDT (to avoid a pointless cross-stable hop). Empty by default — no
# venue in the current catalog is settlement-USDT-first; this is the documented seam for one that is.
USDT_FIRST_VENUES: frozenset[str] = frozenset()

# Venues whose ONLY stable quote is USDC (no USDT leg exists) — settlement is USDC by construction, and a USDT
# balance there is meaningless. Used by needs_usdt to never demand USDT on a USDC-only venue.
USDC_ONLY_VENUES: frozenset[str] = frozenset({"polymarket", "hyperliquid"})


def normalize_quote(quote: str) -> str:
    """Upper-case + map the fiat 'USD' marker to USDT for TRADE-leg liquidity comparison only.

    A venue may spell a stable-quoted book as 'USD' (Kraken/Coinbase/Hyperliquid/Kraken-Futures all do in the
    universe_pairs rows). For the trade leg, a USD-quoted book is economically a dollar book and competes with a
    USDT book; we fold it to USDT so the deepest *dollar* book is picked. This NEVER applies to the settlement
    leg — we settle to USDC/USDT balances, never to a fiat 'USD' the on-chain wallet can't hold.
    """
    q = quote.strip().upper()
    return USDT if q == "USD" else q


@dataclass(frozen=True)
class TradeQuoteDecision:
    """The trade-leg verdict for one (symbol, venue): which stable quote to route the order into, and why."""

    quote: Quote
    rationale: str
    # The depths the decision was made on (for an audit trail / UI), already normalized + summed per stable quote.
    usdc_liquidity: float
    usdt_liquidity: float


def choose_trade_quote(
    symbol: str,
    venue: str,
    liquidity_by_quote: dict[str, float],
    *,
    tolerance: float = COMPARABLE_BOOK_TOLERANCE,
) -> TradeQuoteDecision:
    """Pick the quote to TRADE a (symbol, venue) in — LIQUIDITY WINS, USDC breaks a near-tie.

    `liquidity_by_quote` maps a quote currency → its 24h USD book depth for this base asset at this venue (read
    straight off data.universe.UniverseRow.liquidity_usd_24h, grouped by UniverseRow.quote). Keys may be any of
    USDC / USDT / USD (USD is folded into USDT by normalize_quote). The caller supplies the figures it already
    has so this stays pure + testable — it does not read the store.

    Rule:
      - deeper book wins outright (routing into the thin book would pay spread + impact that dwarfs any
        settlement preference);
      - when the two books are COMPARABLE (the thinner is within `tolerance` of the deeper), prefer USDC — the
        documented tie-break toward the stable end-state;
      - a venue that only lists USDC (USDC_ONLY_VENUES) trades USDC regardless of the figures.
    """
    if venue in USDC_ONLY_VENUES:
        return TradeQuoteDecision(
            quote=USDC,
            rationale=f"{venue} is USDC-only — no USDT book exists; trade USDC.",
            usdc_liquidity=float(liquidity_by_quote.get(USDC, 0.0)),
            usdt_liquidity=0.0,
        )

    # Fold the raw per-quote figures into the two stable buckets (USD → USDT).
    usdc = 0.0
    usdt = 0.0
    for q, liq in liquidity_by_quote.items():
        nq = normalize_quote(q)
        val = max(0.0, float(liq))
        if nq == USDC:
            usdc += val
        elif nq == USDT:
            usdt += val
        # any other quote (EUR/BTC-quoted) is not a stable book we route into — ignored.

    if usdc <= 0.0 and usdt <= 0.0:
        # No measured stable depth at all → fall back to the stable end-state (USDC). Honest: we don't know the
        # book, so we don't claim a liquidity win; we default to the rest currency.
        return TradeQuoteDecision(
            quote=DEFAULT_SETTLEMENT_QUOTE,
            rationale=f"no measured stable book for {symbol}@{venue} — default to {DEFAULT_SETTLEMENT_QUOTE}.",
            usdc_liquidity=usdc,
            usdt_liquidity=usdt,
        )

    deeper, thinner = (usdt, usdc) if usdt >= usdc else (usdc, usdt)
    comparable = deeper > 0.0 and (thinner / deeper) >= (1.0 - tolerance)

    if comparable:
        return TradeQuoteDecision(
            quote=USDC,
            rationale=(
                f"USDC book ({usdc:,.0f}) and USDT book ({usdt:,.0f}) are comparable "
                f"(within {tolerance:.0%}) for {symbol}@{venue} — prefer USDC (stable end-state)."
            ),
            usdc_liquidity=usdc,
            usdt_liquidity=usdt,
        )

    winner: Quote = USDT if usdt > usdc else USDC
    return TradeQuoteDecision(
        quote=winner,
        rationale=(
            f"{winner} book is materially deeper for {symbol}@{venue} "
            f"(USDT {usdt:,.0f} vs USDC {usdc:,.0f}) — liquidity wins; route {winner}."
        ),
        usdc_liquidity=usdc,
        usdt_liquidity=usdt,
    )


def settlement_quote(venue: str) -> Quote:
    """The quote a position SETTLES / RESTS in when a bot is killed or a position is realized.

    Defaults to USDC (the stable end-state). A venue in USDT_FIRST_VENUES rests in USDT to avoid a pointless
    cross-stable hop (none in the current catalog — the seam is documented). USDC-only venues are USDC by
    construction. This is the STORAGE leg — independent of the TRADE leg's liquidity choice.
    """
    if venue in USDC_ONLY_VENUES:
        return USDC
    if venue in USDT_FIRST_VENUES:
        return USDT
    return DEFAULT_SETTLEMENT_QUOTE


def needs_usdt(symbol: str, venue: str, *, actively_trading: bool) -> bool:
    """Should USDT be HELD for this (symbol, venue) right now, rather than swept back to USDC?

    True when USDT is load-bearing:
      - the bot is ACTIVELY trading a USDT-quoted pair at this venue (selling to USDC and re-buying USDT every
        step would just burn spread), OR
      - the venue is USDT-first (USDT_FIRST_VENUES) — its native quote is USDT.
    False on a USDC-only venue (no USDT to hold), and False when nothing is actively trading USDT (sweep to USDC).
    """
    if venue in USDC_ONLY_VENUES:
        return False
    if venue in USDT_FIRST_VENUES:
        return True
    return actively_trading and normalize_quote(_quote_of(symbol)) == USDT


def _quote_of(symbol: str) -> str:
    """Best-effort quote-currency parse from a venue symbol, for needs_usdt. Mirrors fee_router's quote set so a
    BTCUSDT / BTC-USDT / BTC/USDT all read as USDT-quoted; a bare base ('BTC') / unknown returns '' (not USDT).

    Kept local + tiny on purpose — the authoritative quote is UniverseRow.quote (the caller should pass the real
    quote when it has it); this is only the fallback when all the caller holds is the raw symbol string."""
    s = symbol.upper().strip().replace("-", "").replace("/", "").replace("_", "")
    for q in ("USDT", "USDC", "USD", "FDUSD", "BUSD", "EUR"):
        if s.endswith(q) and len(s) > len(q):
            return q
    return ""


# -----------------------------------------------------------------------------------------------------------------
# WIRING SEAM — where this WOULD plug into the live order-routing + settlement path (NOT wired today).
# -----------------------------------------------------------------------------------------------------------------
# This module changes NO live behavior. It is pure planning, like spine/fee_router.py. Two future seams, both
# behind a default-off flag so the current path stays byte-identical until the operator explicitly opts in:
#
#   1. TRADE leg — order routing. The live lane (orchestrator/paper_step.py → adapters/exec/<venue>.submit) today
#      builds the order symbol straight from the cell's instrument (a fixed USDT pair). The seam: BEFORE building
#      the Order, call choose_trade_quote(base, venue, liquidity_by_quote) where liquidity_by_quote is grouped
#      from data.universe.load_universe(store, venue=venue) rows for this base asset (UniverseRow.quote →
#      liquidity_usd_24h), then resolve the instrument for that quote. If the chosen quote's instrument is absent
#      from the catalog, fall back to the existing pair (no behavior change). Gate this on e.g.
#      settings.base_currency_routing_enabled (default False).
#
#   2. STORAGE leg — settlement on kill/realize. When paper_step.py liquidates a killed version's position (the
#      `liquidate_reason` path) or the live lane realizes a position, the resting balance would be converted to
#      settlement_quote(venue) (default USDC) UNLESS needs_usdt(symbol, venue, actively_trading=…) is True for an
#      adjacent still-active USDT cell at that venue. Same default-off flag; until then the realized cash stays in
#      its current quote exactly as today.
#
# Nothing above is called from any live path in this change. The functions are exercised only by the unit tests.


__all__ = [
    "COMPARABLE_BOOK_TOLERANCE",
    "DEFAULT_SETTLEMENT_QUOTE",
    "USDC",
    "USDC_ONLY_VENUES",
    "USDT",
    "USDT_FIRST_VENUES",
    "TradeQuoteDecision",
    "choose_trade_quote",
    "needs_usdt",
    "normalize_quote",
    "settlement_quote",
]
