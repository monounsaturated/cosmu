# intent: compute system-level intelligence metrics — the machine's self-awareness snapshot. Answers
# "is the machine getting smarter?" not just "is it making money?" inputs: the Store (all data lives
# in the audit ledger + strategy_versions + research_notes); outputs: a typed dict the API serializes
# to IntelligenceResponse. invariants: read-only (never mutates); offline-safe; no LLM.

from __future__ import annotations

import json
from typing import Any

from cosmu.knowledge.store import Store


def compute_intelligence(store: Store) -> dict[str, Any]:
    """The system intelligence snapshot — everything the overview needs to show the machine's brain."""
    return {
        "funnel": _funnel(store),
        "gate_efficiency": _gate_efficiency(store),
        "memory": _memory_depth(store),
        "regime_coverage": _regime_coverage(store),
        "data_freshness": _data_freshness(store),
        "ticks": _tick_stats(store),
        "lineage": _lineage_stats(store),
    }


def _funnel(store: Store) -> dict[str, int]:
    """Strategy funnel: how many at each stage."""
    total = _count(store, "SELECT COUNT(*) AS n FROM strategy_versions")
    screened = _count(store, "SELECT COUNT(*) AS n FROM strategy_versions WHERE status != 'killed' OR killed_at IS NOT NULL")
    paper = _count(store, "SELECT COUNT(*) AS n FROM strategy_versions WHERE status = 'paper'")
    live = _count(store, "SELECT COUNT(*) AS n FROM strategy_versions WHERE status = 'live'")
    killed = _count(store, "SELECT COUNT(*) AS n FROM strategy_versions WHERE status = 'killed'")
    gate_passed = _count(store, "SELECT COUNT(*) AS n FROM backtests WHERE passed_gates = 1")
    return {
        "authored": total,
        "screened": total,
        "gate_passed": gate_passed,
        "funded": paper + live,
        "live": live,
        "killed": killed,
    }


def _gate_efficiency(store: Store) -> dict[str, Any]:
    """Gate pass rate over recent ticks — is the author learning from the graveyard?"""
    rows = store.rows(
        "SELECT payload FROM events WHERE kind = 'autonomy_tick_completed' ORDER BY id DESC LIMIT 12"
    )
    trend: list[float] = []
    for r in rows:
        payload = _parse_payload(r.get("payload"))
        s = payload.get("summary", {})
        authored = int(s.get("authored", 0))
        passed = int(s.get("gated_passed", 0))
        if authored > 0:
            trend.append(round(passed / authored, 3))
    trend.reverse()
    current = trend[-1] if trend else 0.0
    improving = len(trend) >= 3 and trend[-1] > trend[0]
    return {"current": current, "trend": trend, "improving": improving}


def _memory_depth(store: Store) -> dict[str, int]:
    """How much has the brain learned?"""
    dead = _count(store, "SELECT COUNT(*) AS n FROM research_notes WHERE kind = 'dead_end'")
    winners = _count(store, "SELECT COUNT(*) AS n FROM research_notes WHERE kind = 'winner'")
    skills = _count(store, "SELECT COUNT(*) AS n FROM skills")
    return {"dead_ends": dead, "winners": winners, "skills": skills, "total": dead + winners + skills}


def _regime_coverage(store: Store) -> dict[str, Any]:
    """Which market regimes do funded strategies have proven edge in?"""
    rows = store.rows(
        "SELECT sv.id, b.regime_label FROM strategy_versions sv "
        "JOIN backtests b ON b.strategy_version_id = sv.id "
        "WHERE sv.status IN ('paper', 'live') AND b.passed_gates = 1"
    )
    coverage: dict[str, int] = {}
    for r in rows:
        label = r.get("regime_label") or "mixed"
        coverage[label] = coverage.get(label, 0) + 1

    all_regimes = ["bull", "bear", "chop"]
    all_vol = ["low", "mid", "high"]
    grid: list[dict[str, Any]] = []
    for trend in all_regimes:
        for vol in all_vol:
            key = f"{trend}/{vol}"
            grid.append({"regime": key, "trend": trend, "vol": vol, "strategies": coverage.get(key, 0)})
    covered = sum(1 for g in grid if g["strategies"] > 0)
    return {"grid": grid, "covered": covered, "total": len(grid), "by_label": coverage}


