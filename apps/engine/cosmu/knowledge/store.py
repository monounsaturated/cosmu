# intent: persist control-plane truth and audit events; inputs: typed engine records; outputs: queryable rows on SQLite (local/test) or Postgres/Supabase (prod, URL-detected); invariants: executions/events are append-only, every irreversible action writes an event, bulk work runs in one transaction, and the same code path serves both backends.

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from cosmu.config.settings import Settings


def utcnow() -> str:
    return datetime.now(tz=UTC).isoformat()


def _serialize(value: Any) -> Any:
    if isinstance(value, dict | list):
        return json.dumps(value, sort_keys=True)
    return value


# Per-thread "current read connection" set by Store.reading(); lets row()/rows() reuse one connection
# across many small reads instead of opening one per query. Thread-local so concurrent requests don't share.
_session = threading.local()


def _is_postgres(url: str) -> bool:
    return url.startswith("postgres://") or url.startswith("postgresql://")


def _pg_dsn(url: str) -> str:
    """Strip libpq-incompatible query params that Supabase pooled URLs carry (pgbouncer, connection_limit)."""
    parts = urlsplit(url)
    keep = [(k, v) for k, v in parse_qsl(parts.query) if k not in ("pgbouncer", "connection_limit")]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(keep), parts.fragment))


class _Conn:
    """Uniform connection over sqlite3 / psycopg2: '?' placeholders, dict rows, commit/close.
    Keeps every query in the store/loop/api backend-agnostic — write once, run on either."""

    def __init__(self, raw: Any, is_pg: bool) -> None:
        self._raw = raw
        self._pg = is_pg

    def execute(self, sql: str, params: Iterable[Any] = ()) -> Any:
        cur = self._raw.cursor()
        cur.execute(sql.replace("?", "%s") if self._pg else sql, tuple(params))
        return cur

    def executescript(self, sql: str) -> None:
        if self._pg:
            self._raw.cursor().execute(sql)  # psycopg2 runs a multi-statement string in one call
        else:
            self._raw.executescript(sql)

    def insert_many(
        self, table: str, columns: list[str], rows: list[tuple[Any, ...]], *, page_size: int = 1000,
        ignore_duplicates: bool = False,
    ) -> None:
        """Multi-row INSERT in ONE round-trip per chunk — psycopg2 `execute_values` on PG, `executemany` on
        sqlite. Row-by-row `execute()` over a remote pooled Postgres is ~1 network RTT each; batching cut a
        ~1.3M-row LunarCrush backfill from ~6h to minutes. Use for any bulk/backfill write.

        `ignore_duplicates` appends `ON CONFLICT DO NOTHING` (valid on both psycopg2/PG and modern SQLite) so a
        row that collides with a UNIQUE/PK constraint is a harmless no-op instead of raising — used by the
        point-in-time alt_data append, whose `uq_alt_data_pit` index would otherwise make a re-appended (or
        raced) window RAISE."""
        if not rows:
            return
        cur = self._raw.cursor()
        cols = ", ".join(columns)
        conflict = " ON CONFLICT DO NOTHING" if ignore_duplicates else ""
        if self._pg:
            import psycopg2.extras

            psycopg2.extras.execute_values(
                cur, f"INSERT INTO {table} ({cols}) VALUES %s{conflict}", [tuple(r) for r in rows], page_size=page_size
            )
        else:
            placeholders = ", ".join("?" for _ in columns)
            cur.executemany(f"INSERT INTO {table} ({cols}) VALUES ({placeholders}){conflict}", [tuple(r) for r in rows])

    def commit(self) -> None:
        self._raw.commit()

    def close(self) -> None:
        self._raw.close()


class Writer:
    """A write handle bound to a single open connection — used for batched cohort writes."""

    def __init__(self, con: _Conn) -> None:
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

    def execute(self, sql: str, params: Iterable[Any] = ()) -> None:
        """Run a raw write statement (e.g. DELETE/UPDATE) on this batch's single transaction."""
        self._con.execute(sql, params)

    def insert_many(
        self, table: str, columns: list[str], rows: list[tuple[Any, ...]], *, ignore_duplicates: bool = False,
    ) -> None:
        """Batched multi-row INSERT on this transaction (see _Conn.insert_many) — for backfills/cohorts.
        `ignore_duplicates` → `ON CONFLICT DO NOTHING` for idempotent re-append against a UNIQUE constraint."""
        self._con.insert_many(table, columns, [tuple(r) for r in rows], ignore_duplicates=ignore_duplicates)

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
        if not self._is_pg:
            self.settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    @property
    def _is_pg(self) -> bool:
        return _is_postgres(self.settings.database_url)

    def _open(self, *, autocommit: bool = False) -> _Conn:
        """Open one raw backend connection. autocommit=True is for read batches (see `reading`)."""
        if self._is_pg:
            import psycopg2
            import psycopg2.extras

            raw = psycopg2.connect(_pg_dsn(self.settings.database_url), connect_timeout=15)
            raw.autocommit = autocommit
            raw.cursor_factory = psycopg2.extras.RealDictCursor
            return _Conn(raw, True)
        raw = sqlite3.connect(self.settings.sqlite_path, timeout=30)
        raw.row_factory = sqlite3.Row
        raw.execute("PRAGMA foreign_keys = ON")
        raw.execute("PRAGMA journal_mode = WAL")
        raw.execute("PRAGMA synchronous = NORMAL")
        return _Conn(raw, False)

    @contextmanager
    def connect(self) -> Iterator[_Conn]:
        con = self._open()
        try:
            yield con
            con.commit()
        finally:
            con.close()

    @contextmanager
    def reading(self) -> Iterator[None]:
        """Reuse ONE autocommit connection for every row()/rows() call in this block (per thread). Opening a
        fresh remote-Postgres connection per query made the /intelligence overview fire ~15 connects and take
        ~26s, which timed out the web ("Engine not connected"). Read-only; nested calls reuse the outer conn."""
        if getattr(_session, "con", None) is not None:
            yield  # already inside a reading() — the outer block owns the connection
            return
        con = self._open(autocommit=True)
        _session.con = con
        try:
            yield
        finally:
            _session.con = None
            con.close()

    @contextmanager
    def batch(self) -> Iterator[Writer]:
        """One connection + one transaction for many writes (cohort throughput)."""
        with self.connect() as con:
            yield Writer(con)

    def migrate(self) -> None:
        if self._is_pg:
            # Postgres schema is applied out-of-band (schema_postgres.sql in the Supabase SQL editor).
            # Here we only ensure the singleton live-toggle row exists.
            with self.connect() as con:
                con.execute("INSERT INTO live_toggle(id, enabled) VALUES ('global', 0) ON CONFLICT (id) DO NOTHING")
            return
        schema_path = Path(__file__).with_name("schema.sql")
        with self.connect() as con:
            con.executescript(schema_path.read_text())
            con.execute("INSERT INTO live_toggle(id, enabled) VALUES ('global', 0) ON CONFLICT (id) DO NOTHING")

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
        active = getattr(_session, "con", None)  # inside a reading() block → reuse the one open connection
        if active is not None:
            cur = active.execute(query, params)
            return [] if cur.description is None else [dict(r) for r in cur.fetchall()]
        with self.connect() as con:
            cur = con.execute(query, params)
            if cur.description is None:  # non-SELECT (INSERT/UPDATE) — nothing to fetch on either backend
                return []
            return [dict(r) for r in cur.fetchall()]

    def row(self, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        rows = self.rows(query, params)
        return rows[0] if rows else None
