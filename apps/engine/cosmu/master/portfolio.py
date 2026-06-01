# intent: the paper/live portfolio of record — hold positions, mark-to-market on latest bars, persist
# portfolio_snapshots, compute net-of-cost P&L + drawdown, and run the daily-loss tracker that trips the
# kill-switch / auto-disarm; inputs: applied fills + latest marks; outputs: real portfolio state (no fabricated
# numbers) feeding GET /portfolio and GET /live/positions; invariants: avg_price is a memoryless basis (never a
# function of past losses), realized P&L is net of fees, and a snapshot is written on every change for audit.

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from cosmu.knowledge.store import Store, utcnow

_PAPER_BANKROLL = Decimal("100000")


@dataclass(frozen=True)
class PositionView:
    instrument_id: str
    symbol: str
    qty: Decimal
    avg_price: Decimal
    venue: str
    strategy_version_id: str | None
    realized_pnl: Decimal
    last_was_loss: bool

    def unrealized_pnl(self, mark: Decimal) -> Decimal:
        return (mark - self.avg_price) * self.qty


@dataclass(frozen=True)
class DailyLossStatus:
    daily_loss: Decimal
    cap: Decimal
    tripped: bool


class PaperPortfolio:
    """The portfolio of record for paper, testnet, and live fills alike — the venue differs, the bookkeeping
    does not. Positions live in the `positions` table; equity/drawdown/daily-loss are derived from snapshots so
    GET /portfolio reflects truth. `daily_loss_cap` is the auto-disarm threshold the order path checks."""

    def __init__(self, store: Store, *, bankroll: Decimal = _PAPER_BANKROLL, daily_loss_cap: Decimal = Decimal("250")) -> None:
        self.store = store
        self.bankroll = bankroll
        self.daily_loss_cap = daily_loss_cap

    # --- positions ---------------------------------------------------------------------------------

    def position(self, instrument_id: str, venue: str, *, strategy_version_id: str | None = None) -> PositionView | None:
        row = self.store.row(
            "SELECT * FROM positions WHERE instrument_id = ? AND venue = ? AND ((? IS NULL AND strategy_version_id IS NULL) OR strategy_version_id = ?)",
            (instrument_id, venue, strategy_version_id, strategy_version_id),
        )
        return self._to_view(row) if row else None

    def positions(self) -> list[PositionView]:
        rows = self.store.rows("SELECT * FROM positions WHERE CAST(qty AS REAL) != 0 ORDER BY updated_at DESC")
        return [self._to_view(r) for r in rows]

    def apply_fill(
        self,
        *,
        instrument_id: str,
        symbol: str,
        venue: str,
        side: int,
        qty: Decimal,
        price: Decimal,
        fee: Decimal,
        strategy_version_id: str | None = None,
    ) -> PositionView:
        """Fold one fill into the position with a memoryless average-cost basis. A reducing/closing fill books
        realized P&L net of fee and records whether THAT close was a loss (the averaging-down guard reads it —
        never to size the next bet). Returns the updated view."""
        existing = self.position(instrument_id, venue, strategy_version_id=strategy_version_id)
        signed = qty if side > 0 else -qty
        prev_qty = existing.qty if existing else Decimal("0")
        prev_avg = existing.avg_price if existing else Decimal("0")
        prev_realized = existing.realized_pnl if existing else Decimal("0")
        new_qty = prev_qty + signed
        realized = prev_realized
        last_was_loss = existing.last_was_loss if existing else False

        if prev_qty == 0 or (prev_qty > 0) == (signed > 0):
            # opening or adding in the same direction -> weighted-average the basis
            total_cost = prev_avg * abs(prev_qty) + price * qty
            new_avg = (total_cost / abs(new_qty)) if new_qty != 0 else Decimal("0")
        else:
            # reducing/closing -> realize P&L on the closed quantity, basis unchanged for the remainder
            closed = min(abs(signed), abs(prev_qty))
            direction = Decimal("1") if prev_qty > 0 else Decimal("-1")
            pnl = (price - prev_avg) * closed * direction - fee
            realized = prev_realized + pnl
            last_was_loss = pnl < 0
            new_avg = prev_avg if new_qty != 0 and (new_qty > 0) == (prev_qty > 0) else (price if new_qty != 0 else Decimal("0"))

        self.store.rows(
            """
            INSERT INTO positions(id, strategy_version_id, instrument_id, symbol, venue, qty, avg_price, realized_pnl, last_was_loss, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET qty = excluded.qty, avg_price = excluded.avg_price,
              realized_pnl = excluded.realized_pnl, last_was_loss = excluded.last_was_loss, updated_at = excluded.updated_at
            """,
            (
                self._pid(instrument_id, venue, strategy_version_id),
                strategy_version_id,
                instrument_id,
                symbol,
                venue,
                str(new_qty),
                str(new_avg.quantize(Decimal("0.00000001"))),
                str(realized.quantize(Decimal("0.00000001"))),
                int(last_was_loss),
                utcnow(),
            ),
        )
        return PositionView(instrument_id, symbol, new_qty, new_avg, venue, strategy_version_id, realized, last_was_loss)

    # --- marks / snapshots -------------------------------------------------------------------------

    def mark_to_market(self, marks: dict[str, Decimal]) -> dict[str, Decimal]:
        """Recompute equity from cash + Σ(qty·mark), write a portfolio_snapshot, and return the derived metrics.
        Cash is bankroll minus net deployed cost basis + realized P&L — no fabricated numbers."""
        positions = self.positions()
        realized = sum((p.realized_pnl for p in positions), Decimal("0"))
        deployed = sum((p.avg_price * p.qty for p in positions), Decimal("0"))
        positions_value = sum((marks.get(p.instrument_id, p.avg_price) * p.qty for p in positions), Decimal("0"))
        cash = self.bankroll + realized - deployed
        equity = cash + positions_value
        high_water = self._high_water(equity)
        drawdown = Decimal("0") if high_water == 0 else (high_water - equity) / high_water
        pnl = equity - self.bankroll
        now = utcnow()
        self.store.insert(
            "portfolio_snapshots",
            {
                "scope": "pool",
                "ref_id": "global",
                "ts": now,
                "equity": str(equity.quantize(Decimal("0.01"))),
                "cash": str(cash.quantize(Decimal("0.01"))),
                "positions_value": str(positions_value.quantize(Decimal("0.01"))),
                "pnl": str(pnl.quantize(Decimal("0.01"))),
                "drawdown": str(max(drawdown, Decimal("0")).quantize(Decimal("0.0001"))),
            },
        )
        # Also accrue a per-SLEEVE marked-value trajectory (existing scope/ref_id columns, no schema change) so
        # master/drift has a real per-sleeve realized series to estimate edge half-life + live drift from. A
        # sleeve's value = its marked positions + its realized P&L; the series across marks IS its edge trajectory.
        by_sleeve: dict[str, Decimal] = {}
        for p in positions:
            if p.strategy_version_id is None:
                continue
            value = marks.get(p.instrument_id, p.avg_price) * p.qty + p.realized_pnl
            by_sleeve[p.strategy_version_id] = by_sleeve.get(p.strategy_version_id, Decimal("0")) + value
        for vid, value in by_sleeve.items():
            self.store.insert(
                "portfolio_snapshots",
                {
                    "scope": "sleeve",
                    "ref_id": vid,
                    "ts": now,
                    "equity": str(value.quantize(Decimal("0.01"))),
                    "cash": "0.00",
                    "positions_value": str(value.quantize(Decimal("0.01"))),
                    "pnl": "0.00",
                    "drawdown": "0.0000",
                },
            )
        return {"equity": equity, "cash": cash, "pnl": pnl, "drawdown": max(drawdown, Decimal("0")), "positions_value": positions_value}

    def equity(self) -> Decimal:
        row = self.store.row("SELECT equity FROM portfolio_snapshots WHERE scope = 'pool' ORDER BY ts DESC LIMIT 1")
        return Decimal(str(row["equity"])) if row else self.bankroll

    def drawdown(self) -> Decimal:
        row = self.store.row("SELECT drawdown FROM portfolio_snapshots WHERE scope = 'pool' ORDER BY ts DESC LIMIT 1")
        return Decimal(str(row["drawdown"])) if row else Decimal("0")

    def daily_loss(self) -> DailyLossStatus:
        """Loss since the start of the UTC day, as a positive number. Equity now vs. the first snapshot today
        (or bankroll if none) — the auto-disarm trips when this meets the cap."""
        day = datetime.now(tz=UTC).date().isoformat()
        start = self.store.row(
            "SELECT equity FROM portfolio_snapshots WHERE scope = 'pool' AND ts >= ? ORDER BY ts ASC LIMIT 1",
            (f"{day}T00:00:00+00:00",),
        )
        start_equity = Decimal(str(start["equity"])) if start else self.bankroll
        loss = max(start_equity - self.equity(), Decimal("0"))
        return DailyLossStatus(daily_loss=loss, cap=self.daily_loss_cap, tripped=loss >= self.daily_loss_cap)

    # --- internals ---------------------------------------------------------------------------------

    def _high_water(self, current: Decimal) -> Decimal:
        row = self.store.row("SELECT MAX(CAST(equity AS REAL)) AS hw FROM portfolio_snapshots WHERE scope = 'pool'")
        prior = Decimal(str(row["hw"])) if row and row["hw"] is not None else self.bankroll
        return max(prior, current)

    @staticmethod
    def _pid(instrument_id: str, venue: str, strategy_version_id: str | None) -> str:
        return f"{strategy_version_id or 'pool'}:{venue}:{instrument_id}"

    @staticmethod
    def _to_view(row: dict) -> PositionView:
        return PositionView(
            instrument_id=row["instrument_id"],
            symbol=row["symbol"],
            qty=Decimal(str(row["qty"])),
            avg_price=Decimal(str(row["avg_price"])),
            venue=row["venue"],
            strategy_version_id=row.get("strategy_version_id"),
            realized_pnl=Decimal(str(row["realized_pnl"])),
            last_was_loss=bool(row["last_was_loss"]),
        )
