"""Track lifecycle helpers shared by every create lane (evolution loop, finder, spine, research arms).

The ONE place a forward paper track is born. Centralising the insert kills a whole bug class: before
this, each lane hand-wrote the ``tracks`` insert and seeded ``equity = capital * (1 + oos_return)`` /
``return_pct = oos_return * 100`` — copying the BACKTEST out-of-sample result into the FORWARD columns.
A survivor whose paper clock never advanced (e.g. the orchestrator cron was dark) then displayed its
backtest return as if it were forward P&L, and — worse — ``master/live_eligibility.paper_net_return_pct``
reads ``tracks.return_pct`` as live-arming proof, so a never-traded survivor could read ``live_ready`` on
a backtest number.

A freshly-funded forward track has ZERO forward P&L by definition. The backtest OOS return already lives
in ``backtests.oos_return`` and must never be duplicated here. The paper clock
(``orchestrator.mark_tracks`` → ``_update_track_returns``) is the SOLE writer that advances
``equity`` / ``return_pct``, and only from real marked snapshots.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Protocol

from cosmu.knowledge.store import Store, tracks_has_cell_columns, utcnow

_CENTS = Decimal("0.01")

# GENEROUS-PAPER (watch) lane verdict. A cell that did NOT clear the strict brut gate but is genuinely promising
# is tagged 'watch' on its backtest_symbols row (vs 'pass' for a gate survivor, vs its kill reason otherwise) and
# funded on the SAME zero-real-capital, born-honest paper lane survivors use — so the forward/paper test, not the
# in-sample scan, separates a real edge from a lucky one. A 'watch' cell is NOT a gate pass: the gate verdict and
# the kill reasons are untouched (live-eligibility still reads the per-cell pass passport, never 'watch'); this is
# a parallel generous-paper lane that defunds on drift like any paper cell. (Operator-approved 2026-06-18.)
WATCH_VERDICT = "watch"

# NEAR-MISS criterion (operator-specified, net of fees). A gate-FAILED cell that meets ALL three is promising
# enough to forward-test rather than kill: a real Sharpe, enough of its OWN trades to be judgeable, and money made.
# e.g. DeFi-flow on SOL: sharpe 1.37 / 114 trades / +6.1% return — sub-0.95 DSR but clearly worth watching.
NEAR_MISS_MIN_SHARPE = 1.0
NEAR_MISS_MIN_TRADES = 30
NEAR_MISS_MIN_RETURN_PCT = 0.0


def is_near_miss_cell(*, sharpe: float, trades: int, return_pct: float) -> bool:
    """True iff a (gate-failed) cell is a generous-paper NEAR-MISS: ``sharpe > 1.0`` AND ``trades >= 30`` AND
    ``return_pct > 0`` — all on the cell's OWN net-of-fees validation metrics (the same numbers persisted on its
    ``backtest_symbols`` row). The caller is responsible for only applying this to cells that did NOT pass the gate
    (a passer is already a survivor); this predicate alone never decides pass/fail, it only routes the leftovers
    to the watch lane. ``return_pct`` here is the fractional return (0.061 = +6.1%), matching ``per_symbol['return']``."""
    return (
        float(sharpe) > NEAR_MISS_MIN_SHARPE
        and int(trades) >= NEAR_MISS_MIN_TRADES
        and float(return_pct) > NEAR_MISS_MIN_RETURN_PCT
    )


class _Inserter(Protocol):
    """Anything with ``Store.insert`` / ``Writer.insert`` — composes with both the per-arm Store and the
    cohort batch ``Writer`` so the same helper serves every create lane. ``insert_or_get`` is the conflict-safe
    twin used for the per-cell track insert so a re-promoted cell is a no-op, not an IntegrityError."""

    def insert(self, table: str, row: dict[str, Any]) -> str: ...

    def insert_or_get(self, table: str, row: dict[str, Any], *, conflict_cols: list[str]) -> str: ...


# Lifecycle statuses that count as a LIVE forward-test of a cell. A track whose version is `killed` (failed the
# gate, defunded, or deduped) no longer occupies the (strategy × symbol × venue) slot — a fresh paper track for
# that cell is then legitimate. Mirrors knowledge/lifecycle_status.ALIVE_STATUSES without importing it here (this
# module is imported very early by the create lanes; the set is a tiny stable whitelist, not user input).
_ALIVE_TRACK_STATUSES = ("screened", "paper", "forward_test", "live")


def alive_cell_track_exists(
    store: Store,
    *,
    strategy_name: str,
    symbol: str | None,
    venue_id: str | None,
) -> bool:
    """True when some NON-killed version of the strategy ``strategy_name`` already owns a paper track for the
    cell ``(symbol, venue_id)``.

    This is the CROSS-VERSION idempotency guard the per-cell ``UNIQUE(strategy_version_id, symbol, venue_id)``
    cannot give: the evolution loop mints a BRAND-NEW ``strategies`` + ``strategy_versions`` row on every cron
    pass, so the unique (which is scoped to the synthetic version id) never collides across runs — and a strategy
    that keeps clearing the generous-paper watch lane accumulates one duplicate zero-/seed-capital track per pass
    on the SAME (strategy × symbol × venue) cell. The stable cross-run identity is the strategy NAME (the loop's
    fresh ids are not), so the slot is keyed on ``strategies.name`` joined through the version to its alive tracks.

    Best-effort + crash-proof: any read error (or a pre-migration tracks table lacking the cell columns) returns
    False so the guard NEVER blocks a legitimate first open — it only suppresses a provable duplicate. Returns
    False when ``symbol``/``venue_id`` are not both given (a version-wide legacy track carries no cell identity to
    dedupe on, so the caller's existing one-track-per-version guard remains the authority there)."""
    if not symbol or not venue_id:
        return False
    try:
        if not tracks_has_cell_columns(store):
            return False  # pre-migration: no cell identity on the row to match — defer to the per-version guard
        placeholders = ", ".join(["?"] * len(_ALIVE_TRACK_STATUSES))
        row = store.row(
            "SELECT 1 FROM tracks tr "
            "JOIN strategy_versions sv ON sv.id = tr.strategy_version_id "
            "JOIN strategies s ON s.id = sv.strategy_id "
            f"WHERE s.name = ? AND tr.symbol = ? AND tr.venue_id = ? AND sv.status IN ({placeholders}) "
            "LIMIT 1",
            (strategy_name, symbol, venue_id, *_ALIVE_TRACK_STATUSES),
        )
        return row is not None
    except Exception:  # noqa: BLE001 — an idempotency probe must never break the create/research path.
        return False


def open_paper_track(
    writer: _Inserter,
    *,
    version_id: str,
    starting_capital: Decimal | str | float,
    target_vol: float | None = None,
    symbol: str | None = None,
    venue_id: str | None = None,
    store: Store | None = None,
) -> str:
    """Insert a forward paper track seeded HONESTLY: ``equity = starting_capital``, ``return_pct = 0``.

    This is the only sanctioned way to create a track. Never seed forward columns from a backtest/OOS
    number — the paper clock fills them in from real marks. Returns the new track id.

    ``target_vol`` (T1 sizing): median EWMA realized vol from the strategy's backtest validation price
    returns, frozen at funding. None → T0 static sizing (max_position_pct × conviction).

    ``symbol`` / ``venue_id`` (BRUT per-cell tracks): the tradeable triple (algorithm × asset × venue) this
    track proves. Back-compatible defaults None → a version-wide track (legacy / pre-migration). When given,
    the row carries the cell columns so the per-cell forward-proof readers (master/live_eligibility) scope to
    THIS cell, and the per-cell UNIQUE(version,symbol,venue) lets one version hold one track per passing cell.

    ``store`` (schema probe): when a per-cell ``symbol``/``venue_id`` is given against a ``writer`` that is a batch
    ``Writer`` (no schema introspection), pass the owning ``Store`` so the insert can check whether the live
    ``tracks`` table actually CARRIES the cell columns. Pre-migration (current prod — columns absent) the cell
    fields are DROPPED from the row so the insert never references a column the table lacks (it degrades to a
    version-wide track, the legacy shape the readers fall back to); post-migration / fresh schema they are kept.
    None ⇒ assume the columns exist (fresh-schema default), preserving the pre-existing behaviour for callers that
    don't pass a store.
    """
    cap = Decimal(str(starting_capital))
    row: dict = {
        "strategy_version_id": version_id,
        "starting_capital": str(cap),
        "equity": str(cap.quantize(_CENTS)),
        "return_pct": "0.00",
        "updated_at": utcnow(),
    }
    if target_vol is not None:
        row["target_vol"] = float(target_vol)
    cell_cols_live = tracks_has_cell_columns(store) if store is not None else True
    if cell_cols_live:
        if symbol is not None:
            row["symbol"] = symbol
        if venue_id is not None:
            row["venue_id"] = venue_id
        # Conflict-safe against the per-cell UNIQUE (uq_tracks_cell on strategy_version_id, symbol, venue_id): a
        # RE-PROMOTED cell (the same triple funded again in a later finder/loop pass) is a harmless no-op that
        # returns the EXISTING track id instead of crashing on the unique. Only when the cell columns are live —
        # ON CONFLICT (symbol, venue_id) cannot reference columns a pre-migration table lacks. Pre-migration the
        # plain insert keeps raising on the legacy UNIQUE(strategy_version_id) so the finder/loop guard (one
        # version-wide track per version) stays load-bearing.
        return writer.insert_or_get(
            "tracks", row, conflict_cols=["strategy_version_id", "symbol", "venue_id"]
        )
    return writer.insert("tracks", row)
