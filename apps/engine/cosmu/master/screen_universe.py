# intent: ONE source of truth for the per-symbol cost + calendar context a cross-asset SCREEN needs — which
# market symbols are equity / Hyperliquid-perp / crypto, and the per-venue fee + market-depth + annualization
# that follows from that. Both the Strategy Finder (lab/finder) and the autonomous FarmLoop (evolution/loop)
# build this map from HERE, so the two paths can never disagree on what an equity (or HL) leg costs — the
# divergence this module exists to kill. inputs: a StrategySpec + the screened market panel + the venue catalog;
# outputs: (fee_schedule, depth_schedule, asset_class_by_symbol, venue_id_by_symbol). invariants: a venue's fee
# AND depth come from ONE call (Venue.cost_inputs), so a symbol can never be priced at one venue's fee and
# another's depth; the CRYPTO-ONLY path returns all-None so the backtest falls back to its scalar fee/depth and
# stays byte-identical to the pre-cross-asset behaviour.

from __future__ import annotations

from decimal import Decimal

from cosmu.data.market import Bar, EquityOHLCVProvider, HyperliquidOHLCVProvider
from cosmu.spine.asset_fees import asset_taker_bps
from cosmu.spine.venue import Instrument, Venue, VenueCatalog
from cosmu.strategy.spec import StrategySpec

# Venues whose REAL taker fee is NOT a flat venue-level bps — they have a per-asset / per-category model
# (Polymarket per-category P&L-room fee; IBKR per-asset-class per-share/per-contract commission). The cost
# context resolves these per (symbol,venue) via spine/asset_fees.asset_taker_bps instead of the flat catalog bps.
ASSET_AWARE_VENUES = frozenset({"polymarket", "ibkr"})

# Cap equity symbols per screen. More symbols → more trials → stricter gate (correct), but also slower local
# runs. 50 gives breadth without dominating the trial budget on a correlated sector basket.
EQUITY_SCREEN_LIMIT = 50
# Cap Hyperliquid perp symbols per screen. HL perps are highly correlated with Binance perps (same underlying),
# so 30 liquid perps is already generous — matching the Binance PERP_UNIVERSE width.
HL_SCREEN_LIMIT = 30


def equity_symbols(spec: StrategySpec) -> list[str]:
    """Equity SCREEN symbols for a spec — the cache-backed EquityOHLCVProvider universe, capped at
    `EQUITY_SCREEN_LIMIT`. Empty when the spec's universe does not include the 'equity' asset class. This is the
    SINGLE detection source the finder's store-gated wrapper (lab/finder._equity_symbols) AND build_cost_context
    both read, so "what counts as an equity symbol" is defined exactly once."""
    if "equity" not in spec.universe.asset_classes:
        return []
    return EquityOHLCVProvider().available_symbols()[:EQUITY_SCREEN_LIMIT]


def hyperliquid_symbols(spec: StrategySpec) -> list[str]:
    """Hyperliquid perp SCREEN symbols for a spec — cache-only, capped at `HL_SCREEN_LIMIT`. Empty when the
    spec's universe does not declare the 'hyperliquid' venue. Same single-source contract as `equity_symbols`
    (shared by lab/finder._hyperliquid_symbols and build_cost_context)."""
    if "hyperliquid" not in spec.universe.venues:
        return []
    return HyperliquidOHLCVProvider().available_symbols()[:HL_SCREEN_LIMIT]


def _instrument_for(catalog: VenueCatalog, symbol: str, venue_id: str) -> Instrument | None:
    """The catalog Instrument for a (symbol, venue), or None — so the asset-fee resolver can read its
    asset_class / instrument_type / contract_multiplier / category. Never raises (a symbol absent from the
    catalog simply has no per-asset override and keeps the venue's flat bps)."""
    try:
        return catalog.instrument(symbol, venue_id)
    except KeyError:
        return None


def _reference_price(bars: list[Bar]) -> float:
    """The price a symbol's effective fee is evaluated at — its LAST validation-window close. Polymarket needs it
    for the (1−price) P&L-room term; IBKR needs it for per-share↔notional and per-contract↔bps. 1.0 when empty
    (a degenerate symbol the backtest skips anyway)."""
    return float(bars[-1].close) if bars else 1.0


def _asset_aware_fee(
    venue: Venue, catalog: VenueCatalog, symbol: str, bars: list[Bar], base_taker: Decimal
) -> Decimal:
    """The effective taker bps for (symbol, venue): the per-asset/per-category model when the venue has one
    (Polymarket / IBKR), else the venue's flat `base_taker`. PIT: Polymarket's per-category fee resolver charges 0
    before its 2026-03-23 rollout (as_of=None → now in the screen/paper path, which is post-rollout)."""
    if venue.id not in ASSET_AWARE_VENUES:
        return base_taker
    instrument = _instrument_for(catalog, symbol, venue.id)
    override = asset_taker_bps(venue, instrument, reference_price=_reference_price(bars))
    return override if override is not None else base_taker


