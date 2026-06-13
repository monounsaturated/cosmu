# intent: compute system-level intelligence metrics — the machine's self-awareness snapshot. Answers
# "is the machine getting smarter?" not just "is it making money?" inputs: the Store (all data lives
# in the audit ledger + strategy_versions + research_notes); outputs: a typed dict the API serializes
# to IntelligenceResponse. invariants: read-only (never mutates); offline-safe; no LLM.

from __future__ import annotations

import json
import threading
import time
from typing import Any

from cosmu.knowledge.store import Store

# The snapshot is a slow cross-source aggregation: ~15 queries, two of them full-table scans of the
# highest-volume tables (alt_data COUNT/MAX-per-provider, and the unbounded strategy_versions⨯backtests
# lineage join). On prod Postgres that recompute took ~24s and timed out the 5s SSR fetch ("Engine not
# connected"). It only changes when an autonomy tick runs (minutes-to-hours cadence), so we serve a
# process-local TTL cache: the first request pays the cost, the rest are instant and honest (we cache
# whatever was really computed — never a fabricated value, and an honest-empty result is cached too).
_CACHE_TTL_SECONDS = 60.0
_cache_lock = threading.Lock()
_cache: dict[str, Any] | None = None
_cache_at: float = 0.0


def compute_intelligence(store: Store, *, use_cache: bool = True) -> dict[str, Any]:
    """The system intelligence snapshot — everything the overview needs to show the machine's brain.
    Cached for `_CACHE_TTL_SECONDS` to keep the heavy aggregation off the request path (see module note).
    All reads run on ONE shared connection (store.reading()); opening one per query made this ~26s on
    remote Postgres and timed out the web."""
    global _cache, _cache_at
    if use_cache:
        with _cache_lock:
            if _cache is not None and (time.monotonic() - _cache_at) < _CACHE_TTL_SECONDS:
                return _cache

    snapshot = _compute(store)

    if use_cache:
        with _cache_lock:
            _cache = snapshot
            _cache_at = time.monotonic()
    return snapshot


def reset_cache() -> None:
    """Drop the cached snapshot (used by tests, and safe to call to force a recompute next request)."""
    global _cache, _cache_at
    with _cache_lock:
        _cache = None
        _cache_at = 0.0


def _compute(store: Store) -> dict[str, Any]:
    with store.reading():
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
    paper = _count(store, "SELECT COUNT(*) AS n FROM strategy_versions WHERE status IN ('paper', 'forward_test')")
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
    rows = _safe_rows(store,
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
    rows = _safe_rows(store,
        "SELECT sv.id, b.regime_label FROM strategy_versions sv "
        "JOIN backtests b ON b.strategy_version_id = sv.id "
        "WHERE sv.status IN ('paper', 'forward_test', 'live') AND b.passed_gates = 1"
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
    """When was the last successful ingest per source?

    Reads the tiny per-(provider, metric) alt_data_provider_summary rollup (kept fresh incrementally by the
    ingest path) and aggregates it to one row per provider — instant, instead of a GROUP BY over the ~17M-row
    alt_data table (that full seq-scan is what made this panel ~24s and timed out the SSR fetch). The answer
    is identical: {source, last_at = MAX(available_at), points = COUNT(*)} per provider. Honest-empty: an empty
    summary → [] (never a fabricated freshness row)."""
    from cosmu.ingest.alt_summary import latest_per_provider

    return latest_per_provider(store)


def _tick_stats(store: Store) -> dict[str, Any]:
    """Autonomous tick history."""
    total = _count(store, "SELECT COUNT(*) AS n FROM events WHERE kind = 'autonomy_tick_completed'")
    try:
        last_row = store.row(
            "SELECT ts, payload FROM events WHERE kind = 'autonomy_tick_completed' ORDER BY id DESC LIMIT 1"
        )
    except Exception:  # noqa: BLE001
        last_row = None
    last_at = last_row["ts"] if last_row else None

    rows = _safe_rows(store,
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
    rows = _safe_rows(store,
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
    try:
        row = store.row(sql)
        return int(row["n"]) if row else 0
    except Exception:  # noqa: BLE001 — table may not exist on fresh stores
        return 0


def _safe_rows(store: Store, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    try:
        return store.rows(sql, params)
    except Exception:  # noqa: BLE001
        return []


def _parse_payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}
