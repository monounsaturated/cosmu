# intent: the global Trades feed — every execution (paper + live) newest-first, each tagged is_paper with its
# owning strategy joined; inputs: none (optional limit); outputs: ExecutionsResponse; invariants: read-only,
# never moves money — listing a fill is a pure read of the executions ledger.

from __future__ import annotations

from fastapi import APIRouter

from cosmu.api._shared import store
from cosmu.api.models import ExecutionListItem, ExecutionsResponse

router = APIRouter()


@router.get("/executions", response_model=ExecutionsResponse)
def executions(limit: int = 200) -> ExecutionsResponse:
    """All trade executions newest-first — paper (SIMULATED, is_paper=1) AND live (real/testnet, is_paper=0)
    together, each tagged `is_paper`, with the owning strategy NAME + version joined. The single Trades page
    renders this one table; the tag is the ONLY thing that separates simulated paper money from real/testnet
    money, so it is never dropped. INNER JOIN strategy_versions/strategies — an execution always belongs to a
    version, so an orphan fill (no version) is intentionally not listed rather than shown with a fabricated name.
    Bounded by `limit` (clamped 1..1000) so a fat ledger never floods the response. Read-only; never funds."""
    n = max(1, min(int(limit), 1000))
    rows = store.rows(
        "SELECT e.id, e.ts, e.strategy_version_id, s.name AS strategy_name, e.side, e.qty, e.price, e.fee, "
        "e.venue_id, CAST(e.is_paper AS INTEGER) AS is_paper "
        "FROM executions e "
        "JOIN strategy_versions sv ON sv.id = e.strategy_version_id "
        "JOIN strategies s ON s.id = sv.strategy_id "
        "ORDER BY e.ts DESC LIMIT ?",
        (n,),
    )
    return ExecutionsResponse(
        rows=[
            ExecutionListItem(
                id=r["id"],
                ts=r["ts"],
                strategy_version_id=r["strategy_version_id"],
                strategy_name=r["strategy_name"],
                side=r["side"],
                qty=float(r["qty"]),
                price=float(r["price"]),
                fee=float(r["fee"]),
                venue=r.get("venue_id"),
                is_paper=bool(r["is_paper"]),
            )
            for r in rows
        ]
    )
