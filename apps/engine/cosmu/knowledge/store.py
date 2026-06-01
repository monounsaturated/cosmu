# intent: persist control-plane truth and audit events; inputs: typed engine records; outputs: queryable SQLite/Postgres-ready rows; invariants: executions/events are append-only, every irreversible action writes an event, and bulk work runs in one transaction.

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from cosmu.config.settings import Settings


def utcnow() -> str:
    return datetime.now(tz=UTC).isoformat()


def _serialize(value: Any) -> Any:
    if isinstance(value, dict | list):
        return json.dumps(value, sort_keys=True)
    return value


class Writer:
    """A write handle bound to a single open connection — used for batched cohort writes."""

    def __init__(self, con: sqlite3.Connection) -> None:
        self._con = con

    def insert(self, table: str, row: dict[str, Any]) -> str:
        record = {"id": row.get("id", str(uuid4())), **row}
        keys = list(record.keys())
        placeholders = ", ".join("?" for _ in keys)
        self._con.execute(
            f"INSERT INTO {table} ({', '.join(keys)}) VALUES ({placeholders})",
            [_serialize(record[key]) for key in keys],
        )
        return str(record["id"])

    def append_event(
        self,
        *,
        actor: str,
        kind: str,
        ref_type: str | None = None,
        ref_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._con.execute(
            "INSERT INTO events(ts, actor, kind, ref_type, ref_id, payload) VALUES (?, ?, ?, ?, ?, ?)",
            (utcnow(), actor, kind, ref_type, ref_id, json.dumps(payload or {}, sort_keys=True)),
        )


@dataclass(frozen=True)
class Store:
    settings: Settings

    def __post_init__(self) -> None:
        self.settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    @contextmanager
    def connect(self) -> Iterable[sqlite3.Connection]:
        con = sqlite3.connect(self.settings.sqlite_path, timeout=30)
        con.row_factory = sqlite3.Row
        try:
            con.execute("PRAGMA foreign_keys = ON")
            con.execute("PRAGMA journal_mode = WAL")
            con.execute("PRAGMA synchronous = NORMAL")
            yield con
            con.commit()
        finally:
            con.close()

    @contextmanager
    def batch(self) -> Iterator[Writer]:
        """One connection + one transaction for many writes (cohort throughput)."""
        with self.connect() as con:
            yield Writer(con)

    def migrate(self) -> None:
        schema_path = Path(__file__).with_name("schema.sql")
        with self.connect() as con:
            con.executescript(schema_path.read_text())
            con.execute("INSERT OR IGNORE INTO live_toggle(id, enabled) VALUES ('global', 0)")

    def insert(self, table: str, row: dict[str, Any]) -> str:
        with self.batch() as writer:
            return writer.insert(table, row)

    def append_event(
        self,
        *,
        actor: str,
        kind: str,
        ref_type: str | None = None,
        ref_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        with self.batch() as writer:
            writer.append_event(actor=actor, kind=kind, ref_type=ref_type, ref_id=ref_id, payload=payload)

    def rows(self, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connect() as con:
            return [dict(row) for row in con.execute(query, params).fetchall()]

    def row(self, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        rows = self.rows(query, params)
        return rows[0] if rows else None
