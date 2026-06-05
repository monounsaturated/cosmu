# intent: gate-ranked leaderboard; inputs: none; outputs: LeaderboardResponse; invariants: every numeric coerced finite; maturity is advisory, never a gate.

from __future__ import annotations

from fastapi import APIRouter

from cosmu.api._shared import _json, _metric, store
from cosmu.api.models import LeaderboardResponse, LeaderboardRow
from cosmu.master.forward_maturity import maturity as forward_maturity
from cosmu.strategy.taxonomy import derive_facets

router = APIRouter()


@router.get("/leaderboard", response_model=LeaderboardResponse)
def leaderboard() -> LeaderboardResponse:
    # The track's forward-test clock origin = its FIRST `track_opened` event (per-version, written when the
    # deterministic gate opened the standalone track). MIN(ts) is the moment the forward test started ticking;
    # advisory maturity (forward_age_days / live_ready) is computed from it. LEFT JOIN so non-funded rows still
    # appear with a 0-day clock (not yet ready).
    rows = store.rows(
        """
        SELECT sv.id, s.name, sv.status, sv.spec, sv.origin, b.deflated_sharpe, b.oos_return, b.pbo, ev.funded_at
        FROM strategy_versions sv
        JOIN strategies s ON s.id = sv.strategy_id
        LEFT JOIN backtests b ON b.strategy_version_id = sv.id
        LEFT JOIN (
            SELECT ref_id, MIN(ts) AS funded_at FROM events WHERE kind = 'track_opened' GROUP BY ref_id
        ) ev ON ev.ref_id = sv.id
        ORDER BY CAST(COALESCE(b.deflated_sharpe, 0) AS REAL) DESC
        LIMIT 20
        """
    )
    if not rows:
        return LeaderboardResponse(rows=[])
    out: list[LeaderboardRow] = []
    for row in rows:
        # net_pct is the net-of-fee return the maturity signal reads — same field surfaced on the row.
        net_pct = _metric(row["oos_return"]) * 100 - 0.18
        # ADVISORY ONLY (master/forward_maturity.py): surfaced, never a gate. The forward-test clock runs from the
        # track's first mark; live_ready recommends a matured + net-positive track. The operator decides.
        mat = forward_maturity(row["funded_at"], net_pct)
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
    return LeaderboardResponse(rows=out)
