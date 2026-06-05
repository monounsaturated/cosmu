from __future__ import annotations

from pydantic import BaseModel

# ---- cost transparency: opex vs alpha (engine builds, web consumes) ----


class CostByCategory(BaseModel):
    category: str
    amount: float


class CostPerStrategy(BaseModel):
    version_id: str
    name: str
    opex: float
    net: float


class InfraLine(BaseModel):
    """One static monthly infra cost line from MASTER_PLAN §9. amount is the midpoint estimate;
    amount_min/amount_max are the range. Source is the authoritative static seed — no billing API."""
    vendor: str
    category: str
    amount: float
    amount_min: float
    amount_max: float
    note: str


class LlmCallSummary(BaseModel):
    """Aggregated summary of recorded LLM calls. total_cost is $0 on :free OpenRouter models
    (accurate). call_count is the real number of rows recorded since the DB was seeded."""
    call_count: int
    total_cost: float
    by_task: dict[str, int]  # task -> call count


class VendorActual(BaseModel):
    """Live-fetched vendor spend for the current month vs its configured monthly budget cap.
    amount=0 for free/constant vendors; budget=0 means uncapped (no alert threshold set)."""
    vendor: str
    category: str
    amount: float
    budget: float   # 0 = uncapped
    period: str     # YYYY-MM


class CostsResponse(BaseModel):
    total_usd: float
    by_category: list[CostByCategory]
    opex_vs_alpha: float
    per_strategy: list[CostPerStrategy]
    infra_lines: list[InfraLine]
    llm_calls: LlmCallSummary
    vendor_actuals: list[VendorActual]
