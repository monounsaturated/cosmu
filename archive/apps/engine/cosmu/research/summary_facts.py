# intent: assemble the DETERMINISTIC facts a per-strategy plain-language summary is written from, plus the
# sha256 staleness pin. inputs: a Store + strategy_version_id. outputs: a JSON-able facts dict (strategy
# name/thesis, spec rationale/lane/bar_size/asset_classes, status/kill_reason, best screen backtest metrics,
# paper track state) and facts_hash(facts). invariants: READ-ONLY over existing tables (strategies,
# strategy_versions, backtests, tracks) — no schema change; no LLM, no network — the summary TEXT is written
# EXTERNALLY (Claude Code on the flat sub), the engine only stores/serves it; facts_hash is sha256 over
# canonical JSON (sort_keys + compact separators) with floats rounded first, so the same facts always pin the
# same hash and a stored summary whose pinned hash differs from the current one is honestly STALE.

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

# ORIGIN_TO_LANE's single source of truth is the API shared module (routers/population derives lanes from it
# too) — imported, never duplicated, so the lane a summary names is always the lane the rest of the app shows.
from cosmu.api._shared import ORIGIN_TO_LANE
from cosmu.knowledge.store import Store


def summary_facts(store: Store, version_id: str) -> dict[str, Any] | None:
    """The deterministic facts a summary is written FROM — and the only thing it may claim. None when the
    version doesn't exist. Every value is read off persisted rows; nothing is computed by an LLM."""
    row = store.row(
        """
        SELECT sv.id, sv.spec, sv.origin, sv.status, sv.kill_reason, s.name, s.thesis
        FROM strategy_versions sv JOIN strategies s ON s.id = sv.strategy_id
        WHERE sv.id = ?
        """,
        (version_id,),
    )
    if row is None:
        return None
    spec = _loads(row["spec"])
    horizon = spec.get("horizon") or {}
    universe = spec.get("universe") or {}
    return {
        "version_id": str(row["id"]),
        "name": row["name"],
        "thesis": row["thesis"],
        "rationale": spec.get("rationale"),
        "lane": ORIGIN_TO_LANE.get(row["origin"], "exploit"),
        "bar_size": horizon.get("bar_size"),
        # sorted → canonical regardless of authoring order, so reordering classes can't flip staleness.
        "asset_classes": sorted(universe.get("asset_classes") or []),
        "status": row["status"],
        "kill_reason": row["kill_reason"],
        "screen": _best_screen(store, str(row["id"])),
        "forward_test": _forward_test(store, str(row["id"])),
    }


def facts_hash(facts: dict[str, Any]) -> str:
    """sha256 of the canonical JSON (sort_keys, compact separators) — the staleness pin. A stored summary
    whose pinned facts_hash differs from the current facts' hash is STALE (the numbers changed)."""
    canonical = json.dumps(facts, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _best_screen(store: Store, version_id: str) -> dict[str, Any] | None:
    """The best screen backtest: gate-passed first, then highest deflated Sharpe, then newest — a total,
    deterministic order. None (honest) when the version was never screened."""
    row = store.row(
        """
        SELECT oos_return, deflated_sharpe, max_dd, num_trades, passed_gates, holdout_passed
        FROM backtests
        WHERE strategy_version_id = ? AND kind = 'screen'
        ORDER BY passed_gates DESC, CAST(deflated_sharpe AS REAL) DESC, created_at DESC
        LIMIT 1
        """,
        (version_id,),
    )
    if row is None:
        return None
    return {
        "oos_return": _num(row["oos_return"]),
        "deflated_sharpe": _num(row["deflated_sharpe"]),
        "max_dd": _num(row["max_dd"]),
        "num_trades": int(row["num_trades"] or 0),
        "passed_gates": bool(row["passed_gates"]),
        "holdout_passed": bool(row["holdout_passed"]),
    }


def _forward_test(store: Store, version_id: str) -> dict[str, Any] | None:
    """The standalone paper track's current state, when one exists. Marks move equity/return_pct (and
    updated_at), so a summary written before a re-mark honestly reads stale — that is the point of the pin."""
    row = store.row(
        "SELECT return_pct, equity, starting_capital, updated_at FROM tracks WHERE strategy_version_id = ?",
        (version_id,),
    )
    if row is None:
        return None
    return {
        "return_pct": _num(row["return_pct"]),
        "equity": _num(row["equity"]),
        "starting_capital": _num(row["starting_capital"]),
        "updated_at": row["updated_at"],
    }


def _num(value: Any) -> float | None:
    """Round to a fixed precision BEFORE hashing so backend numeric formatting (sqlite TEXT vs Postgres
    NUMERIC) can never flip the staleness pin. Non-finite/unparseable → None (honest, hash-stable)."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return round(out, 6) if math.isfinite(out) else None


def _loads(value: Any) -> dict[str, Any]:
    """Spec column → dict on either backend (sqlite stores JSON TEXT; a dict may arrive pre-parsed)."""
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value) if isinstance(value, str) else {}
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
