# intent: the ONE per-asset / per-category fee model — turn a venue's REAL commission structure (which is NOT a
# flat bps for Polymarket or IBKR) into an effective TAKER bps the backtest cost path can charge per (symbol,venue).
# inputs: an Instrument (asset_class / instrument_type / contract_multiplier / category) + a reference price; outputs:
# effective taker bps. invariants: ALWAYS-TAKER (the OHLCV Bar model has no depth to justify a maker assumption, so
# crediting a maker rebate would inflate edge = leak); FEES-PINNED-TO-TODAY (operator rule — every bar, even years
# old, is charged TODAY's fee schedule so the backtest answers "what would this cost to run NOW"; funding/slippage
# stay real-historical, fees do not); CONSERVATIVE (no maker rebates credited; unknown Polymarket category defaults
# to the most-expensive crypto rate). Venue base/tiered bps stays the
# single source for plain spot/perp (Binance/Kraken/OKX/HL) — this module ONLY overrides the asset classes whose real
# fee is not a flat bps (prediction, equity/future at IBKR).

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from cosmu.spine.venue import Instrument, Venue

# --- Polymarket per-category taker fee --------------------------------------------------------------------------
# Polymarket charges the TAKER a fee proportional to the realized P&L room of the share: fee = shares × feeRate ×
# price × (1 − price). feeRate is set PER MARKET CATEGORY. Maker side earns a rebate — modelled here as 0 cost
# (upside only; never credited in a backtest, which would flatter the edge).
# Source: docs.polymarket.com/trading/fees + help.polymarket.com (per-category schedule, effective 2026-03-23):
# the ONLY fee-free category is the official "Geopolitical & World Events" (keyed here as `geopolitics`); sports 3%;
# politics/finance/tech/mentions 4%; economics/culture/weather/other 5%; crypto 7% (the most expensive). Verified
# against the published $/100-shares max table (max fee at p=0.5 = feeRate×0.25: sports $0.75, the 4% tier $1.00,
# the 5% tier $1.25, crypto $1.80). `world` is NOT a distinct official category — world events fall under the
# fee-free "Geopolitical & World Events" (use `geopolitics`); a bare `world` tag is treated as the general 5% rate
# (the old `world: 0.00` was an unjustified over-credit on a non-official key).
POLYMARKET_CATEGORY_FEE_RATE: dict[str, float] = {
    "geopolitics": 0.00,  # official "Geopolitical & World Events" — the only fee-free category
    "world": 0.05,        # NOT an official category → general rate (was a bogus 0.00 over-credit)
    "sports": 0.03,
    "politics": 0.04,
    "finance": 0.04,
    "tech": 0.04,
    "mentions": 0.04,
    "economics": 0.05,
    "culture": 0.05,
    "weather": 0.05,
    "other": 0.05,
    "crypto": 0.07,
}
# Unknown / unmapped category → the most-expensive (crypto) rate, the conservative default (over-charge, never
# under-charge, when we don't know the category).
POLYMARKET_DEFAULT_FEE_RATE: float = POLYMARKET_CATEGORY_FEE_RATE["crypto"]


def polymarket_category_fee_rate(category: str | None) -> float:
    """The Polymarket taker feeRate for a market category (0.00–0.07). Unknown/None → the conservative crypto
    rate (0.07) — over-charging an unmapped market is honest; under-charging would manufacture edge."""
    if category is None:
        return POLYMARKET_DEFAULT_FEE_RATE
    return POLYMARKET_CATEGORY_FEE_RATE.get(category.strip().lower(), POLYMARKET_DEFAULT_FEE_RATE)


def polymarket_taker_bps(category: str | None, price: float, *, as_of: datetime | None = None) -> Decimal:
    """Effective Polymarket taker fee in BPS of notional for a share priced at `price` (a probability in (0,1)).

    fee_per_share = feeRate × price × (1 − price); notional_per_share = price; so fee/notional = feeRate × (1 − price)
    → bps = feeRate × (1 − price) × 10_000. FEES ARE ALWAYS TODAY'S SCHEDULE (operator rule): we charge the CURRENT
    per-category fee on EVERY bar, including historical ones — the backtest answers "what would this cost to run
    NOW", so there is no surprise at live launch. `as_of` is accepted for signature compatibility but IGNORED (fees
    are pinned to today, never point-in-time; funding/slippage stay real-historical, fees do not)."""
    del as_of  # fees pinned to today's schedule on purpose — never point-in-time
    p = max(0.0, min(1.0, price))
    rate = polymarket_category_fee_rate(category)
    return Decimal(str(rate * (1.0 - p) * 10_000.0))


