# intent: the sim/live portfolio of record — hold positions, mark-to-market on latest bars, persist
# portfolio_snapshots, compute net-of-cost P&L + drawdown, and run the daily-loss tracker that trips the
# kill-switch / auto-disarm; inputs: applied fills + latest marks; outputs: real portfolio state (no fabricated
# numbers) feeding GET /overview (aggregate read-out) and GET /live/positions; invariants: avg_price is a
# memoryless basis (never a function of past losses), realized P&L is net of fees, and a snapshot is written on
# every change for audit. The aggregate scope is a pure READ-OUT (Σ of standalone tracks), never a pooled wallet.

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from cosmu.knowledge.store import Store, tracks_has_cell_columns, utcnow

_SIM_BANKROLL = Decimal("100000")


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


@dataclass(frozen=True)
class TrackRiskView:
    """The SANDBOX per-combo wallet view for ONE track (= strategy_version × symbol × venue). The track is one
    wallet of `starting_capital` that can never lose more than that. `equity` = starting_capital + realized (ALL
    its rows) + unrealized (open legs, marked). `cash` = the deployable headroom = starting_capital + realized −
    own open notional (cost basis of its open legs). `open_positions` = how many distinct open legs it holds
    (feeds size_fraction's concurrency divisor). When the track has no wallet (no starting_capital — bare
    positions in tests/tools), `starting_capital` is None and the per-combo gauntlet checks fall back to the
    aggregate (today's behaviour)."""

    starting_capital: Decimal | None
    equity: Decimal
    cash: Decimal
    open_positions: int


