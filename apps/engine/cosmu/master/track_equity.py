# intent: ONE honest definition of a "funder seed-collapse" per-track snapshot + the readers that skip it, shared by
# every scope='track' consumer (live-eligibility gate, drift auto-defund, capital guard, decay, the API). inputs:
# scope='track' portfolio_snapshot rows (ts-ascending) + the track's starting_capital (the SEED). outputs: seed-
# filtered row lists / the latest REAL marked equity. invariants: READ-ONLY (never writes, never moves money, never
# consulted as the Gate); a leading day-0 seed run is truth and is KEPT; every other seed-to-the-cent row is dropped.
"""Seed-collapse hygiene for the per-track marked-equity trajectory (scope='track' portfolio_snapshots).

ROOT of the collapse (fixed at the writer in master/portfolio.mark_to_market): the FUNDER
(orchestrator.fund_tracks_from_survivors) re-marks with a marks-dict carrying ONLY the freshly-funded cells, so an
already-held track's legs fall back to cost basis (portfolio.mark_to_market: ``marks.get(id, avg_price)``) →
unrealized == 0 → equity == starting_capital + 0 == the SEED to the cent. Interleaved with the paper clock's real
marks this drew a sawtooth that snapped to the seed; a run of funder-only ticks drew a flat gap pinned at the seed.

A seed-collapse row carries NO information (it is a stale re-mark to basis, not a fresh price), so every reader that
computes a statistic or reads the "current" value must ignore it — otherwise the forward Sharpe / drift / decay /
guard all read a phantom round-trip to the seed. The one honest exception is a LEADING run of seed rows before any
real mark ever landed: that is day-0 truth (the track really is worth its capital until it first marks), so it is
kept. This mirrors the display-side carry-forward in api/_shared.honest_track_equity_series — same fingerprint, but
the statistical readers DROP the row (a funder-only day with no real price is simply not an observation) rather than
carry the last value, so a phantom flat day can never dilute a forward Sharpe.
"""

from __future__ import annotations

from cosmu.knowledge.store import Store, tracks_has_cell_columns

# A genuine mark landing on the seed to the penny is vanishingly unlikely (the entry-day cost-basis snapshot is
# $1,000.02 here, not the $1,000.00 seed), so seed-to-the-cent is the unambiguous funder-collapse fingerprint.
SEED_EPS = 0.005


def is_seed_equity(equity: float, seed: float | None) -> bool:
    """True when this equity is the seed to the cent — the funder-collapse fingerprint. Only meaningful together with
    'a real mark already exists' (see real_track_rows); alone it also matches the honest day-0 seed."""
    return seed is not None and abs(equity - seed) < SEED_EPS


def real_track_rows(rows: list, seed: float | None, *, equity_key: str = "equity") -> list:
    """Drop every seed-collapse row that FOLLOWS a real mark; keep a leading run of seed rows (day-0 truth) and every
    genuine mark. `rows` MUST be ts-ascending. Returns the surviving rows in input order. A row whose equity can't be
    read is dropped, never raised — a malformed snapshot must never break a decision path."""
    out: list = []
    seen_real = False
    for r in rows:
        try:
            eq = float(r[equity_key])
        except (TypeError, ValueError, KeyError):
            continue
        if is_seed_equity(eq, seed):
            if seen_real:
                continue  # funder collapse after a real mark → drop (carries no information)
            out.append(r)  # leading day-0 seed → keep (the track really is worth its capital until it marks)
        else:
            out.append(r)
            seen_real = True
    return out


def latest_real_equity(rows: list, seed: float | None, *, equity_key: str = "equity") -> float | None:
    """The most recent NON-collapse marked equity — the honest 'current' value. `rows` MUST be ts-ascending. None
    when there are no rows at all; a track that has only ever seeded returns its seed (day-0 truth)."""
    kept = real_track_rows(rows, seed, equity_key=equity_key)
    if not kept:
        return None
    try:
        return float(kept[-1][equity_key])
    except (TypeError, ValueError, KeyError):
        return None


def track_starting_capital(store: Store, ref_id: str) -> float | None:
    """The SEED (tracks.starting_capital) for a scope='track' ref_id — schema-aware. `ref_id` is either a cell key
    ``version:symbol:venue`` or the legacy version-only key. Post-migration a cell ref reads the cell row; a
    version-only ref (or a pre-migration table with no cell columns) reads the version row — EXACTLY the seed
    mark_to_market wrote against. None when no track / no capital (the caller then treats nothing as a collapse)."""
    if ":" in ref_id and tracks_has_cell_columns(store):
        vid, symbol, venue = ref_id.split(":", 2)  # cell key: version:symbol:venue (no component contains a colon)
        try:
            row = store.row(
                "SELECT starting_capital FROM tracks WHERE strategy_version_id = ? AND symbol = ? AND venue_id = ?",
                (vid, symbol, venue),
            )
            if row and row.get("starting_capital") is not None:
                return float(row["starting_capital"])
        except (TypeError, ValueError):
            pass
    try:
        row = store.row(
            "SELECT starting_capital FROM tracks WHERE strategy_version_id = ?",
            (ref_id.split(":", 2)[0],),
        )
        return float(row["starting_capital"]) if row and row.get("starting_capital") is not None else None
    except (TypeError, ValueError):
        return None
