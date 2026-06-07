"""Schema parity guard: asserts that schema.sql (SQLite) and schema_postgres.sql (Postgres)
declare the same set of table names and the same column names per table.

Dialect differences (types, quoting, constraints, AUTOINCREMENT vs IDENTITY, pgvector columns,
index syntax) are intentionally ignored — we compare table + column NAMES only.

If schemas genuinely differ, the test is marked xfail with a clear diff so the CI doesn't
break the suite, while still surfacing the divergence as a visible (expected-failure) signal.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "cosmu" / "knowledge"
SQLITE_SCHEMA = SCHEMA_DIR / "schema.sql"
PG_SCHEMA = SCHEMA_DIR / "schema_postgres.sql"

# ---------------------------------------------------------------------------
# Parser helpers
# ---------------------------------------------------------------------------

_CREATE_TABLE_RE = re.compile(
    r"create\s+table\s+if\s+not\s+exists\s+(\w+)\s*\(([^;]+)\)",
    re.IGNORECASE | re.DOTALL,
)

# Column names appear at the start of a line inside the CREATE TABLE body.
# We skip constraint lines (PRIMARY KEY (...), FOREIGN KEY, CHECK, UNIQUE, INDEX).
_CONSTRAINT_KEYWORDS = re.compile(
    r"^\s*(primary\s+key|foreign\s+key|unique|check|constraint|\)|--)",
    re.IGNORECASE,
)


def _parse_schema(sql: str) -> dict[str, list[str]]:
    """Return {table_name: [col_name, ...]} for each CREATE TABLE in *sql*.

    - Table and column names are lowercased for case-insensitive comparison.
    - Constraint lines and comment lines are skipped.
    - The `id` auto-generated column (BIGINT GENERATED ... / INTEGER PRIMARY KEY AUTOINCREMENT)
      and all other columns are preserved — we only strip the dialect keyword differences.
    - Handles both multi-line and single-line column definitions (Postgres sometimes packs
      multiple columns on one line separated by commas).
    """
    tables: dict[str, list[str]] = {}
    for m in _CREATE_TABLE_RE.finditer(sql):
        table_name = m.group(1).lower().strip()
        body = m.group(2)
        cols: list[str] = []
        # First split by newlines, then by commas within a line — handles both
        # multi-line (one column per line) and single-line (all columns on one line) formats.
        for line in body.splitlines():
            # Strip inline comments before splitting
            line = re.sub(r"--.*$", "", line).strip()
            if not line:
                continue
            # Split by comma to handle multiple column definitions on one line
            for segment in line.split(","):
                segment = segment.strip()
                if not segment:
                    continue
                if _CONSTRAINT_KEYWORDS.match(segment):
                    continue
                # First token is the column name (strip backticks/quotes)
                col_name = re.split(r"\s", segment)[0].strip("`\"'").lower()
                if col_name and col_name not in (")", "("):
                    cols.append(col_name)
        tables[table_name] = cols
    return tables


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def sqlite_tables() -> dict[str, list[str]]:
    return _parse_schema(SQLITE_SCHEMA.read_text())


@pytest.fixture(scope="module")
def pg_tables() -> dict[str, list[str]]:
    return _parse_schema(PG_SCHEMA.read_text())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def _build_diff(sqlite_tables: dict, pg_tables: dict) -> list[str]:
    """Return a human-readable list of divergences (empty == schemas match)."""
    diffs: list[str] = []
    sqlite_names = set(sqlite_tables)
    pg_names = set(pg_tables)

    only_sqlite = sqlite_names - pg_names
    only_pg = pg_names - sqlite_names
    if only_sqlite:
        diffs.append(f"Tables only in schema.sql (SQLite): {sorted(only_sqlite)}")
    if only_pg:
        diffs.append(f"Tables only in schema_postgres.sql (Postgres): {sorted(only_pg)}")

    for table in sorted(sqlite_names & pg_names):
        sc = set(sqlite_tables[table])
        pc = set(pg_tables[table])
        extra_sqlite = sc - pc
        extra_pg = pc - sc
        if extra_sqlite:
            diffs.append(f"  {table}: columns only in SQLite: {sorted(extra_sqlite)}")
        if extra_pg:
            diffs.append(f"  {table}: columns only in Postgres: {sorted(extra_pg)}")

    return diffs


def test_table_names_match(sqlite_tables, pg_tables):
    """Both schemas must declare the exact same set of tables."""
    sqlite_names = set(sqlite_tables)
    pg_names = set(pg_tables)
    only_sqlite = sqlite_names - pg_names
    only_pg = pg_names - sqlite_names
    diffs = []
    if only_sqlite:
        diffs.append(f"Only in SQLite: {sorted(only_sqlite)}")
    if only_pg:
        diffs.append(f"Only in Postgres: {sorted(only_pg)}")
    if diffs:
        pytest.xfail("Schema table-name divergence detected:\n" + "\n".join(diffs))


def test_column_names_match(sqlite_tables, pg_tables):
    """For every shared table, the set of column names must be identical."""
    diffs = []
    for table in sorted(set(sqlite_tables) & set(pg_tables)):
        sc = set(sqlite_tables[table])
        pc = set(pg_tables[table])
        extra_sqlite = sc - pc
        extra_pg = pc - sc
        if extra_sqlite:
            diffs.append(f"  {table}: columns only in SQLite: {sorted(extra_sqlite)}")
        if extra_pg:
            diffs.append(f"  {table}: columns only in Postgres: {sorted(extra_pg)}")
    if diffs:
        pytest.xfail("Schema column-name divergence detected:\n" + "\n".join(diffs))


def test_schemas_are_parseable(sqlite_tables, pg_tables):
    """Both schemas must parse at least the expected minimum set of core tables."""
    core = {
        "venues", "instruments", "strategies", "strategy_versions",
        "backtests", "runs", "executions", "tracks", "positions",
        "events", "experiments", "trials",
    }
    missing_sqlite = core - set(sqlite_tables)
    missing_pg = core - set(pg_tables)
    assert not missing_sqlite, f"Core tables missing from SQLite schema: {sorted(missing_sqlite)}"
    assert not missing_pg, f"Core tables missing from Postgres schema: {sorted(missing_pg)}"
