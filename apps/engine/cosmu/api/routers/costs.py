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

    import json as _json_mod

    # All reads share ONE Postgres connection via store.reading() — eliminates the per-query
    # reconnect overhead (each open was ~200-500 ms on Supabase, 7 queries ≈ 13 s total).
    with store.reading():
        cost_rows = store.rows("SELECT category, SUM(CAST(amount AS REAL)) AS amount FROM costs GROUP BY category")
        by_category = [CostByCategory(category=r["category"], amount=float(r["amount"] or 0)) for r in cost_rows]
        total = round(sum(c.amount for c in by_category), 6)
        try:
            equity = float(_portfolio().equity())
        except Exception:  # noqa: BLE001 — equity is best-effort; the cost page must render without it
            equity = 0.0
        # net edge = the REAL net-of-fee forward P&L (marked scope='track' snapshot − starting_capital), NOT
        # tracks.equity. tracks.equity is SEEDED with the rosy backtest number at funding (e.g. +100%), so
        # subtracting starting_capital surfaced a fabricated "net edge" the moment a track carried a cost.
        # We mirror the leaderboard's honesty: derive from the marked snapshot, and only once the track has
        # genuinely traded on paper (a real is_paper=1 fill) — a funded-but-unfilled / un-marked track has $0
        # realized edge, never the backtest. Day-0 = 0, exactly like the Paper P&L read-out.
        per_rows = store.rows(
            """
            SELECT sv.id AS version_id, s.name AS name,
                   SUM(CAST(c.amount AS REAL)) AS opex,
                   tr.starting_capital AS starting_capital, ps.equity AS marked_equity,
                   EXISTS(SELECT 1 FROM executions e WHERE e.strategy_version_id = sv.id
                          AND CAST(e.is_paper AS INTEGER) = 1) AS has_paper_fills
            FROM costs c
            JOIN strategy_versions sv ON sv.id = c.strategy_version_id
            JOIN strategies s ON s.id = sv.strategy_id
            LEFT JOIN tracks tr ON tr.strategy_version_id = sv.id
            LEFT JOIN (
                SELECT ref_id, equity FROM portfolio_snapshots p1
                WHERE scope = 'track' AND ts = (
                    SELECT MAX(ts) FROM portfolio_snapshots p2 WHERE p2.scope = 'track' AND p2.ref_id = p1.ref_id
                )
            ) ps ON ps.ref_id = sv.id
            GROUP BY sv.id, s.name, tr.starting_capital, ps.equity
            """
        )

        def _net_edge(row: dict) -> float:  # noqa: ANN001 — local honesty helper
            if not bool(row["has_paper_fills"]) or row["marked_equity"] is None or row["starting_capital"] is None:
                return 0.0
            try:
                return float(row["marked_equity"]) - float(row["starting_capital"])
            except (TypeError, ValueError):
                return 0.0

        per_strategy = [
            CostPerStrategy(version_id=r["version_id"], name=r["name"], opex=round(float(r["opex"] or 0), 6), net=round(_net_edge(r), 6))
            for r in per_rows
        ]

        # Build the static infra table from the seeded costs rows (meta field identifies infra seeds).
        # NOTE: the LIKE pattern MUST be a bound parameter — an inline '%' collides with psycopg2's
        # %-paramstyle (store passes a params tuple), raising IndexError on Postgres (SQLite tolerates it).
        infra_rows = store.rows(
            "SELECT vendor, category, CAST(amount AS REAL) AS amount, meta FROM costs WHERE meta LIKE ? LIMIT 200",
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
        task_rows = store.rows("SELECT task, COUNT(*) AS n FROM llm_calls GROUP BY task LIMIT 100")
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
            "FROM costs WHERE meta LIKE ? ORDER BY ts DESC LIMIT 100",
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
