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


class _Inserter(Protocol):
    """Anything with ``Store.insert`` / ``Writer.insert`` — composes with both the per-arm Store and the
    cohort batch ``Writer`` so the same helper serves every create lane. ``insert_or_get`` is the conflict-safe
    twin used for the per-cell track insert so a re-promoted cell is a no-op, not an IntegrityError."""

    def insert(self, table: str, row: dict[str, Any]) -> str: ...

    def insert_or_get(self, table: str, row: dict[str, Any], *, conflict_cols: list[str]) -> str: ...


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
