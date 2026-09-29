"""cosmu-supabase MCP: read-only named queries over Cosmu control-plane tables.

Connects via DATABASE_URL (SQLite in dev, Postgres/Supabase in prod).
Auth: loads from .env.local at repo root, then process env. Never hardcodes keys.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Load creds: repo-root .env.local first (dev), process env wins (prod/Modal).
_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env.local", override=False)
load_dotenv(".env.local", override=False)

from mcp.server.fastmcp import FastMCP
from sqlalchemy import create_engine, text

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./.cosmu/cosmu.sqlite3")
_IS_SQLITE = DATABASE_URL.startswith("sqlite")

mcp = FastMCP(
    "cosmu-supabase",
    instructions=(
        "Read-only access to Cosmu control-plane tables: gate verdicts, experiments, "
        "trials, alt-data, strategies. All tools are SELECT-only — no writes."
    ),
)


def _engine():
    url = DATABASE_URL
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return create_engine(url, pool_pre_ping=True)


def _rows(conn, sql: str, params: dict | None = None) -> list[tuple]:
    return conn.execute(text(sql), params or {}).fetchall()


# ---------------------------------------------------------------------------
# Schema introspection
# ---------------------------------------------------------------------------

@mcp.tool(
    description="List all table names in the Cosmu database.",
    annotations={"readOnlyHint": True},
)
def list_tables() -> list[str]:
    with _engine().connect() as c:
        if _IS_SQLITE:
            rows = _rows(c, "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        else:
            rows = _rows(
                c,
                "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename",
            )
    return [r[0] for r in rows]


@mcp.tool(
    description="Return columns (name, type, nullable) for a table.",
    annotations={"readOnlyHint": True},
)
def describe_table(table: str) -> list[dict[str, Any]]:
    with _engine().connect() as c:
        if _IS_SQLITE:
            rows = _rows(c, f"PRAGMA table_info({table})")  # noqa: S608 — table name, not user data
            return [{"column": r[1], "type": r[2], "notnull": bool(r[3])} for r in rows]
        else:
            rows = _rows(
                c,
                "SELECT column_name, data_type, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=:t "
                "ORDER BY ordinal_position",
                {"t": table},
            )
            return [{"column": r[0], "type": r[1], "nullable": r[2] == "YES"} for r in rows]


# ---------------------------------------------------------------------------
# Gate + experiment data
# ---------------------------------------------------------------------------

@mcp.tool(
    description="Recent Gate run verdicts (PASS/STOP) with full payload, newest first.",
    annotations={"readOnlyHint": True},
)
def get_gate_verdicts(limit: int = 20) -> list[dict[str, Any]]:
    with _engine().connect() as c:
        rows = _rows(
            c,
            "SELECT ts, decision, data_source, payload "
            "FROM gate_verdicts ORDER BY ts DESC LIMIT :n",
            {"n": min(limit, 200)},
        )
    return [
        {"ts": r[0], "decision": r[1], "data_source": r[2], "payload": _json(r[3])}
        for r in rows
    ]


@mcp.tool(
    description=(
        "Experiment records logged by the Gate. kind: 'edge_gate' | 'ablation' "
        "'cross_asset' | 'finder'. Returns metrics, config, soft_label, gate_passed."
    ),
    annotations={"readOnlyHint": True},
)
def get_experiments(limit: int = 20, kind: str | None = None) -> list[dict[str, Any]]:
    where = "WHERE kind=:k " if kind else ""
    sql = (
        "SELECT ts, kind, source, label, config, metrics, soft_label, gate_passed "
        f"FROM experiments {where}ORDER BY ts DESC LIMIT :n"
    )
    with _engine().connect() as c:
        rows = _rows(c, sql, {"k": kind, "n": min(limit, 500)} if kind else {"n": min(limit, 500)})
    return [
        {
            "ts": r[0], "kind": r[1], "source": r[2], "label": r[3],
            "config": _json(r[4]), "metrics": _json(r[5]),
            "soft_label": _f(r[6]), "gate_passed": r[7],
        }
        for r in rows
    ]


@mcp.tool(
    description="Trial ledger (each Gate variant = one counted trial for deflated-Sharpe).",
    annotations={"readOnlyHint": True},
)
def get_trials(limit: int = 30) -> list[dict[str, Any]]:
    with _engine().connect() as c:
        rows = _rows(
            c,
            "SELECT ts, source, label, sharpe_per_obs FROM trials ORDER BY ts DESC LIMIT :n",
            {"n": min(limit, 500)},
        )
    return [{"ts": r[0], "source": r[1], "label": r[2], "sharpe_per_obs": _f(r[3])} for r in rows]


# ---------------------------------------------------------------------------
# Alt-data
# ---------------------------------------------------------------------------

@mcp.tool(
    description=(
        "Read alt-data time series for a symbol + metric. "
        "Common metrics: galaxy_score, fear_greed, funding_rate, news_sentiment, "
        "pm_risk_on, macro_regime. symbol='MARKET' for cross-asset metrics."
    ),
    annotations={"readOnlyHint": True},
)
def get_alt_data(symbol: str, metric: str, limit: int = 100) -> list[dict[str, Any]]:
    with _engine().connect() as c:
        rows = _rows(
            c,
            "SELECT ts, available_at, value FROM alt_data "
            "WHERE symbol=:s AND metric=:m ORDER BY ts DESC LIMIT :n",
            {"s": symbol, "m": metric, "n": min(limit, 2000)},
        )
    return [{"ts": r[0], "available_at": r[1], "value": _f(r[2])} for r in rows]


@mcp.tool(
    description="List distinct (symbol, metric) pairs available in alt_data.",
    annotations={"readOnlyHint": True},
)
def list_alt_data_series() -> list[dict[str, str]]:
    with _engine().connect() as c:
        rows = _rows(
            c,
            "SELECT DISTINCT symbol, metric FROM alt_data ORDER BY symbol, metric",
        )
    return [{"symbol": r[0], "metric": r[1]} for r in rows]


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

@mcp.tool(
    description="List strategies and their latest version status (funded/killed/active).",
    annotations={"readOnlyHint": True},
)
def get_strategies(status: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    where = "AND sv.status=:st " if status else ""
    sql = (
        "SELECT s.id, s.name, s.thesis, sv.status, sv.created_at, sv.killed_at "
        "FROM strategies s "
        "JOIN strategy_versions sv ON sv.strategy_id=s.id "
        f"WHERE sv.id=(SELECT id FROM strategy_versions WHERE strategy_id=s.id ORDER BY created_at DESC LIMIT 1) "
        f"{where}"
        "ORDER BY sv.created_at DESC LIMIT :n"
    )
    params: dict = {"n": min(limit, 200)}
    if status:
        params["st"] = status
    with _engine().connect() as c:
        rows = _rows(c, sql, params)
    return [
        {"id": r[0], "name": r[1], "thesis": r[2], "status": r[3],
         "created_at": r[4], "killed_at": r[5]}
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _json(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return v
    return v


def _f(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except Exception:
        return None


if __name__ == "__main__":
    mcp.run()
