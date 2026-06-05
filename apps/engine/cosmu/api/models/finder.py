from __future__ import annotations

from pydantic import BaseModel

# ---- Strategy Finder (grid-search → screen → Gate + profit_factor → WFO/holdout → config library) ----


class FinderRunRequest(BaseModel):
    max_variants: int | None = None
    seed_real: bool = False  # persist real backtested strategies to the configured store (bootstrap)


class FinderVariant(BaseModel):
    config_tag: str
    version_id: str | None
    profit_factor: float        # DISPLAYED secondary metric
    deflated_sharpe: float      # the ranking metric
    net_profit: float
    num_trades: int
    gate_passed: bool
    promoted: bool
    holdout_passed: bool


class FinderResponse(BaseModel):
    strategy_name: str
    grid_size: int
    screened: int
    gate_passed: int
    promoted: int
    leaderboard: list[FinderVariant]
    survivors: list[FinderVariant]
