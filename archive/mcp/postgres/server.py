"""cosmu-postgres MCP: direct read-only parameterized queries over the Cosmu Postgres DB.

Postgres-only (rejects sqlite:// URLs). SELECT statements only — any DML/DDL is blocked.
Auth: loads DATABASE_URL from .env.local at repo root, then process env.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env.local", override=False)
load_dotenv(".env.local", override=False)

from mcp.server.fastmcp import FastMCP

DATABASE_URL = os.environ.get("DATABASE_URL", "")
_PG_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1) if DATABASE_URL else ""

mcp = FastMCP(
    "cosmu-postgres",
    instructions=(
        "Direct read-only Postgres access. Use execute_query with parameterised SQL "
        "($1/$2 placeholders for psycopg2-style). Only SELECT is allowed — any attempt "
        "to INSERT/UPDATE/DELETE/DROP raises an error before touching the DB."
    ),
)

# Tokens that indicate a write/DDL statement — checked before sending to Postgres.
_WRITE_TOKENS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|GRANT|REVOKE|COPY|VACUUM|CALL)\b",
    re.IGNORECASE,
)


def _conn():
    import psycopg2

    if not _PG_URL or _PG_URL.startswith("sqlite"):
        raise RuntimeError(
            "cosmu-postgres requires a Postgres DATABASE_URL. "
            "Set DATABASE_URL=postgresql://... in .env.local."
        )
    return psycopg2.connect(_PG_URL)


@mcp.tool(
    description=(
        "Run a parameterised read-only SQL query. "
        "Use %(name)s placeholders and pass a params dict, "
        "or use positional %s and pass a list. "
        "Only SELECT statements are accepted. "
        "Example: execute_query('SELECT * FROM gate_verdicts LIMIT %s', [5])"
    ),
    annotations={"readOnlyHint": True},
)
def execute_query(
    sql: str,
    params: list[Any] | dict[str, Any] | None = None,
) -> dict[str, Any]:
    stripped = sql.strip()
    if _WRITE_TOKENS.search(stripped):
        raise ValueError(
            f"Blocked: detected write/DDL keyword in query. "
            f"cosmu-postgres is read-only. Offending SQL: {stripped[:200]}"
        )
    if not re.match(r"^\s*SELECT\b", stripped, re.IGNORECASE):
        raise ValueError(
            "Only SELECT statements are allowed. "
            f"Query starts with: {stripped[:60]!r}"
        )

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(stripped, params or [])
            cols = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchall()

    return {
        "columns": cols,
        "rows": [list(r) for r in rows],
        "row_count": len(rows),
    }


@mcp.tool(
    description="List all user tables in the public schema.",
    annotations={"readOnlyHint": True},
)
def list_tables() -> list[str]:
    result = execute_query(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
    )
    return [r[0] for r in result["rows"]]


@mcp.tool(
    description="Return column definitions for a table (name, type, nullable, default).",
    annotations={"readOnlyHint": True},
)
def describe_table(table: str) -> list[dict[str, Any]]:
    result = execute_query(
        "SELECT column_name, data_type, is_nullable, column_default "
        "FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=%(t)s "
        "ORDER BY ordinal_position",
        {"t": table},
    )
    cols = result["columns"]
    return [dict(zip(cols, r)) for r in result["rows"]]


if __name__ == "__main__":
    mcp.run()
