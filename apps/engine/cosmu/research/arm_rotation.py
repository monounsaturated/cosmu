# intent: ONE rotation-close for every deploy-lane arm. A documented rotation strategy (GEM, GTAA, VAA, PAA,
# DAA, sector/TSMOM, risk-parity …) re-arms into its CURRENT target holdings — but every arm used to only check
# "is the target already held?", so on rotation (SPY→AGG, sleeve drops below SMA, canary flips) the OLD leg was
# left open and the NEW leg opened on top: double capital deployed, the paper P&L polluted by a position
# the strategy had already rotated out of. This module closes the stale legs FIRST, at the latest REAL close,
# charging the same per-side fee the arm pays on entries — the faithful rotation sell. inputs: the portfolio +
# the keep-set of target symbols + the arm's own price fetch + per-side fee; outputs: booked closing fills (real
# realized P&L) + one audited event per close. invariants: SIM only; a leg whose close can't be fetched (offline)
# is LEFT OPEN this run and reported as deferred (honest deferral, never a fabricated exit price); idempotent
# (no stale legs → no-op); deterministic for a fixed store + closes.

from __future__ import annotations

from decimal import Decimal
from typing import Callable

from cosmu.knowledge.store import Store
from cosmu.master.portfolio import Portfolio


def close_stale_legs(
    store: Store,
    portfolio: Portfolio,
    *,
    version_id: str,
    keep_symbols: set[str],
    price_fn: Callable[[str], Decimal],
    fee_per_side_bps: float | Decimal,
) -> dict:
    """Close every held leg of `version_id` whose symbol is NOT in `keep_symbols` — the rotation sell that must
    precede opening the new target legs. Each close books at the latest REAL close from `price_fn`, net of the
    arm's own per-side fee (the same accounting its entries use), so realized P&L is genuine. Returns
    {"closed": [{symbol, qty, price}], "deferred": [symbol]} — deferred legs had no fetchable close (offline)
    and stay open until the next re-arm rather than exiting at a fabricated price."""
    closed: list[dict] = []
    deferred: list[str] = []
    fee_fraction = Decimal(str(fee_per_side_bps)) / Decimal("10000")
    for p in portfolio.positions():
        if p.strategy_version_id != version_id or p.qty == 0 or p.symbol in keep_symbols:
            continue
        price = price_fn(p.symbol)
        if price <= 0:
            deferred.append(p.symbol)
            continue
        fee = (abs(p.qty) * price * fee_fraction).quantize(Decimal("0.00000001"))
        portfolio.apply_fill(
            instrument_id=p.instrument_id,
            symbol=p.symbol,
            venue=p.venue,
            side=-1,
            qty=p.qty,
            price=price,
            fee=fee,
            strategy_version_id=version_id,
            record_execution=True,  # a rotation SELL is a real paper trade — advance the blotter/trade-count
        )
        closed.append({"symbol": p.symbol, "qty": str(p.qty), "price": str(price)})
        store.append_event(
            actor="research",
            kind="rotation_closed",
            ref_type="strategy_version",
            ref_id=version_id,
            payload={"symbol": p.symbol, "qty": str(p.qty), "price": str(price), "fee": str(fee)},
        )
    return {"closed": closed, "deferred": deferred}
