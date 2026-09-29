# intent: the PAPER executor's per-position EXIT-PLAN engine — make the forward run apply the SAME multi-leg exit
# physics the backtest (cosmu/data/backtest.py::_run_symbol) screened with: partial multi-TP scale-out legs,
# break-even-after-TP1, the post-TP1 runner trail, a standalone trailing stop, an ATR-multiple initial stop, and
# per-bar funding accrual on a held perp leg. The backtest is a single in-memory loop carrying mutable state
# across bars; the paper executor is STATELESS across ticks (it reconstructs from the DB each tick), so this
# module (a) persists that runner state in `position_exit_state` keyed like a position, and (b) steps it one
# CLOSED bar at a time with the EXACT worst-case priority the backtest uses (stop > take legs > single take >
# time/signal). invariants: long-only here (the paper executor already skips short specs); a leg fills exactly
# once; the stop only ever RAISES (never loosens); state is gated by the `position_exit_state` schema probe so a
# pre-migration prod table degrades to the legacy single stop/take/time/signal close — byte-identical to before.

from __future__ import annotations

import json
from dataclasses import dataclass, field

from cosmu.data.backtest import _atr, _lookback_for, _resolved_tp_legs
from cosmu.knowledge.store import Store, positions_has_exit_state, utcnow
from cosmu.strategy.spec import StrategySpec


@dataclass
class ExitState:
    """The mutable runner state of ONE open paper leg — the persisted mirror of the backtest's per-position
    locals (stop_price / tp1_filled / legs_filled / extreme_since_entry / funding_accrued). `entry_ts` ties the
    state to the CURRENT leg so a re-entry after a full close starts fresh and never inherits a prior leg's
    trail."""

    entry_ts: str | None = None
    entry_qty: float = 0.0
    stop_price: float | None = None
    tp1_filled: bool = False
    legs_filled: list[int] = field(default_factory=list)
    extreme: float | None = None
    funding_accrued: float = 0.0


@dataclass(frozen=True)
class PartialClose:
    """One reduce-only fill the exit plan wants this tick. `qty` is the BASE-unit size to close (a partial leg or
    the full remainder), `fill_price` the price it fills at, `reason` the exit reason (stop_loss / take_profit /
    time_stop / signal_exit), `leg_index` the multi-TP leg that fired (None for non-leg exits)."""

    qty: float
    fill_price: float
    reason: str
    leg_index: int | None = None


# Reason a plan-driven exit fully or partially closes the leg. Mirrors the backtest's _book ordering.
_STOP = "stop_loss"
_TAKE = "take_profit"
_TIME = "time_stop"
_SIGNAL = "signal_exit"


def has_exit_plan(spec: StrategySpec) -> bool:
    """True when the spec carries ANY of the layered exit tools this engine manages (multi-TP legs, break-even,
    a runner trail, a standalone trailing stop, or an ATR-multiple stop). False → the spec has only a plain
    stop/take/time/signal exit and the executor's legacy single-close path governs (byte-identical to before)."""
    plan = spec.exit.plan
    has_plan = plan is not None and bool(plan.multi_tp or plan.break_even_after_tp1 or plan.runner_trail is not None)
    return bool(has_plan or spec.exit.trailing_stop is not None or spec.exit.atr_mult is not None)


def manages_exit(store: Store, spec: StrategySpec) -> bool:
    """True when the executor should drive this leg through the multi-leg exit-plan engine: the spec uses a
    layered exit tool AND the `position_exit_state` table is live (so state can persist across ticks). When the
    table is absent (pre-migration prod) this is False and the legacy single-close path governs — no crash, no
    behaviour change for any existing track."""
    return has_exit_plan(spec) and positions_has_exit_state(store)


def load_state(store: Store, version_id: str, instrument_id: str, venue: str) -> ExitState | None:
    """The persisted exit state for an open leg, or None when none is on file (a leg opened before this engine,
    or the table is absent). Never raises — a missing table degrades to None (legacy path)."""
    if not positions_has_exit_state(store):
        return None
    row = store.row(
        "SELECT entry_ts, entry_qty, stop_price, tp1_filled, legs_filled, extreme, funding_accrued "
        "FROM position_exit_state WHERE strategy_version_id = ? AND instrument_id = ? AND venue = ?",
        (version_id, instrument_id, venue),
    )
    if row is None:
        return None
    try:
        legs = list(json.loads(row["legs_filled"])) if row.get("legs_filled") else []
    except (ValueError, TypeError):
        legs = []
    return ExitState(
        entry_ts=row.get("entry_ts"),
        entry_qty=float(row["entry_qty"]) if row.get("entry_qty") is not None else 0.0,
        stop_price=float(row["stop_price"]) if row.get("stop_price") is not None else None,
        tp1_filled=bool(row.get("tp1_filled")),
        legs_filled=[int(x) for x in legs],
        extreme=float(row["extreme"]) if row.get("extreme") is not None else None,
        funding_accrued=float(row["funding_accrued"]) if row.get("funding_accrued") is not None else 0.0,
    )


