# intent: cost transparency — opex vs alpha; inputs: none; outputs: CostsResponse; invariants: reads only persisted rows (no external billing API); secrets/budget caps stay server-side.

from __future__ import annotations

from fastapi import APIRouter

from cosmu.api._shared import _portfolio, store
from cosmu.api.models import (
    CostByCategory,
    CostPerStrategy,
    CostsResponse,
    InfraLine,
    LlmCallSummary,
    VendorActual,
)

router = APIRouter()


@router.get("/costs", response_model=CostsResponse)
def costs() -> CostsResponse:
    """Cost transparency — opex vs alpha. Total spend, spend by category, the opex/equity ratio,
    per-strategy opex vs net edge, the static infra cost table (MASTER_PLAN §9), and a summary of
    recorded LLM calls. Seeds the static infra lines on first call (idempotent per calendar month).
    Reads only persisted rows — no external billing API calls."""
    # Seed static infra lines (idempotent: once per calendar month). Best-effort.
    try:
        from cosmu.costs.writer import seed_infra_costs
        seed_infra_costs(store)
    except Exception:  # noqa: BLE001 — seed is best-effort; never crash the endpoint
        pass

    cost_rows = store.rows("SELECT category, SUM(CAST(amount AS REAL)) AS amount FROM costs GROUP BY category")
    by_category = [CostByCategory(category=r["category"], amount=float(r["amount"] or 0)) for r in cost_rows]
    total = round(sum(c.amount for c in by_category), 6)
    try:
        equity = float(_portfolio().equity())
    except Exception:  # noqa: BLE001 — equity is best-effort; the cost page must render without it
        equity = 0.0
    per_rows = store.rows(
        """
        SELECT sv.id AS version_id, s.name AS name,
               SUM(CAST(c.amount AS REAL)) AS opex,
               COALESCE(CAST(tr.equity AS REAL) - CAST(tr.starting_capital AS REAL), 0) AS net
        FROM costs c
        JOIN strategy_versions sv ON sv.id = c.strategy_version_id
        JOIN strategies s ON s.id = sv.strategy_id
        LEFT JOIN tracks tr ON tr.strategy_version_id = sv.id
        GROUP BY sv.id, s.name, tr.equity, tr.starting_capital
        """
    )
    per_strategy = [
        CostPerStrategy(version_id=r["version_id"], name=r["name"], opex=round(float(r["opex"] or 0), 6), net=round(float(r["net"] or 0), 6))
        for r in per_rows
    ]

    # Build the static infra table from the seeded costs rows (meta field identifies infra seeds).
    import json as _json_mod
    # NOTE: the LIKE pattern MUST be a bound parameter — an inline '%' collides with psycopg2's
    # %-paramstyle (store passes a params tuple), raising IndexError on Postgres (SQLite tolerates it).
    infra_rows = store.rows(
        "SELECT vendor, category, CAST(amount AS REAL) AS amount, meta FROM costs WHERE meta LIKE ?",
        ('%"seed": "infra"%',),
    )
    seen_vendors: set[str] = set()
    infra_lines: list[InfraLine] = []
    for r in infra_rows:
        vendor = r["vendor"]
        if vendor in seen_vendors:
            continue  # keep only the first (latest) seed row per vendor
        seen_vendors.add(vendor)
        try:
            meta = _json_mod.loads(r["meta"]) if isinstance(r["meta"], str) else (r["meta"] or {})
        except (ValueError, TypeError):
            meta = {}
        infra_lines.append(InfraLine(
            vendor=vendor,
            category=r["category"],
            amount=float(r["amount"] or 0),
            amount_min=float(meta.get("amount_min", r["amount"] or 0)),
            amount_max=float(meta.get("amount_max", r["amount"] or 0)),
            note=str(meta.get("note", "")),
        ))

    # LLM call summary from llm_calls table.
    llm_count_row = store.row("SELECT COUNT(*) AS n, COALESCE(SUM(CAST(cost AS REAL)), 0) AS total FROM llm_calls")
    llm_count = int(llm_count_row["n"] or 0) if llm_count_row else 0
    llm_total = float(llm_count_row["total"] or 0.0) if llm_count_row else 0.0
    task_rows = store.rows("SELECT task, COUNT(*) AS n FROM llm_calls GROUP BY task")
    by_task = {r["task"]: int(r["n"]) for r in task_rows}

    # Vendor actuals: latest live-fetched row per vendor (meta seed='vendor').
    # Enriched with per-vendor budget caps from settings — never stored in DB (secrets stay server-side).
    from cosmu.config.settings import get_settings as _get_settings
    _settings = _get_settings()
    _budget = _settings.budget
    _vendor_budget_map: dict[str, float] = {
        "OpenRouter": float(_budget.openrouter.monthly_cap),
        "xAI": float(_budget.xai.monthly_cap),
        "Railway": float(_budget.railway.monthly_cap),
        "Modal": float(_budget.modal.monthly_cap),
        "Claude": float(_budget.claude.monthly_cap),
    }
    vendor_rows = store.rows(
        "SELECT vendor, category, CAST(amount AS REAL) AS amount, meta "
        "FROM costs WHERE meta LIKE ? ORDER BY ts DESC",
        ('%"seed": "vendor"%',),
    )
    seen_v: set[str] = set()
    vendor_actuals: list[VendorActual] = []
    for r in vendor_rows:
        v = r["vendor"]
        if v in seen_v:
            continue
        seen_v.add(v)
        try:
            meta = _json_mod.loads(r["meta"]) if isinstance(r["meta"], str) else (r["meta"] or {})
        except (ValueError, TypeError):
            meta = {}
        vendor_actuals.append(VendorActual(
            vendor=v,
            category=r["category"],
            amount=float(r["amount"] or 0),
            budget=_vendor_budget_map.get(v, 0.0),
            period=str(meta.get("month", "")),
        ))

    return CostsResponse(
        total_usd=total,
        by_category=by_category,
        opex_vs_alpha=round(total / equity, 6) if equity else 0.0,
        per_strategy=per_strategy,
        infra_lines=infra_lines,
        llm_calls=LlmCallSummary(call_count=llm_count, total_cost=llm_total, by_task=by_task),
        vendor_actuals=vendor_actuals,
    )
