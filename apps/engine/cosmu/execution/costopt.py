# intent: execution-cost optimization — pick maker vs taker and the right fee tier so high-turnover crypto keeps
# its edge; inputs: gross edge, spread, fee schedule, urgency, maker fill probability; outputs: an OrderPlan in
# net-of-cost bps; invariants: a trade is only worth doing if expected NET edge > 0, and maker rebates/half-spread
# capture are credited honestly (a maker order that won't fill in time is worth less than its rebate).

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cosmu.spine.venue import Venue


@dataclass(frozen=True)
class FeeSchedule:
    """Per-venue fees in basis points. `maker_bps` may be negative (a rebate you EARN)."""

    maker_bps: float
    taker_bps: float

    @classmethod
    def from_venue(cls, venue: "Venue", volume_30d_usd: float = 0.0) -> "FeeSchedule":
        """The single bridge from a catalog Venue (real, volume-tiered fees) to the cost model — so a
        backtest/paper prices the SAME fees the live venue would charge, per the account's volume."""
        maker, taker = venue.effective_fee(volume_30d_usd)
        return cls(maker_bps=float(maker), taker_bps=float(taker))

    @classmethod
    def from_pit(
        cls,
        venue: "Venue",
        symbol: str,
        as_of: datetime,
        store: Any,  # AltDataStore | PgAltDataStore — the PIT store
        volume_30d_usd: float = 0.0,
    ) -> "FeeSchedule":
        """Point-in-time fee schedule: read the snapshot from the alt_data store that was in effect
        at `as_of`, falling back to the volume-tiered catalog if no snapshot is available.

        This is the seam that eliminates fee look-ahead in backtests and papers: every order
        prices costs against the fee the account WOULD HAVE PAID at that timestamp, not the current rate.
        """
        from cosmu.data.altdata import read_pit_fee

        maker_bps = read_pit_fee(store, venue.id, symbol, "venue_fees_maker", as_of)
        taker_bps = read_pit_fee(store, venue.id, symbol, "venue_fees_taker", as_of)

        if maker_bps is not None and taker_bps is not None:
            return cls(maker_bps=float(maker_bps), taker_bps=float(taker_bps))

        # Fallback: volume-tiered catalog (the pre-P0.4 behaviour — still better than a raw magic number)
        maker_cat, taker_cat = venue.effective_fee(volume_30d_usd)
        return cls(
            maker_bps=float(maker_bps if maker_bps is not None else maker_cat),
            taker_bps=float(taker_bps if taker_bps is not None else taker_cat),
        )


@dataclass(frozen=True)
class FeeTier:
    min_volume_30d_usd: float
    schedule: FeeSchedule


def fee_for_volume(volume_30d_usd: float, tiers: list[FeeTier]) -> FeeSchedule:
    """The fee schedule for a 30-day volume — the highest tier whose threshold is met. Fee-tier routing is a
    real profit lever: more volume → cheaper fills → more strategies clear net-of-cost."""
    eligible = [t for t in tiers if volume_30d_usd >= t.min_volume_30d_usd]
    if not eligible:
        # below the lowest threshold → use the lowest tier's schedule
        return min(tiers, key=lambda t: t.min_volume_30d_usd).schedule
    return max(eligible, key=lambda t: t.min_volume_30d_usd).schedule


@dataclass(frozen=True)
class OrderPlan:
    order_type: str          # "maker" (post-only) | "market" (taker)
    expected_net_bps: float  # expected edge after fees + slippage
    reason: str


def taker_net_bps(gross_edge_bps: float, fee: FeeSchedule, spread_bps: float, extra_slippage_bps: float = 0.0) -> float:
    """Crossing the book: pay the taker fee + half the spread + any impact slippage."""
    return gross_edge_bps - fee.taker_bps - 0.5 * spread_bps - extra_slippage_bps


def maker_expected_net_bps(
    gross_edge_bps: float, fee: FeeSchedule, spread_bps: float, *, fill_prob: float, urgency: float
) -> float:
    """Posting passively: if filled you avoid crossing the spread and pay maker fee (or earn a rebate, negative
    bps); if not filled you forgo the edge in proportion to urgency. Expected value blends the two."""
    fill_prob = min(max(fill_prob, 0.0), 1.0)
    urgency = min(max(urgency, 0.0), 1.0)
    filled_value = gross_edge_bps - fee.maker_bps + 0.5 * spread_bps  # capture half-spread, pay maker (or +rebate)
    miss_cost = urgency * gross_edge_bps                              # urgent misses forfeit the edge
    return fill_prob * filled_value - (1.0 - fill_prob) * miss_cost


def choose_order(
    gross_edge_bps: float,
    fee: FeeSchedule,
    spread_bps: float,
    *,
    urgency: float = 0.5,
    maker_fill_prob: float = 0.6,
    extra_slippage_bps: float = 0.0,
) -> OrderPlan:
    """Pick the order type that maximizes expected net-of-cost edge. Prefers passive (maker) fills — which
    capture spread and rebates — unless urgency/low fill-probability makes crossing worth it."""
    taker = taker_net_bps(gross_edge_bps, fee, spread_bps, extra_slippage_bps)
    maker = maker_expected_net_bps(gross_edge_bps, fee, spread_bps, fill_prob=maker_fill_prob, urgency=urgency)
    if maker >= taker:
        return OrderPlan("maker", maker, "passive fill: captures spread/rebate, beats crossing")
    return OrderPlan("market", taker, "cross the book: urgency/low fill-prob outweighs maker savings")
