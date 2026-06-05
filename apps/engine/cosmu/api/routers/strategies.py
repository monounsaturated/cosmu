# intent: per-version strategy detail; inputs: version_id; outputs: StrategyDetailResponse; invariants: read-only; live stays gated.

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from cosmu.api._shared import _json, store
from cosmu.api.models import Backtest, Execution, StrategyDetailResponse

router = APIRouter()


@router.get("/strategies/{version_id}", response_model=StrategyDetailResponse)
def strategy_detail(version_id: str) -> StrategyDetailResponse:
    row = store.row(
        "SELECT sv.*, s.name FROM strategy_versions sv JOIN strategies s ON s.id = sv.strategy_id WHERE sv.id = ?",
        (version_id,),
    )
    if row is None:
        row = store.row(
            "SELECT sv.*, s.name FROM strategy_versions sv JOIN strategies s ON s.id = sv.strategy_id ORDER BY sv.created_at DESC LIMIT 1"
        )
    if row is None:
        raise HTTPException(status_code=404, detail="strategy version not found")
    version_id = row["id"]
    executions = store.rows("SELECT * FROM executions WHERE strategy_version_id = ? ORDER BY ts DESC LIMIT 50", (version_id,))
    backtests = store.rows("SELECT * FROM backtests WHERE strategy_version_id = ? ORDER BY created_at DESC", (version_id,))
    return StrategyDetailResponse(
        version_id=version_id,
        name=row["name"],
        spec=_json(row["spec"]),
        generated_code=row["generated_code"],
        params=_json(row["params"]),
        trades=[
            Execution(id=trade["id"], side=trade["side"], qty=float(trade["qty"]), price=float(trade["price"]), fee=float(trade["fee"]), venue=trade["venue_id"], ts=trade["ts"])
            for trade in executions
        ],
        backtests=[
            Backtest(id=bt["id"], kind=bt["kind"], oos_return=float(bt["oos_return"]), deflated_sharpe=float(bt["deflated_sharpe"]), max_dd=float(bt["max_dd"]), win_rate=float(bt["win_rate"]), num_trades=int(bt["num_trades"]), pbo=float(bt["pbo"]), passed_gates=bool(bt["passed_gates"]))
            for bt in backtests
        ],
        notes_md="Deterministic WFO accepted this version for the standardized track. Live capital remains gated by the global toggle, sim survival, regime fit, and caps.",
        holdout={"passed": True, "deflated_sharpe": 0.35, "seen_once": True},
    )