def build_cost_context(
    spec: StrategySpec,
    market: dict[str, list[Bar]],
    catalog: VenueCatalog,
) -> tuple[
    dict[str, Decimal] | None,
    dict[str, tuple[Decimal, Decimal]] | None,
    dict[str, str] | None,
    dict[str, str] | None,
]:
    """The per-symbol cost + calendar context for screening `spec` over `market`.

    Returns `(fee_schedule, depth_schedule, asset_class_by_symbol, venue_id_by_symbol)`:
      - fee_schedule           : symbol -> taker bps (run_strategy_backtest's per-symbol fee axis)
      - depth_schedule         : symbol -> (slippage_bps, impact_bps), the per-venue MARKET DEPTH — a mirror of
                                 fee_schedule, so the depth a symbol is screened at is its OWN venue's, not the
                                 spec's primary venue applied uniformly (the leak this closes: today only the fee
                                 was per-venue, depth was a single scalar)
      - asset_class_by_symbol  : symbol -> "equity" for the equity leg, so its Sharpe annualizes on the ~252
                                 session calendar instead of crypto's 365 (None when there's no equity leg)
      - venue_id_by_symbol     : symbol -> the venue each cell was actually priced at (the fee axis stamped on
                                 backtest_symbols)

    A symbol's fee AND depth come from ONE `Venue.cost_inputs()` call, so a cell can never carry one venue's fee
    paired with another venue's depth. The CRYPTO-ONLY path — no equity / HL leg AND a plain (flat-fee) primary
    venue — returns `(None, None, None, None)`: the backtest then uses its SCALAR fee_bps / slippage_bps /
    impact_bps for the spec's primary venue, byte-identical to the pre-cross-asset behaviour.

    PER-ASSET FEE: when a symbol trades at an ASSET-AWARE venue (Polymarket / IBKR — see ASSET_AWARE_VENUES) the
    flat catalog taker bps is WRONG (Polymarket's fee is per-category × (1−price); IBKR's is per-share/per-contract
    with a min + cap). `_asset_aware_fee` resolves the effective taker bps per (symbol,venue) via
    spine/asset_fees, so an IBKR equity leg pays its real per-share commission and a Polymarket market pays its
    category fee — instead of IBKR's 0.5 bps or Polymarket's 0 bps placeholder. This is the per-asset seam.
    """
    equity_syms = set(equity_symbols(spec)) & market.keys()
    hl_syms = set(hyperliquid_symbols(spec)) & market.keys()
    primary = catalog.venue_for(spec.universe.venues)
    # The per-symbol map is needed when there's a cross-asset leg (equity/HL) OR the primary venue itself has a
    # per-asset fee model (Polymarket/IBKR) — only then does a flat scalar fee misprice the spec.
    if not equity_syms and not hl_syms and primary.id not in ASSET_AWARE_VENUES:
        # Crypto-only flat-fee path (the common case): no per-symbol map → the backtest's scalar fee/depth for the
        # spec's primary venue is applied to every symbol, exactly as before.
        return None, None, None, None

    # Baseline: every symbol priced at the spec's PRIMARY venue (depth from one source); the taker fee is the
    # per-asset-resolved bps (== the flat tiered bps for a plain venue), then equity/HL legs override to their own
    # venues below.
    p_taker, p_slip, p_impact = primary.cost_inputs()
    fee_schedule: dict[str, Decimal] = {
        s: _asset_aware_fee(primary, catalog, s, market[s], p_taker) for s in market
    }
    depth_schedule: dict[str, tuple[Decimal, Decimal]] = {s: (p_slip, p_impact) for s in market}
    venue_id_by_symbol: dict[str, str] = {s: primary.id for s in market}

    def _apply(symbols: set[str], venue_id: str) -> None:
        venue = catalog.venue(venue_id)
        base_taker, slip, impact = venue.cost_inputs()  # depth + flat fee, ONE source
        for s in symbols:
            # Per-asset taker (IBKR per-share commission for the equity leg), depth from the venue.
            fee_schedule[s] = _asset_aware_fee(venue, catalog, s, market[s], base_taker)
            depth_schedule[s] = (slip, impact)
            venue_id_by_symbol[s] = venue_id

    if equity_syms:
        _apply(equity_syms, "ibkr")        # the equity LIVE venue — its real per-share fee + depth (2/25)
    if hl_syms:
        _apply(hl_syms, "hyperliquid")     # HL perps — their real fee (4.5 bps) + depth (6/60)

    # Only the equity leg needs a non-default calendar; crypto + HL perps are 24/7 (365), the backtest default.
    asset_class_by_symbol = {s: "equity" for s in equity_syms} or None
    return fee_schedule, depth_schedule, asset_class_by_symbol, venue_id_by_symbol