class Portfolio:
    """The portfolio of record for sim, testnet, and live fills alike — the venue differs, the bookkeeping
    does not. Positions live in the `positions` table; equity/drawdown/daily-loss are derived from snapshots so
    GET /overview reflects truth. `daily_loss_cap` is the auto-disarm threshold the order path checks."""

    def __init__(self, store: Store, *, bankroll: Decimal = _SIM_BANKROLL, daily_loss_cap: Decimal = Decimal("250")) -> None:
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

    def register_track(self, *, instrument_id: str, symbol: str, venue: str, strategy_version_id: str) -> None:
        """Register a FLAT track: a zero-qty position row that makes the version visible to the paper
        executor (its flat-row query) WITHOUT opening a trade. The funder calls this instead of buying at the
        mark — the track's FIRST entry is then its own spec's signal, so the forward record measures the
        strategy from bar one, never buy-and-hold-from-funding-day. Idempotent: an existing row (any qty)
        is left untouched, so registering can never reset a live basis or P&L."""
        self.store.rows(
            """
            INSERT INTO positions(id, strategy_version_id, instrument_id, symbol, venue, qty, avg_price, realized_pnl, last_was_loss, updated_at)
            VALUES (?, ?, ?, ?, ?, '0', '0', '0', 0, ?)
            ON CONFLICT (id) DO NOTHING
            """,
            (
                self._pid(instrument_id, venue, strategy_version_id),
                strategy_version_id,
                instrument_id,
                symbol,
                venue,
                utcnow(),
            ),
        )

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
        record_execution: bool = False,
        is_paper: bool = True,
    ) -> PositionView:
        """Fold one fill into the position with a memoryless average-cost basis. A reducing/closing fill books
        realized P&L net of fee and records whether THAT close was a loss (the averaging-down guard reads it —
        never to size the next bet). Returns the updated view.

        `record_execution=True` ALSO appends one row to the `executions` ledger (the fill blotter + trade-count
        the front reads), idempotently — the deploy-lane TAA arms pass it so a real monthly rebalance fill ADVANCES
        the trade-count, instead of writing only `positions` and leaving the blotter frozen at the 06-14 backfill.
        DEFAULT False so the backtest/replay path (which calls apply_fill thousands of times per sweep) NEVER
        pollutes the live ledger — the money path (positions/realized P&L/marks) is byte-identical to before either
        way. Idempotent via a CONTENT-HASHED id (version+instrument+venue+side+qty+price+UTC-day): re-running the
        same 4-hourly tick re-touches the SAME row → `ON CONFLICT (id) DO NOTHING` no-op (no double-count, no
        retroactive backfill of prior rotations), while a genuine rebalance (new qty/price/day) writes a new row."""
        existing = self.position(instrument_id, venue, strategy_version_id=strategy_version_id)
        signed = qty if side > 0 else -qty
        prev_qty = existing.qty if existing else Decimal("0")
        prev_avg = existing.avg_price if existing else Decimal("0")
        prev_realized = existing.realized_pnl if existing else Decimal("0")
        new_qty = prev_qty + signed
        realized = prev_realized
        last_was_loss = existing.last_was_loss if existing else False

        if prev_qty == 0 or (prev_qty > 0) == (signed > 0):
            # opening or adding in the same direction -> weighted-average the basis (pure price), and the
            # entry-leg fee books to realized NOW (mark-to-market expense). It used to be silently dropped —
            # only the closing leg's fee was ever charged, flattering every round trip by ~one taker fee,
            # and that flattery fed tracks.return_pct → live_ready.
            total_cost = prev_avg * abs(prev_qty) + price * qty
            new_avg = (total_cost / abs(new_qty)) if new_qty != 0 else Decimal("0")
            realized = prev_realized - fee
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
        if record_execution:
            self._record_execution(
                instrument_id=instrument_id, venue=venue, side=side, qty=qty, price=price, fee=fee,
                strategy_version_id=strategy_version_id, is_paper=is_paper,
            )
        return PositionView(instrument_id, symbol, new_qty, new_avg, venue, strategy_version_id, realized, last_was_loss)

    def _record_execution(
        self,
        *,
        instrument_id: str,
        venue: str,
        side: int,
        qty: Decimal,
        price: Decimal,
        fee: Decimal,
        strategy_version_id: str | None,
        is_paper: bool,
    ) -> None:
        """Append ONE idempotent row to the `executions` ledger for a fill (the trade-count + blotter source). Keyed
        by a content hash (version, instrument, venue, side, abs(qty), price, UTC-day) so re-running the same tick is
        a `DO NOTHING` no-op — the trade-count advances on a REAL rebalance (distinct qty/price/day) but never
        double-counts a re-mark. Best-effort + isolated: a ledger write must NEVER crash the money path (positions
        were already booked above), so any failure is swallowed — the worst case is a momentarily-stale blotter, not
        a lost or distorted position. Reuses ONE paper `runs` row per (version, day) as the FK parent."""
        try:
            abs_qty = abs(qty)
            day = utcnow()[:10]  # UTC date bucket — same leg re-touched within the day collapses to one row
            digest = hashlib.sha1(
                f"{strategy_version_id}|{instrument_id}|{venue}|{side}|{abs_qty}|{price}|{day}".encode()
            ).hexdigest()
            exec_id = f"fill-{digest}"
            if self.store.row("SELECT 1 FROM executions WHERE id = ?", (exec_id,)) is not None:
                return  # already logged this fill this day — idempotent no-op (no double-count)
            run_id = self._paper_run_for(strategy_version_id, venue, day)
            self.store.rows(
                """
                INSERT INTO executions(id, run_id, strategy_version_id, instrument_id, venue_id, side, qty,
                    price, fee, slippage, order_type, is_paper, ts, fill_log)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '0', 'market', ?, ?, ?)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    exec_id, run_id, strategy_version_id, instrument_id, venue,
                    "buy" if side > 0 else "sell", str(abs_qty), str(price), str(fee),
                    1 if is_paper else 0, utcnow(), json.dumps({"source": "apply_fill"}),
                ),
            )
        except Exception:  # noqa: BLE001 — the ledger row is advisory display data; never break the money path
            return

    def _paper_run_for(self, strategy_version_id: str | None, venue: str, day: str) -> str:
        """The FK-parent `runs` row for a fill's execution, reused per (version, day) so a day's rebalance legs share
        one run instead of minting a run per leg. Deterministic id (so concurrent ticks converge on the same row),
        created on first use, idempotent via ON CONFLICT."""
        run_id = f"paperrun-{strategy_version_id}-{day}"
        self.store.rows(
            "INSERT INTO runs(id, strategy_version_id, mode, venue_id, seed, started_at, status) "
            "VALUES (?, ?, 'paper', ?, 0, ?, 'completed') ON CONFLICT (id) DO NOTHING",
            (run_id, strategy_version_id, venue, utcnow()),
        )
        return run_id

    # --- marks / snapshots -------------------------------------------------------------------------

    def mark_to_market(
        self,
        marks: dict[str, Decimal],
        *,
        funding_by_track: dict[str, Decimal] | None = None,
        cell_resolver=None,  # noqa: ANN001 — Callable[[PositionView], tuple[str,str,str] | None]
    ) -> dict[str, Decimal]:
        """Recompute equity from cash + Σ(qty·mark), write a portfolio_snapshot, and return the derived metrics.
        Cash is bankroll minus net deployed cost basis + realized P&L — no fabricated numbers.

        `cell_resolver(position) -> (version_id, symbol, venue_id) | None` re-keys the per-track marked-value
        trajectory to the BRUT cell: each (version, symbol, venue) cell gets its OWN scope='track' snapshot series
        (ref_id = version:symbol:venue) and its OWN tracks row (matched on version+symbol+venue), so a cell's
        forward-proof + drift read ITS OWN trajectory, never a sibling cell's. None (the default / a position the
        resolver can't place) falls back to the legacy VERSION-only key (ref_id = version_id, tracks matched on
        version only) — back-compatible for every pre-brut caller and pre-migration row.

        `funding_by_track` is the cumulative funding P&L per strategy_version_id for two-leg neutral tracks (the
        carry the short-perp leg has booked — see master/neutral.py). It is ADDED to equity and to that track's
        marked-value series. Absent/empty (every spot caller) it is a no-op, so the single-leg spot mark path is
        byte-identical to before. Σ(qty·mark) already nets the short perp leg correctly via its negative signed
        qty — funding is the only carry term the price marks don't already capture."""
        funding_by_track = funding_by_track or {}
        positions = self.positions()
        # Realized P&L lives on EVERY position row, including rows the paper executor has closed to
        # qty=0 — reading it off open positions only would make a closed trade's realized P&L vanish from
        # equity the moment it books (latent while nothing ever closed; live since exits exist).
        all_rows = [self._to_view(r) for r in self.store.rows("SELECT * FROM positions")]
        realized = sum((p.realized_pnl for p in all_rows), Decimal("0"))
        deployed = sum((p.avg_price * p.qty for p in positions), Decimal("0"))
        positions_value = sum((marks.get(p.instrument_id, p.avg_price) * p.qty for p in positions), Decimal("0"))
        funding = sum(funding_by_track.values(), Decimal("0"))
        cash = self.bankroll + realized - deployed + funding
        equity = cash + positions_value
        high_water = self._high_water(equity)
        drawdown = Decimal("0") if high_water == 0 else (high_water - equity) / high_water
        pnl = equity - self.bankroll
        now = utcnow()
        self.store.insert(
            "portfolio_snapshots",
            {
                "scope": "aggregate",
                "ref_id": "global",
                "ts": now,
                "equity": str(equity.quantize(Decimal("0.01"))),
                "cash": str(cash.quantize(Decimal("0.01"))),
                "positions_value": str(positions_value.quantize(Decimal("0.01"))),
                "pnl": str(pnl.quantize(Decimal("0.01"))),
                "drawdown": str(max(drawdown, Decimal("0")).quantize(Decimal("0.0001"))),
            },
        )
        # Also accrue a per-TRACK marked-value trajectory (existing scope/ref_id columns, no schema change) so
        # master/drift has a real per-track realized series to estimate edge half-life + live drift from. A
        # track's value = its starting_capital + unrealized (open legs) + realized (ALL its rows — a closed
        # leg's P&L must stay in the trajectory, and a fully-flat track is worth its capital ± realized, not
        # zero). A version with no tracks row (bare positions in tests/tools) falls back to the old
        # marked-positions + realized sum.
        # Resolve each position to its CELL KEY (version:symbol:venue when cell_resolver places it AND the live
        # tracks schema carries the cell columns, else the legacy version-only key) and remember the cell tuple so
        # the tracks lookup below can match on version+symbol+venue. Pre-migration (no cell columns on prod tracks)
        # the resolver is IGNORED and every series is version-keyed — byte-for-byte the pre-PR (main) behaviour, so
        # the cell-keyed SQL never touches a column the live table lacks.
        has_cell_cols = tracks_has_cell_columns(self.store)
        cell_meta: dict[str, tuple[str, str, str] | None] = {}
        # The (version, symbol, venue) triples that actually OWN a per-cell tracks row. A position is keyed to its
        # cell ONLY when a real cell track exists for it — otherwise a LEGACY version-wide track (symbol/venue NULL,
        # the documented multi-leg arms: DAA/PAA/TSMOM/GTAA/RiskParity/Sector) would split into one orphan per-leg
        # snapshot, each marked to that ONE leg's notional (~capital/n_legs) instead of the whole book, and
        # _update_track_returns then reads a single fragment as the track's equity (DAA $1000 → ~$169 = $1000/6).
        # The single-leg arms (one stamped cell track) were always correct; this keeps them cell-keyed and only
        # folds the version-wide multi-leg arms back onto the version key (their honest aggregate $1000 trajectory).
        # Empty set when the cell columns aren't live (pre-migration) → every triple misses → version-keyed, exactly
        # the prior behaviour. Best-effort: a read hiccup degrades to version-keying, never crashes the mark.
        _cell_track_triples: set[tuple[str, str, str]] = set()
        if has_cell_cols:
            try:
                _cell_track_triples = {
                    (r["strategy_version_id"], r["symbol"], r["venue_id"])
                    for r in self.store.rows(
                        "SELECT strategy_version_id, symbol, venue_id FROM tracks "
                        "WHERE symbol IS NOT NULL AND venue_id IS NOT NULL"
                    )
                }
            except Exception:  # noqa: BLE001 — degrade to version-keying; never break the mark on a read error
                _cell_track_triples = set()

        def _cell_key(p: PositionView) -> str | None:
            if p.strategy_version_id is None:
                return None
            triple = cell_resolver(p) if (cell_resolver is not None and has_cell_cols) else None
            # Adopt the cell key ONLY when a real per-cell track row owns this triple; a legacy version-wide track
            # (no matching cell row) keeps ALL its legs on the version key so the snapshot marks the whole book.
            if triple is not None and tuple(triple) in _cell_track_triples:
                vid, symbol, venue_id = triple
                key = f"{vid}:{symbol}:{venue_id}"
                cell_meta[key] = triple
                return key
            cell_meta.setdefault(p.strategy_version_id, None)
            return p.strategy_version_id

        unrealized_by_track: dict[str, Decimal] = {}
        open_value_by_track: dict[str, Decimal] = {}
        for p in positions:
            key = _cell_key(p)
            if key is None:
                continue
            mark = marks.get(p.instrument_id, p.avg_price)
            unrealized_by_track[key] = unrealized_by_track.get(key, Decimal("0")) + (mark - p.avg_price) * p.qty
            open_value_by_track[key] = open_value_by_track.get(key, Decimal("0")) + mark * p.qty
        realized_by_track: dict[str, Decimal] = {}
        for p in all_rows:
            key = _cell_key(p)
            if key is None:
                continue
            realized_by_track[key] = realized_by_track.get(key, Decimal("0")) + p.realized_pnl
        by_track: dict[str, Decimal] = {}
        for key in {*unrealized_by_track, *realized_by_track}:
            meta = cell_meta.get(key)
            if meta is not None:
                # `meta` is only ever set when the cell columns are live (see `_cell_key`), so the cell-keyed
                # SQL is safe here. The tracks row is the CELL row, matched on (version, symbol, venue).
                vid, symbol, venue_id = meta
                row = self.store.row(
                    "SELECT starting_capital FROM tracks WHERE strategy_version_id = ? AND symbol = ? AND venue_id = ?",
                    (vid, symbol, venue_id),
                )
            else:
                # The version-only key (pre-migration, or a position the resolver couldn't place): `key` IS the
                # version. Never references symbol/venue_id, so a pre-migration prod table never raises.
                row = self.store.row("SELECT starting_capital FROM tracks WHERE strategy_version_id = ?", (key,))
            pnl_track = unrealized_by_track.get(key, Decimal("0")) + realized_by_track.get(key, Decimal("0"))
            if row is not None and row.get("starting_capital") is not None:
                by_track[key] = Decimal(str(row["starting_capital"])) + pnl_track
            else:
                by_track[key] = open_value_by_track.get(key, Decimal("0")) + realized_by_track.get(key, Decimal("0"))
        # Add each neutral track's accrued funding carry to its marked-value series (keyed by version_id; on a
        # single-cell-per-version book the cell key equals the version key — funding lands on the right series).
        for vid, fund in funding_by_track.items():
            if vid in by_track:
                by_track[vid] += fund
        for key, value in by_track.items():
            self.store.insert(
                "portfolio_snapshots",
                {
                    "scope": "track",
                    "ref_id": key,
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
        row = self.store.row("SELECT equity FROM portfolio_snapshots WHERE scope = 'aggregate' ORDER BY ts DESC LIMIT 1")
        return Decimal(str(row["equity"])) if row else self.bankroll

    def drawdown(self) -> Decimal:
        row = self.store.row("SELECT drawdown FROM portfolio_snapshots WHERE scope = 'aggregate' ORDER BY ts DESC LIMIT 1")
        return Decimal(str(row["drawdown"])) if row else Decimal("0")

    def daily_loss(self) -> DailyLossStatus:
        """Loss since the start of the UTC day, as a positive number. Equity now vs. the first snapshot today
        (or bankroll if none) — the auto-disarm trips when this meets the cap."""
        day = datetime.now(tz=UTC).date().isoformat()
        start = self.store.row(
            "SELECT equity FROM portfolio_snapshots WHERE scope = 'aggregate' AND ts >= ? ORDER BY ts ASC LIMIT 1",
            (f"{day}T00:00:00+00:00",),
        )
        start_equity = Decimal(str(start["equity"])) if start else self.bankroll
        loss = max(start_equity - self.equity(), Decimal("0"))
        return DailyLossStatus(daily_loss=loss, cap=self.daily_loss_cap, tripped=loss >= self.daily_loss_cap)

    # --- SANDBOX per-combo wallet ------------------------------------------------------------------

    def track_risk(
        self,
        strategy_version_id: str,
        *,
        symbol: str | None = None,
        venue: str | None = None,
        marks: dict[str, Decimal] | None = None,
    ) -> TrackRiskView:
        """The per-combo wallet view for ONE track — the SANDBOX bound's per-track equity/cash (Q1).

        A track is one wallet of its `starting_capital` (from the tracks row) and can never lose more than that.
        We sum P&L over ONLY this track's positions: realized over ALL its rows (a closed leg's P&L stays in the
        wallet), unrealized over its open legs marked at `marks` (the position's avg_price when no mark — flat,
        conservative). `cash` is the deployable headroom: starting_capital + realized − own open notional, so a
        new entry sized against it can never deploy past the wallet → loss is bounded to starting_capital.

        Scoping: when `symbol`/`venue` are given AND the tracks table carries the cell columns, the wallet is
        the (version, symbol, venue) CELL row; otherwise the version-only tracks row (legacy / pre-migration).
        Positions are matched on strategy_version_id (and `symbol` when supplied) — the book label (sim/live)
        is irrelevant to the wallet. No tracks row / no starting_capital ⇒ starting_capital=None (checks skip).
        """
        marks = marks or {}
        rows = self.store.rows(
            "SELECT * FROM positions WHERE strategy_version_id = ?", (strategy_version_id,)
        )
        views = [self._to_view(r) for r in rows]
        if symbol is not None:
            views = [v for v in views if v.symbol == symbol]
        realized = sum((v.realized_pnl for v in views), Decimal("0"))
        open_legs = [v for v in views if v.qty != 0]
        own_open_notional = sum((v.avg_price * abs(v.qty) for v in open_legs), Decimal("0"))
        unrealized = sum(
            ((marks.get(v.instrument_id, v.avg_price) - v.avg_price) * v.qty for v in open_legs),
            Decimal("0"),
        )
        starting_capital = self._track_starting_capital(strategy_version_id, symbol=symbol, venue=venue)
        if starting_capital is None:
            # No wallet on file — equity/cash are advisory only (the gauntlet skips the per-combo checks).
            equity = realized + unrealized
            return TrackRiskView(None, equity, equity - own_open_notional, len(open_legs))
        equity = starting_capital + realized + unrealized
        cash = starting_capital + realized - own_open_notional
        return TrackRiskView(starting_capital, equity, cash, len(open_legs))

    def _track_starting_capital(
        self, strategy_version_id: str, *, symbol: str | None = None, venue: str | None = None
    ) -> Decimal | None:
        """This track's wallet size from the tracks row. Cell-scoped (version, symbol, venue) when those columns
        are live AND symbol+venue are supplied, else the version-only row (legacy / pre-migration). None when no
        row or no starting_capital — the per-combo bound then skips and the aggregate gauntlet governs."""
        row = None
        if symbol is not None and venue is not None and tracks_has_cell_columns(self.store):
            row = self.store.row(
                "SELECT starting_capital FROM tracks WHERE strategy_version_id = ? AND symbol = ? AND venue_id = ?",
                (strategy_version_id, symbol, venue),
            )
        if row is None:
            row = self.store.row(
                "SELECT starting_capital FROM tracks WHERE strategy_version_id = ?", (strategy_version_id,)
            )
        if row is None or row.get("starting_capital") is None:
            return None
        try:
            return Decimal(str(row["starting_capital"]))
        except Exception:  # noqa: BLE001 — a malformed wallet value must never crash the money path
            return None

    # --- internals ---------------------------------------------------------------------------------

    def _high_water(self, current: Decimal) -> Decimal:
        row = self.store.row("SELECT MAX(CAST(equity AS REAL)) AS hw FROM portfolio_snapshots WHERE scope = 'aggregate'")
        prior = Decimal(str(row["hw"])) if row and row["hw"] is not None else self.bankroll
        return max(prior, current)

    @staticmethod
    def _pid(instrument_id: str, venue: str, strategy_version_id: str | None) -> str:
        return f"{strategy_version_id or 'agg'}:{venue}:{instrument_id}"

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
