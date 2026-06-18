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
from cosmu.spine.venue import VenueCatalog
from cosmu.strategy.spec import StrategySpec

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
    paired with another venue's depth. The CRYPTO-ONLY path — no equity and no HL symbol present in `market` —
    returns `(None, None, None, None)`: the backtest then uses its SCALAR fee_bps / slippage_bps / impact_bps for
    the spec's primary venue, byte-identical to the pre-cross-asset behaviour.
    """
    equity_syms = set(equity_symbols(spec)) & market.keys()
    hl_syms = set(hyperliquid_symbols(spec)) & market.keys()
    if not equity_syms and not hl_syms:
        # Crypto-only (the common path): no per-symbol map → the backtest's scalar fee/depth for the spec's
        # primary venue is applied to every symbol, exactly as before.
        return None, None, None, None

    # Baseline: every symbol priced at the spec's PRIMARY venue (fee + depth from one source), then the equity
    # and HL legs are overridden to their own venues below.
    primary = catalog.venue_for(spec.universe.venues)
    p_fee, p_slip, p_impact = primary.cost_inputs()
    fee_schedule: dict[str, Decimal] = {s: p_fee for s in market}
    depth_schedule: dict[str, tuple[Decimal, Decimal]] = {s: (p_slip, p_impact) for s in market}
    venue_id_by_symbol: dict[str, str] = {s: primary.id for s in market}

    def _apply(symbols: set[str], venue_id: str) -> None:
        fee, slip, impact = catalog.venue(venue_id).cost_inputs()  # fee + depth, ONE source
        for s in symbols:
            fee_schedule[s] = fee
            depth_schedule[s] = (slip, impact)
            venue_id_by_symbol[s] = venue_id

    if equity_syms:
        _apply(equity_syms, "ibkr")        # the equity LIVE venue — its real fee (≈0.5 bps) + depth (2/25)
    if hl_syms:
        _apply(hl_syms, "hyperliquid")     # HL perps — their real fee (4.5 bps) + depth (6/60)

    # Only the equity leg needs a non-default calendar; crypto + HL perps are 24/7 (365), the backtest default.
    asset_class_by_symbol = {s: "equity" for s in equity_syms} or None
    return fee_schedule, depth_schedule, asset_class_by_symbol, venue_id_by_symbol