# --- IBKR per-asset-class commission ----------------------------------------------------------------------------
# IBKR's REAL fee is NOT a flat bps — it is per-share (equities/ETFs, with a per-order MIN and a value CAP),
# per-contract (futures, scaled by the contract multiplier), or value-percent (EU equities, with a per-order min +
# the French FTT on the buy leg). The flat 0.5/0.5 bps catalog field is kept only as a last-resort fallback.
# Default plan = IBKR Tiered. Options are DEFERRED (skip).
IBKR_US_PER_SHARE: float = 0.0035          # $/share (us_equity, us_etf)
IBKR_US_MIN_ORDER: float = 0.35            # $ min per order
IBKR_US_VALUE_CAP_PCT: float = 0.01        # commission capped at 1% of trade value
IBKR_US_FUTURE_PER_CONTRACT: float = 0.85  # $/contract (us_future)
IBKR_EU_FUTURE_PER_CONTRACT: float = 0.90  # €/contract (eu_future)
IBKR_EU_EQUITY_PCT: float = 0.0005         # 0.05% of value (eu_equity)
IBKR_EU_EQUITY_MIN: float = 1.25           # € min per order
# French Financial Transaction Tax: 0.40% on the BUY leg ONLY, for FR-HQ large-caps (>€1bn mkt cap). Modelled as a
# buy-leg-only asymmetry (NOT folded into commission) — see ibkr_ftt_buy_leg_bps.
FRENCH_FTT_RATE: float = 0.004


def ibkr_commission_usd(instrument: Instrument, qty: float, price: float) -> float:
    """IBKR per-asset-class commission for ONE leg, in the trade's currency (USD for US, EUR for EU — the caller
    treats it as a fraction of the same-currency notional, so the unit cancels into bps). Excludes the French FTT,
    which is a buy-leg-only tax modelled separately. `qty` is shares (equity) or contracts (future)."""
    notional = abs(qty) * price
    asset_class = _ibkr_asset_class(instrument)
    if asset_class in ("us_equity", "us_etf"):
        commission = abs(qty) * IBKR_US_PER_SHARE
        commission = max(commission, IBKR_US_MIN_ORDER)        # per-order minimum
        return min(commission, notional * IBKR_US_VALUE_CAP_PCT)  # capped at 1% of trade value
    if asset_class == "us_future":
        return abs(qty) * IBKR_US_FUTURE_PER_CONTRACT
    if asset_class == "eu_future":
        return abs(qty) * IBKR_EU_FUTURE_PER_CONTRACT
    if asset_class == "eu_equity":
        return max(notional * IBKR_EU_EQUITY_PCT, IBKR_EU_EQUITY_MIN)
    # Unknown IBKR asset class → the venue's flat 0.5 bps (the dispatcher normally returns None before reaching
    # here, so this is only a defensive floor).
    return notional * 0.5 / 10_000.0


def ibkr_taker_bps(instrument: Instrument, price: float, *, reference_notional: float = 10_000.0) -> Decimal:
    """IBKR commission as effective BPS of notional for a SINGLE leg, at a `reference_notional` order size.

    Per-share / per-contract / min / cap all make the bps SIZE-dependent (a tiny order hits the $0.35 min and pays
    a huge bps; a large order is dominated by the per-share rate). The backtest charges a per-symbol scalar bps, so
    we evaluate the real commission curve at one honest reference order notional (default $10k — a realistic small
    book leg) and convert to bps. A future's per-contract cost is divided by (multiplier × price) to reach bps.
    The French FTT is NOT included here (it is a buy-leg-only asymmetry — see ibkr_ftt_buy_leg_bps)."""
    asset_class = _ibkr_asset_class(instrument)
    if price <= 0:
        return Decimal("0")
    if asset_class in ("us_future", "eu_future"):
        # A future's notional per contract = contract_multiplier × price. The per-contract commission ÷ that
        # notional IS the bps — invariant to how many contracts the reference book buys, so no contract count is
        # needed (commission and notional both scale linearly with #contracts).
        per_contract_notional = float(instrument.contract_multiplier) * price
        if per_contract_notional <= 0:
            return Decimal("0")
        per_contract = IBKR_US_FUTURE_PER_CONTRACT if asset_class == "us_future" else IBKR_EU_FUTURE_PER_CONTRACT
        return Decimal(str(per_contract / per_contract_notional * 10_000.0))
    # Equity / ETF / EU equity: qty in SHARES = reference_notional / price; the min/cap make this size-dependent.
    qty = reference_notional / price
    commission = ibkr_commission_usd(instrument, qty, price)
    return Decimal(str(commission / reference_notional * 10_000.0))


def ibkr_ftt_buy_leg_bps(instrument: Instrument) -> Decimal:
    """The French FTT as buy-leg-only bps: 0.40% (40 bps) charged on the BUY leg ONLY of an FR-HQ large-cap
    (>€1bn) — a round-trip ASYMMETRY (buy pays it, sell does not), NOT folded into the symmetric commission. The
    instrument opts in via `instrument_type == 'eu_equity_fr_ftt'` (or category 'fr_ftt'); everything else → 0."""
    if _ibkr_asset_class(instrument) == "eu_equity" and _is_fr_ftt(instrument):
        return Decimal(str(FRENCH_FTT_RATE * 10_000.0))
    return Decimal("0")


