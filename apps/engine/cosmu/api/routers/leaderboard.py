# intent: gate-ranked leaderboard; inputs: none; outputs: LeaderboardResponse; invariants: every numeric coerced finite; maturity is advisory, never a gate.

from __future__ import annotations

import math

from fastapi import APIRouter

from cosmu.api._shared import _json, _metric, store
from cosmu.api.models import LeaderboardResponse, LeaderboardRow
from cosmu.master.forward_maturity import maturity as forward_maturity
from cosmu.strategy.taxonomy import derive_facets

router = APIRouter()


def _forward_return_pct(tr_equity: object, starting_capital: object) -> float | None:
    """The real net-of-fee forward return % from the marked trajectory: (marked_equity / starting_capital - 1) * 100.
    Returns None when the track has no marked snapshot yet (day-0 / never marked) or its starting_capital is
    missing/degenerate — so the contract carries an honest `null` rather than the rosy backtest number. A marked
    flat/negative track returns its TRUE (0 / negative) number; never falls back to the backtest."""
    if tr_equity is None or starting_capital is None:
        return None
    try:
        start = float(starting_capital)
        equity = float(tr_equity)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(start) and math.isfinite(equity)) or start <= 0:
        return None
    return (equity / start - 1.0) * 100.0


@router.get("/leaderboard", response_model=LeaderboardResponse)
def leaderboard() -> LeaderboardResponse:
    # The track's forward-test clock origin = its FIRST `track_opened` event (per-version, written when the
    # deterministic gate opened the standalone track). MIN(ts) is the moment the forward test started ticking;
    # advisory maturity (forward_age_days / live_ready) is computed from it. LEFT JOIN so non-funded rows still
    # appear with a 0-day clock (not yet ready).
    # forward_return_pct is the REAL forward-test number: marked-to-market equity (the LATEST per-track
    # portfolio_snapshot the mark clock wrote) vs the track's starting_capital — net of fees, since funding.
    # We derive it from the marked SNAPSHOT (not tracks.return_pct, which is SEEDED with the backtest number at
    # funding time): a track with no marked snapshot yet has `tr_equity` NULL → forward_return_pct stays null
    # (day-0 truth), so a fresh track can NEVER surface its rosy backtest as forward performance.
    rows = store.rows(
        """
        SELECT sv.id, s.name, sv.status, sv.spec, sv.origin, b.deflated_sharpe, b.oos_return, b.pbo, ev.funded_at,
               tr.starting_capital, ps.equity AS tr_equity
        FROM strategy_versions sv
        JOIN strategies s ON s.id = sv.strategy_id
        LEFT JOIN backtests b ON b.strategy_version_id = sv.id
        LEFT JOIN (
            SELECT ref_id, MIN(ts) AS funded_at FROM events WHERE kind = 'track_opened' GROUP BY ref_id
        ) ev ON ev.ref_id = sv.id
        LEFT JOIN tracks tr ON tr.strategy_version_id = sv.id
        LEFT JOIN (
            SELECT ref_id, equity FROM portfolio_snapshots p1
            WHERE scope = 'track' AND ts = (
                SELECT MAX(ts) FROM portfolio_snapshots p2 WHERE p2.scope = 'track' AND p2.ref_id = p1.ref_id
            )
        ) ps ON ps.ref_id = sv.id
        ORDER BY CAST(COALESCE(b.deflated_sharpe, 0) AS REAL) DESC
        LIMIT 20
        """
    )
    if not rows:
        return LeaderboardResponse(rows=[])
    out: list[LeaderboardRow] = []
    for row in rows:
      # Defense-in-depth: one malformed row must NEVER 500 the whole floor leaderboard. A row that can't be
      # built is skipped (logged), so the rest of the floor still renders. (derive_facets is also bulletproof.)
      try:
        # net_pct is the net-of-fee return the maturity signal reads — same field surfaced on the row.
        net_pct = _metric(row["oos_return"]) * 100 - 0.18
        # ADVISORY ONLY (master/forward_maturity.py): surfaced, never a gate. The forward-test clock runs from the
        # track's first mark; live_ready recommends a matured + net-positive track. The operator decides.
        mat = forward_maturity(row["funded_at"], net_pct)
        # The REAL forward-test return: marked equity (latest scope='track' snapshot) vs the track's
        # starting_capital, net of fees. Null when the track has NO marked snapshot yet (day-0 / never
        # marked) — we NEVER fall back to b.oos_return, so a fresh track shows its honest 0/— forward, not
        # the rosy backtest. Once marked, a flat/negative forward test shows its TRUE (0 or negative) number.
        forward_return_pct = _forward_return_pct(row["tr_equity"], row["starting_capital"])
        # Facets are DERIVED from the spec's named features (taxonomy.py) — no manual tagging — so the
        # Strategies filters always reflect the strategy's real inputs and structure.
        facets = derive_facets(_json(row["spec"]), row["origin"])
        out.append(
            LeaderboardRow(
                version_id=row["id"],
                name=row["name"],
                # Every numeric field is coerced via _metric so the API NEVER emits
                # null/NaN where the LeaderboardRow contract promises `number`.
                track_return_pct=_metric(row["oos_return"]) * 100,
                deflated_sharpe=_metric(row["deflated_sharpe"]),
                net_pct=net_pct,
                forward_return_pct=forward_return_pct,
                pbo=_metric(row["pbo"]),
                status=row["status"],
                lineage="seed:template -> wfo",
                forward_age_days=mat.forward_age_days,
                live_ready=mat.live_ready,
                signal_family=facets.signal_family,
                signal_family_label=facets.signal_family_label,
                features=facets.features,
                asset_class=facets.asset_class,
                venue=facets.venue,
                timeframe=facets.timeframe,
                origin=facets.origin,
                edge_type=facets.edge_type,
            )
        )
      except Exception:  # noqa: BLE001 — skip a single broken row, never 500 the floor.
        import logging
        logging.getLogger(__name__).warning("leaderboard: skipped a malformed row", exc_info=True)
        continue
    return LeaderboardResponse(rows=out)
