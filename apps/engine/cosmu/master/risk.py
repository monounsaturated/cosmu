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
    # SANDBOX per-combo: True when THIS track's own equity has fallen to/below its kill floor — the wallet is
    # spent. The order path turns this into a reduce_only CLOSE of the track's open leg (and never opens a new
    # entry for it). A close that genuinely reduces is itself always accepted, so the kill flag never traps an
    # exit. Default False ⇒ no per-combo kill (every order today), so callers that ignore it are unaffected.
    kill_combo: bool = False


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
    # the SIM/paper lane.
    venue_open_notional: Decimal = Decimal("0")
    venue_max_notional: Decimal | None = None
    # Operator LIVE caps (the Rules modal's global "$ hard blocker" + per-strategy live cap). Gated exactly like
    # venue_max_notional: None → the check is skipped (the SIM/paper lane is never fed a live cap, so absent
    # config == today's behavior). Measured against LIVE-BOOK exposure only (testnet/live positions) — NEVER the
    # sim/paper notional — so a funded paper cohort can never false-trip the operator's live limits. The caller
    # sets these ONLY for live-armed orders.
    live_open_notional: Decimal = Decimal("0")             # gross notional already on live books (all strategies)
    global_live_max_notional: Decimal | None = None        # operator's global pool cap (the headline "$ blocker")
    strategy_live_open_notional: Decimal = Decimal("0")    # this strategy's gross notional on live books
    per_strategy_live_max_notional: Decimal | None = None  # operator's per-strategy live cap
    # --- SANDBOX per-combo wallet (operator decision Q1 = "sandbox + global backstop") ----------------
    # 1 track (= strategy_version × symbol × venue) is 1 wallet of its allocated `starting_capital` and can
    # NEVER lose more than that. These describe THIS order's OWN track (NOT the aggregate pool — the aggregate
    # equity/cash/drawdown/daily-loss checks remain the FINAL backstop, never removed). All three are evaluated
    # on the per-TRACK portfolio view (Portfolio.track_risk). Gated like the live caps: when the caller cannot
    # resolve a track wallet (no tracks row — bare-position tests/tools), it leaves `track_starting_capital`
    # None and the per-combo checks are SKIPPED (today's behaviour exactly), so the aggregate gauntlet still
    # governs. The caller sets them for every executor-managed paper/live track (which always has a wallet).
    track_starting_capital: Decimal | None = None  # the wallet size — the hard loss floor. None ⇒ checks skipped.
    track_equity: Decimal = Decimal("0")           # this track's own equity = starting_capital + realized + unrealized
    track_cash: Decimal = Decimal("0")             # this track's own deployable cash = starting_capital + realized − own open notional
    # The per-combo KILL floor as a FRACTION of the wallet: when this track's own equity falls to/below
    # starting_capital × this fraction, the track is killed (the executor emits a reduce_only close). 0.0 = kill
    # only at a fully-drained wallet; a small positive fraction kills slightly early so the wallet is never
    # actually breached by the next adverse mark. Per-combo, NOT the aggregate drawdown kill-switch (which stays).
    track_kill_floor_pct: Decimal = Decimal("0")


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
    checks, then the SANDBOX per-combo wallet bound (a track can never deploy past its own starting_capital —
    so its loss is bounded to its wallet), then the portfolio-aware AGGREGATE backstop: global cap, min cash
    reserve, drawdown kill-switch, daily-loss auto-disarm, and the martingale/averaging-down ban. Per Q1
    ("sandbox + global backstop") BOTH layers run — the per-combo bound is the sandbox, the aggregate checks
    are the final filet. Memoryless: position size is never a function of past losses — a prior loss can only
    BLOCK a trade (no averaging down), never enlarge the next one. The returned decision also carries
    `kill_combo` (True when this track's own equity hit its wallet floor) so the order path can liquidate it."""
    base = validate_order(order, venue, instrument, risk)
    issues = list(base.issues)

    # SANDBOX per-combo KILL signal: this track's own equity has reached its wallet floor. Computed for BOTH a
    # close and an entry so the order path can liquidate the spent wallet's open leg. It is a SIGNAL, never a
    # blocker of a close — a reduce_only exit stays accepted (closing the leg is exactly what the kill wants).
    kill_combo = (
        state.track_starting_capital is not None
        and state.track_equity <= state.track_starting_capital * state.track_kill_floor_pct
    )

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
        # kill-switch, the daily-loss disarm, OR the per-combo bound would trap losing positions open — the
        # opposite of safety. The per-combo kill flag is carried so the caller closes a spent wallet's leg.
        return RiskDecision(accepted=not issues, issues=issues, kill_combo=kill_combo)

    # SANDBOX per-combo HARD BOUND (operator decision Q1): a track is one wallet of its `starting_capital` and
    # can NEVER lose more than that. Evaluated on the PER-TRACK view (NOT the aggregate pool): a new BUY can
    # deploy no more than THIS track's own deployable cash (starting_capital + own realized P&L − own open
    # notional), so the most this combo can ever lose is bounded by its wallet. A spent/over-drawn wallet
    # (track_kill_floor reached) takes no new entry at all. Gated on a resolved wallet (track_starting_capital
    # set) — None ⇒ skipped (bare-position tests/tools fall back to the aggregate gauntlet, today's behaviour).
    # This is the SANDBOX; the aggregate global_cap / drawdown_killswitch / daily_loss below remain the FINAL
    # backstop (Q1 = "sandbox + filet global") and are NOT removed.
    if state.track_starting_capital is not None and order.side == "buy":
        if kill_combo:
            issues.append("combo_wallet_spent")
        elif order.notional > state.track_cash:
            issues.append("combo_capital_exceeded")
    if state.open_notional + order.notional > risk.global_max_notional:
        issues.append("global_cap")
    if state.strategy_open_notional + order.notional > risk.per_strategy_cap:
        issues.append("per_strategy_cap_exceeded")
    # Per-venue hard cap (Rules modal). Additive + gated on a configured cap: None → skipped (today's
    # behavior). Inside the non-reduce_only block, so a close is never trapped behind it. A deterministic
    # reject — the order can never push this venue's deployed notional past the operator's per-venue limit.
    if state.venue_max_notional is not None and state.venue_open_notional + order.notional > state.venue_max_notional:
        issues.append("venue_cap")
    # Operator LIVE caps (Rules modal): the global pool "$ hard blocker" + the per-strategy live cap, each
    # measured against LIVE-book exposure only. Additive + gated (None → skipped); inside the non-reduce_only
    # block so a close is never trapped. A reject can never push live exposure past the operator's limit.
    if state.global_live_max_notional is not None and state.live_open_notional + order.notional > state.global_live_max_notional:
        issues.append("global_live_cap")
    if state.per_strategy_live_max_notional is not None and state.strategy_live_open_notional + order.notional > state.per_strategy_live_max_notional:
        issues.append("per_strategy_live_cap")
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
    return RiskDecision(accepted=not issues, issues=issues, kill_combo=kill_combo)

