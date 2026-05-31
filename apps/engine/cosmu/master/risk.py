# intent: enforce deterministic order safety for paper and live; inputs: order proposals and risk settings; outputs: validation decision; invariants: no martingale, no missing SL/TP, no stale data, no order bypasses the gauntlet.

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from cosmu.config.settings import RiskSettings
from cosmu.spine.venue import Instrument, Venue


class OrderIntent(BaseModel):
    symbol: str
    side: Literal["buy", "sell"]
    qty: Decimal
    price: Decimal
    stop_loss: Decimal | None
    take_profit: Decimal | None
    conviction: Decimal
    sizing_basis: Literal["equity_vol_conviction"]
    data_fresh: bool = True

    @property
    def notional(self) -> Decimal:
        return self.qty * self.price


class RiskDecision(BaseModel):
    accepted: bool
    issues: list[str]


def validate_order(order: OrderIntent, venue: Venue, instrument: Instrument, risk: RiskSettings) -> RiskDecision:
    issues: list[str] = []
    if not order.data_fresh:
        issues.append("stale_data")
    if order.stop_loss is None or order.take_profit is None:
        issues.append("missing_sl_tp")
    if order.sizing_basis != "equity_vol_conviction":
        issues.append("non_memoryless_sizing")
    if order.notional < instrument.min_notional or order.notional < venue.min_notional:
        issues.append("min_notional")
    if order.notional > risk.per_strategy_cap:
        issues.append("per_strategy_cap")
    if order.qty <= 0 or order.price <= 0:
        issues.append("invalid_qty_or_price")
    if order.side == "buy" and order.stop_loss is not None and order.stop_loss >= order.price:
        issues.append("invalid_stop_loss")
    if order.side == "buy" and order.take_profit is not None and order.take_profit <= order.price:
        issues.append("invalid_take_profit")
    return RiskDecision(accepted=not issues, issues=issues)