def _data_freshness(store: Store) -> list[dict[str, Any]]:
    """When was the last successful ingest per source?"""
    rows = store.rows(
        "SELECT provider, MAX(available_at) AS last_at, COUNT(*) AS points "
        "FROM alt_data GROUP BY provider ORDER BY provider"
    )
    return [
        {"source": r["provider"], "last_at": r["last_at"], "points": int(r["points"])}
        for r in rows
    ]


def _tick_stats(store: Store) -> dict[str, Any]:
    """Autonomous tick history."""
    total = _count(store, "SELECT COUNT(*) AS n FROM events WHERE kind = 'autonomy_tick_completed'")
    last_row = store.row(
        "SELECT ts, payload FROM events WHERE kind = 'autonomy_tick_completed' ORDER BY id DESC LIMIT 1"
    )
    last_at = last_row["ts"] if last_row else None

    rows = store.rows(
        "SELECT payload FROM events WHERE kind = 'autonomy_tick_completed' ORDER BY id DESC LIMIT 20"
    )
    total_survivors = 0
    total_authored = 0
    tick_details: list[dict[str, Any]] = []
    for r in rows:
        payload = _parse_payload(r.get("payload"))
        s = payload.get("summary", {})
        authored = int(s.get("authored", 0))
        passed = int(s.get("gated_passed", 0))
        funded = int(s.get("funded", 0))
        total_survivors += passed
        total_authored += authored
        tick_details.append({"authored": authored, "passed": passed, "funded": funded})
    tick_details.reverse()

    avg_survivors = round(total_survivors / total, 2) if total > 0 else 0.0
    return {
        "total": total,
        "last_at": last_at,
        "avg_survivors_per_tick": avg_survivors,
        "total_authored": total_authored,
        "total_survivors": total_survivors,
        "recent": tick_details,
    }


def _lineage_stats(store: Store) -> dict[str, Any]:
    """Which origins/mutation operators produce the most gate-passers?"""
    rows = store.rows(
        "SELECT sv.origin, sv.mutation_operator, b.passed_gates "
        "FROM strategy_versions sv LEFT JOIN backtests b ON b.strategy_version_id = sv.id"
    )
    by_origin: dict[str, dict[str, int]] = {}
    by_operator: dict[str, dict[str, int]] = {}
    for r in rows:
        origin = r.get("origin") or "unknown"
        op = r.get("mutation_operator") or "none"
        passed = bool(r.get("passed_gates"))
        by_origin.setdefault(origin, {"total": 0, "passed": 0})
        by_origin[origin]["total"] += 1
        if passed:
            by_origin[origin]["passed"] += 1
        by_operator.setdefault(op, {"total": 0, "passed": 0})
        by_operator[op]["total"] += 1
        if passed:
            by_operator[op]["passed"] += 1

    origins = [
        {"origin": k, "total": v["total"], "passed": v["passed"],
         "rate": round(v["passed"] / v["total"], 3) if v["total"] > 0 else 0.0}
        for k, v in sorted(by_origin.items(), key=lambda kv: kv[1].get("passed", 0), reverse=True)
    ]
    operators = [
        {"operator": k, "total": v["total"], "passed": v["passed"],
         "rate": round(v["passed"] / v["total"], 3) if v["total"] > 0 else 0.0}
        for k, v in sorted(by_operator.items(), key=lambda kv: kv[1].get("passed", 0), reverse=True)
    ]
    return {"by_origin": origins, "by_operator": operators}


def _count(store: Store, sql: str) -> int:
    row = store.row(sql)
    return int(row["n"]) if row else 0


def _parse_payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}