def save_state(store: Store, version_id: str, instrument_id: str, venue: str, state: ExitState) -> None:
    """Persist the open leg's runner state (idempotent upsert on the position key). No-op when the table is
    absent (the engine is never reached in that case, but this stays safe)."""
    if not positions_has_exit_state(store):
        return
    store.rows(
        """
        INSERT INTO position_exit_state(strategy_version_id, instrument_id, venue, entry_ts, entry_qty,
            stop_price, tp1_filled, legs_filled, extreme, funding_accrued, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (strategy_version_id, instrument_id, venue) DO UPDATE SET
            entry_ts = excluded.entry_ts, entry_qty = excluded.entry_qty, stop_price = excluded.stop_price,
            tp1_filled = excluded.tp1_filled, legs_filled = excluded.legs_filled, extreme = excluded.extreme,
            funding_accrued = excluded.funding_accrued, updated_at = excluded.updated_at
        """,
        (
            version_id, instrument_id, venue,
            state.entry_ts,
            str(state.entry_qty),
            None if state.stop_price is None else str(state.stop_price),
            int(state.tp1_filled),
            json.dumps(sorted(state.legs_filled)),
            None if state.extreme is None else str(state.extreme),
            str(state.funding_accrued),
            utcnow(),
        ),
    )


def clear_state(store: Store, version_id: str, instrument_id: str, venue: str) -> None:
    """Drop the leg's exit state — called when the position fully closes, so the next entry starts fresh."""
    if not positions_has_exit_state(store):
        return
    store.rows(
        "DELETE FROM position_exit_state WHERE strategy_version_id = ? AND instrument_id = ? AND venue = ?",
        (version_id, instrument_id, venue),
    )


def initial_stop_pct(spec: StrategySpec, params: dict[str, float], bars: list) -> float | None:  # noqa: ANN001
    """The initial stop DISTANCE (fraction of entry) for a NEW leg: `atr_mult × ATR` at the signal bar (the last
    CLOSED bar, the bar the entry decision reads) when the spec uses an ATR-multiple stop AND the ATR is
    available, else the fixed `stop_loss` fraction — mirroring the backtest's entry-stop choice. None only when
    the spec has no fixed stop param either (the leg is then unprotected by a fixed stop, exactly as the legacy
    `_bracket_fractions` would leave it)."""
    stop = params.get(spec.exit.stop_loss.param)
    fixed = float(stop) if stop is not None and float(stop) > 0 else None
    if spec.exit.atr_mult is None:
        return fixed
    mult = max(0.0, float(params[spec.exit.atr_mult.param]))
    highs = [float(b.high) for b in bars]
    lows = [float(b.low) for b in bars]
    closes = [float(b.close) for b in bars]
    atr = _atr(highs, lows, closes, _lookback_for("atr", spec, params))
    atr_at = atr[-1] if atr else None  # the last CLOSED bar = the entry signal bar
    if atr_at is not None and atr_at > 0:
        return mult * float(atr_at)
    return fixed  # warm-up / no ATR → the fixed stop fraction (never unprotected when a fixed stop exists)


def open_state(
    spec: StrategySpec, params: dict[str, float], *, entry_price: float, entry_qty: float, entry_ts: str, bars: list  # noqa: ANN001
) -> ExitState:
    """Build the fresh exit state for a leg that just opened — the paper mirror of the backtest's entry block
    (stop the adverse side of entry, extreme seeded at the entry bar's favourable extreme, no legs filled)."""
    stop_pct = initial_stop_pct(spec, params, bars)
    stop_price = entry_price * (1.0 - stop_pct) if stop_pct is not None else None  # long-only here
    return ExitState(
        entry_ts=entry_ts,
        entry_qty=entry_qty,
        stop_price=stop_price,
        tp1_filled=False,
        legs_filled=[],
        extreme=float(bars[-1].high),  # the entry bar's high (the favourable extreme at entry) — long-only
    )


def accrue_funding(state: ExitState, *, position_qty: float, rate: float | None, close: float) -> float:
    """One bar of funding cash-flow on the held LONG leg: a long pays funding when the rate is positive, so the
    flow is `-rate × qty × close` (negative = cost). Mirrors backtest's _accrue_funding for d=+1. Returns the
    flow and folds it into `state.funding_accrued`. rate None / no qty → 0 (spot leg is unchanged)."""
    if rate is None or position_qty <= 0:
        return 0.0
    flow = -float(rate) * position_qty * close
    state.funding_accrued += flow
    return flow


