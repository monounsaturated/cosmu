# intent: persist control-plane truth and audit events; inputs: typed engine records; outputs: queryable SQLite/Postgres-ready rows; invariants: executions/events are append-only and every irreversible action writes an event.

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from cosmu.config.settings import Settings


def utcnow() -> str:
    return datetime.now(tz=UTC).isoformat()


@dataclass(frozen=True)
class Store:
    settings: Settings

    def __post_init__(self) -> None:
        self.settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    @contextmanager
    def connect(self) -> Iterable[sqlite3.Connection]:
        con = sqlite3.connect(self.settings.sqlite_path)
        con.row_factory = sqlite3.Row
        try:
            con.execute("PRAGMA foreign_keys = ON")
            yield con
            con.commit()
        finally:
            con.close()

    def migrate(self) -> None:
        schema_path = Path(__file__).with_name("schema.sql")
        with self.connect() as con:
            con.executescript(schema_path.read_text())
            con.execute(
                "INSERT OR IGNORE INTO live_toggle(id, enabled) VALUES ('global', 0)"
            )

    def insert(self, table: str, row: dict[str, Any]) -> str:
        record = {"id": row.get("id", str(uuid4())), **row}
        keys = list(record.keys())
        values = [self._serialize(record[key]) for key in keys]
        placeholders = ", ".join("?" for _ in keys)
        with self.connect() as con:
            con.execute(
                f"INSERT INTO {table} ({', '.join(keys)}) VALUES ({placeholders})",
                values,
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
        with self.connect() as con:
            con.execute(
                "INSERT INTO events(ts, actor, kind, ref_type, ref_id, payload) VALUES (?, ?, ?, ?, ?, ?)",
                (utcnow(), actor, kind, ref_type, ref_id, json.dumps(payload or {}, sort_keys=True)),
            )

    def rows(self, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connect() as con:
            return [dict(row) for row in con.execute(query, params).fetchall()]

    def row(self, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        rows = self.rows(query, params)
        return rows[0] if rows else None

    @staticmethod
    def _serialize(value: Any) -> Any:
        if isinstance(value, dict | list):
            return json.dumps(value, sort_keys=True)
        return value

