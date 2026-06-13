# intent: population census + graveyard; inputs: none; outputs: PopulationResponse; invariants: read-only over strategy_versions.

from __future__ import annotations

from fastapi import APIRouter

from cosmu.api._shared import ORIGIN_TO_LANE, store
from cosmu.api.models import GraveyardRow, PopulationResponse

router = APIRouter()


@router.get("/population", response_model=PopulationResponse)
def population() -> PopulationResponse:
    counts = store.rows("SELECT status, origin, COUNT(*) AS n FROM strategy_versions GROUP BY status, origin")
    total = sum(int(r["n"]) for r in counts)
    paper = sum(int(r["n"]) for r in counts if r["status"] in ("paper", "forward_test", "live"))
    live = sum(int(r["n"]) for r in counts if r["status"] == "live")
    killed = sum(int(r["n"]) for r in counts if r["status"] == "killed")
    by_origin: dict[str, int] = {}
    by_lane: dict[str, int] = {}
    for r in counts:
        origin = r["origin"] or "unknown"
        by_origin[origin] = by_origin.get(origin, 0) + int(r["n"])
        lane = ORIGIN_TO_LANE.get(origin, "exploit")
        by_lane[lane] = by_lane.get(lane, 0) + int(r["n"])
    grave = store.rows(
        """
        SELECT sv.id, s.name, sv.origin, sv.kill_reason, b.deflated_sharpe
        FROM strategy_versions sv
        JOIN strategies s ON s.id = sv.strategy_id
        LEFT JOIN backtests b ON b.strategy_version_id = sv.id
        WHERE sv.status = 'killed'
        ORDER BY CAST(COALESCE(b.deflated_sharpe, -99) AS REAL) DESC
        LIMIT 40
        """
    )
    return PopulationResponse(
        total=total,
        paper=paper,
        live=live,
        killed=killed,
        by_origin=by_origin,
        by_lane=by_lane,
        kill_rate=round(killed / total, 4) if total else 0.0,
        graveyard=[
            GraveyardRow(
                version_id=r["id"],
                name=r["name"],
                origin=r["origin"] or "unknown",
                kill_reason=r["kill_reason"] or "unknown",
                deflated_sharpe=float(r["deflated_sharpe"] or 0),
            )
            for r in grave
        ],
    )