def step_exit_plan(
    spec: StrategySpec,
    params: dict[str, float],
    *,
    bar,  # noqa: ANN001 — the latest CLOSED Bar
    state: ExitState,
    position_qty: float,
    entry_price: float,
    time_stop_hit: bool,
    signal_exit_hit: bool,
) -> tuple[list[PartialClose], ExitState, float]:
    """Step ONE closed bar of the multi-leg exit plan for a held LONG leg, returning (the partial closes to fill
    this tick, the updated state, the qty STILL open after them). The worst-case priority MIRRORS the backtest's
    _run_symbol held-position block EXACTLY:

      0) update the favourable extreme (bar high) and the trailing stops (post-TP1 runner + standalone trailing,
         both RAISE-only),
      1) stop / trail first (low <= stop ⇒ close the FULL remaining qty),
      2) partial multi-TP legs in ascending take-distance order (close entry_qty × size_pct each; the first leg
         arms break-even when set),
      3) single take-profit ONLY when there is no multi-TP plan,
      4) time-stop / signal-exit closes whatever remains.

    Long-only (the paper executor skips short specs). Prices fill AT the level (stop_price / leg_price / tp_price)
    for the bracket legs and at the bar close for the time/signal exit — the same levels the backtest books, so
    paper and the screen agree on the exit sequence and P&L (slippage/fees are charged identically by the order
    path). The caller persists the returned state and clears it when the remaining qty reaches 0."""
    high = float(bar.high)
    low = float(bar.low)
    close = float(bar.close)
    qty = position_qty
    closes: list[PartialClose] = []

    # 0) favourable extreme + trailing stops (RAISE-only) — long-only.
    state.extreme = high if state.extreme is None else max(state.extreme, high)

    plan = spec.exit.plan
    runner_trail = (
        max(0.0, float(params[plan.runner_trail.param])) if plan is not None and plan.runner_trail is not None else None
    )
    if runner_trail is not None and state.tp1_filled and state.extreme is not None:
        trail = state.extreme * (1.0 - runner_trail)
        state.stop_price = trail if state.stop_price is None else max(state.stop_price, trail)

    ts_rule = spec.exit.trailing_stop
    if ts_rule is not None and state.extreme is not None:
        trail_dist = max(0.0, float(params[ts_rule.distance.param]))
        trail_arm = (
            max(0.0, float(params[ts_rule.arm_after_profit.param])) if ts_rule.arm_after_profit is not None else None
        )
        profit = (state.extreme - entry_price) / entry_price if entry_price else 0.0
        if trail_arm is None or profit >= trail_arm:
            trail = state.extreme * (1.0 - trail_dist)
            state.stop_price = trail if state.stop_price is None else max(state.stop_price, trail)

    legs = _resolved_tp_legs(spec, params)  # [] when no multi_tp plan
    break_even = bool(plan is not None and plan.break_even_after_tp1)

    # 1) stop / trail (worst-case first): a long stops when the bar low <= stop.
    if state.stop_price is not None and qty > 0 and low <= state.stop_price:
        closes.append(PartialClose(qty=qty, fill_price=state.stop_price, reason=_STOP))
        return closes, state, 0.0

    # 2) partial multi-TP legs in ascending take-distance order.
    if qty > 0 and legs:
        for li, (at, size_pct) in enumerate(legs):
            if li in state.legs_filled:
                continue
            leg_price = entry_price * (1.0 + at)
            if high >= leg_price:
                leg_qty = min(qty, state.entry_qty * size_pct)
                if leg_qty > 0:
                    closes.append(PartialClose(qty=leg_qty, fill_price=leg_price, reason=_TAKE, leg_index=li))
                    qty -= leg_qty
                    state.legs_filled.append(li)
                    if not state.tp1_filled:
                        state.tp1_filled = True
                        if break_even:
                            # Risk-free runner: raise the stop to entry (long: max in the favourable direction).
                            state.stop_price = entry_price if state.stop_price is None else max(state.stop_price, entry_price)

    # 3) single take-profit ONLY when there is no multi-TP plan.
    take = params.get(spec.exit.take_profit.param)
    take_pct = float(take) if take is not None and float(take) > 0 else None
    if qty > 0 and not legs and take_pct is not None:
        tp_price = entry_price * (1.0 + take_pct)
        if high >= tp_price:
            closes.append(PartialClose(qty=qty, fill_price=tp_price, reason=_TAKE))
            return closes, state, 0.0

    # 4) time-stop / signal-exit closes whatever remains, at the bar close.
    if qty > 0 and (time_stop_hit or signal_exit_hit):
        reason = _TIME if time_stop_hit else _SIGNAL
        closes.append(PartialClose(qty=qty, fill_price=close, reason=reason))
        return closes, state, 0.0

    return closes, state, qty
