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
    # A reduce-only order CLOSES (part of) an existing position and can never open or grow exposure — the
    # paper executor's exit leg. The gauntlet verifies it genuinely reduces (see validate_order_full)
    # and then EXEMPTS it from the entry-shaped checks (brackets, caps, kill-switch): risk checks exist to stop
    # ADDING risk, and an order that strictly reduces exposure must never be trapped behind them (a tripped
    # kill-switch that also blocked closes would lock in the very losses it exists to stop).
    reduce_only: bool = False

    @property
    def notional(self) -> Decimal:
        return self.qty * self.price


class RiskDecision(BaseModel):
    accepted: bool
    issues: list[str]


class PortfolioRiskState(BaseModel):
    """The live portfolio context the gauntlet needs for the caps/reserve/kill-switch/martingale checks.
    Memoryless sizing is enforced structurally: size is f(equity, vol, conviction), so the ONLY past-loss
    field here, `last_trade_was_loss`, is used solely to BAN averaging-down — never to grow the next bet."""

    equity: Decimal = Decimal("100000")  # current pool equity (mark-to-market)
    cash: Decimal = Decimal("100000")  # free cash available to deploy
    open_notional: Decimal = Decimal("0")  # global gross notional already deployed (all strategies)
    strategy_open_notional: Decimal = Decimal("0")  # this strategy's gross notional already deployed
    drawdown_pct: Decimal = Decimal("0")  # current pool drawdown from high-water
    daily_loss: Decimal = Decimal("0")  # realized + unrealized loss so far today (positive number)
    daily_loss_cap: Decimal = Decimal("250")
    last_trade_was_loss: bool = False  # the prior trade on THIS instrument closed at a loss
    avg_entry_price: Decimal | None = None  # existing position avg price (averaging-down detector)
    existing_qty: Decimal = Decimal("0")  # existing position qty on this instrument (signed by entry side)
    # Per-venue hard cap (the Rules modal's "max $ per venue"). `venue_open_notional` is the gross notional
    # already deployed on THIS order's venue; `venue_max_notional` is the configured cap, or None when no
    # per-venue cap applies (e.g. the order is not live-armed) — None means the check is skipped entirely, so
    # absent config == today's behavior exactly. The caller only sets the cap for live-armed orders, never for
    # the SIM/forward-test lane.
    venue_open_notional: Decimal = Decimal("0")
    venue_max_notional: Decimal | None = None


def validate_order(order: OrderIntent, venue: Venue, instrument: Instrument, risk: RiskSettings) -> RiskDecision:
    issues: list[str] = []
    if not order.data_fresh:
        issues.append("stale_data")
    if (order.stop_loss is None or order.take_profit is None) and not order.reduce_only:
        issues.append("missing_sl_tp")  # a close carries no brackets — it IS the bracket firing
    if order.sizing_basis != "equity_vol_conviction":
        issues.append("non_memoryless_sizing")
    if order.notional < instrument.min_notional or order.notional < venue.min_notional:
        issues.append("min_notional")
    if order.qty < venue.lot_size or order.qty < instrument.lot_size:
        issues.append("lot_size")
    if order.notional > risk.per_strategy_cap:
        issues.append("per_strategy_cap")
    if order.qty <= 0 or order.price <= 0:
        issues.append("invalid_qty_or_price")
    if order.side == "buy" and order.stop_loss is not None and order.stop_loss >= order.price:
        issues.append("invalid_stop_loss")
    if order.side == "buy" and order.take_profit is not None and order.take_profit <= order.price:
        issues.append("invalid_take_profit")
    return RiskDecision(accepted=not issues, issues=issues)


def validate_order_full(
    order: OrderIntent,
    venue: Venue,
    instrument: Instrument,
    risk: RiskSettings,
    state: PortfolioRiskState,
) -> RiskDecision:
    """The full gauntlet every order (paper OR live) must clear before any fill. Runs the base deterministic
    checks, then the portfolio-aware ones: global cap, min cash reserve, drawdown kill-switch, daily-loss
    auto-disarm, and the martingale/averaging-down ban. Memoryless: position size is never a function of past
    losses — a prior loss can only BLOCK a trade (no averaging down), never enlarge the next one."""
    base = validate_order(order, venue, instrument, risk)
    issues = list(base.issues)

    if order.reduce_only:
        # A reduce-only order must GENUINELY reduce: an opposite-side fill against an existing position, no
        # larger than what is held. Verified structurally so the exemptions below can never open exposure.
        held = state.existing_qty
        reduces = (
            (order.side == "sell" and held > 0 and order.qty <= held)
            or (order.side == "buy" and held < 0 and order.qty <= -held)
        )
        if not reduces:
            issues.append("reduce_only_not_reducing")
        # Exposure-adding checks are SKIPPED for a genuine close: blocking an exit behind caps, the
        # kill-switch, or the daily-loss disarm would trap losing positions open — the opposite of safety.
        return RiskDecision(accepted=not issues, issues=issues)

    if state.open_notional + order.notional > risk.global_max_notional:
        issues.append("global_cap")
    if state.strategy_open_notional + order.notional > risk.per_strategy_cap:
        issues.append("per_strategy_cap_exceeded")
    # Per-venue hard cap (Rules modal). Additive + gated on a configured cap: None → skipped (today's
    # behavior). Inside the non-reduce_only block, so a close is never trapped behind it. A deterministic
    # reject — the order can never push this venue's deployed notional past the operator's per-venue limit.
    if state.venue_max_notional is not None and state.venue_open_notional + order.notional > state.venue_max_notional:
        issues.append("venue_cap")
    if order.side == "buy" and (state.cash - order.notional) < risk.min_cash_reserve:
        issues.append("min_cash_reserve")
    if state.drawdown_pct >= risk.drawdown_killswitch_pct:
        issues.append("drawdown_killswitch")
    if state.daily_loss >= state.daily_loss_cap:
        issues.append("daily_loss_auto_disarm")
    # Martingale / averaging-down ban: never add to a losing position, and never buy below your average
    # entry to "improve" the basis. Both are the classic ruin patterns; either is an outright reject.
    if order.side == "buy" and state.existing_qty > 0:
        if state.last_trade_was_loss:
            issues.append("martingale_after_loss")
        if state.avg_entry_price is not None and order.price < state.avg_entry_price:
            issues.append("averaging_down")
    return RiskDecision(accepted=not issues, issues=issues)