def _ibkr_asset_class(instrument: Instrument) -> str:
    """Map an Instrument to its IBKR fee asset-class key. Prefers an explicit `instrument_type`, else infers from
    the catalog `asset_class` (US equity is the default IBKR research universe)."""
    itype = (instrument.instrument_type or "").strip().lower()
    if itype in ("us_equity", "us_etf", "us_future", "eu_future", "eu_equity"):
        return itype
    if itype in ("eu_equity_fr_ftt",):
        return "eu_equity"
    # Inference from the generic catalog class: IBKR's catalog equities are US names/ETFs.
    if instrument.asset_class == "equity":
        return "us_equity"
    return "unknown"


def _is_fr_ftt(instrument: Instrument) -> bool:
    """True when this EU-equity instrument is an FR-HQ large-cap subject to the French FTT (buy-leg tax)."""
    itype = (instrument.instrument_type or "").strip().lower()
    cat = (instrument.category or "").strip().lower()
    return itype == "eu_equity_fr_ftt" or cat == "fr_ftt"


# Venues whose REAL taker fee is NOT a flat venue-level bps — they have a per-asset / per-category model
# (Polymarket per-category P&L-room fee; IBKR per-asset-class per-share/per-contract commission). The ONE source
# of this set so the screen (master/screen_universe) and the order path (master/execution) can never disagree on
# which venues need the per-asset override. Plain spot/perp venues (Binance/Kraken/OKX/HL) are NOT in here and
# keep their flat base/tiered bps untouched.
ASSET_AWARE_VENUES: frozenset[str] = frozenset({"polymarket", "ibkr"})


def effective_taker_bps(
    venue: Venue,
    instrument: Instrument | None,
    *,
    reference_price: float = 1.0,
    as_of: datetime | None = None,
    reference_notional: float = 10_000.0,
) -> Decimal | None:
    """The ONE shared per-venue TAKER-fee resolver — the fee analogue of master/sizing.size_fraction.

    Returns the effective taker bps when the venue has a per-asset / per-category model that a flat catalog bps
    would MISPRICE (Polymarket per-category×(1−price); IBKR per-share/per-contract/min/cap), else **None** — the
    signal to the caller to keep the venue's own flat base/tiered bps (or its PIT-snapshot read). Both the
    backtest/screen cost path (`build_cost_context` → `_asset_aware_fee`) and the paper/live order path
    (`_pit_fee_for_order`) call THIS, so a Polymarket/IBKR cell pays the SAME asset-aware fee in paper that the
    backtest charged — and crypto spot/perp is byte-identical (this returns None, the catalog/PIT path is unchanged).

    INVARIANT — this can only EQUAL-or-RAISE a non-crypto paper fee vs the flat placeholder (Polymarket 0 bps →
    per-category; IBKR 0.5 bps → real per-share): it NEVER credits a maker rebate, NEVER lowers a crypto fee, and
    NEVER touches the Gate. `reference_price` is the order/screen price (Polymarket needs it for (1−price); IBKR for
    per-share↔notional); `instrument` None → None (no per-asset override possible)."""
    if venue.id not in ASSET_AWARE_VENUES:
        return None  # plain spot/perp venue → caller keeps its flat/PIT bps (crypto byte-identical)
    return asset_taker_bps(
        venue,
        instrument,
        reference_price=reference_price,
        as_of=as_of,
        reference_notional=reference_notional,
    )


# --- the dispatcher the cost context calls ----------------------------------------------------------------------

def asset_taker_bps(
    venue: Venue,
    instrument: Instrument | None,
    *,
    reference_price: float = 1.0,
    as_of: datetime | None = None,
    reference_notional: float = 10_000.0,
) -> Decimal | None:
    """The effective TAKER bps for (symbol,venue) when the venue's real fee is NOT a flat venue-level bps.

    Returns:
      - Polymarket  → per-category PIT taker bps (0 before the 2026-03-23 rollout; feeRate×(1−price)×1e4 after).
      - IBKR        → per-asset-class commission bps (per-share + min + cap, or per-contract×multiplier, or
                      value-percent), at `reference_notional`. The FR FTT buy-leg asymmetry is reported separately.
      - else        → None: the caller keeps the venue's base/tiered bps (Binance/Kraken/OKX/HL spot+perp unchanged).

    `reference_price` is the bar price the symbol is screened at (Polymarket needs it for (1−price); IBKR needs it
    for per-share↔notional and per-contract↔bps). `instrument` None → None (no per-asset override possible)."""
    if venue.id == "polymarket":
        category = instrument.category if instrument is not None else None
        return polymarket_taker_bps(category, reference_price, as_of=as_of)
    if venue.id == "ibkr" and instrument is not None:
        if _ibkr_asset_class(instrument) == "unknown":
            return None  # no per-asset model → keep the venue's flat bps fallback
        return ibkr_taker_bps(instrument, reference_price, reference_notional=reference_notional)
    return None
