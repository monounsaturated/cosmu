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


def _is_read_sql(query: str) -> bool:
    """True for a read-only statement (SELECT / WITH). A bare store.rows()/row() running such a query OUTSIDE a
    reading() block is routed through the warm read pool (skips the ~1.7s Supabase handshake); writes
    (INSERT/UPDATE/DELETE — store.rows() is overloaded for those in a few call sites) keep the transactional
    connect() path untouched. Cheap first-keyword check; our writes never start with WITH."""
    head = query.lstrip()[:8].upper()
    return head.startswith("SELECT") or head.startswith("WITH")


def _pg_dsn(url: str) -> str:
    """Strip libpq-incompatible query params that Supabase pooled URLs carry (pgbouncer, connection_limit)."""
    parts = urlsplit(url)
    keep = [(k, v) for k, v in parse_qsl(parts.query) if k not in ("pgbouncer", "connection_limit")]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(keep), parts.fragment))


# WARM READ POOL. A fresh psycopg2 connect to remote Supabase costs ~1.7s (TLS + auth across regions) — and
# `reading()` opened one PER REQUEST, so every page's first engine call paid the full handshake (the dominant
# slice of the ~2s API latency). A process-level pool keeps a handful of autocommit READ connections warm and
# hands them out across requests, dropping that ~1.7s to ~0. Scope is deliberately READ-ONLY (autocommit, no
# transaction state): the money/write path (connect()/batch()) still opens a fresh transactional connection,
# so nothing about commit semantics changes. Lazy + keyed by DSN; thread-safe (ThreadedConnectionPool).
import os as _os  # noqa: E402 — local to the pool helper

_PG_READ_POOLS: dict[str, Any] = {}
_PG_READ_POOL_LOCK = threading.Lock()


def _pg_read_pool(dsn: str) -> Any:
    pool = _PG_READ_POOLS.get(dsn)
    if pool is None:
        with _PG_READ_POOL_LOCK:
            pool = _PG_READ_POOLS.get(dsn)  # re-check under lock
            if pool is None:
                import psycopg2.extras
                from psycopg2.pool import ThreadedConnectionPool

                maxconn = max(2, int(_os.environ.get("PG_READ_POOL_MAX", "8")))
                pool = ThreadedConnectionPool(
                    2, maxconn, dsn, connect_timeout=15, cursor_factory=psycopg2.extras.RealDictCursor
                )
                _PG_READ_POOLS[dsn] = pool
    return pool


class _Conn:
    """Uniform connection over sqlite3 / psycopg2: '?' placeholders, dict rows, commit/close.
    Keeps every query in the store/loop/api backend-agnostic — write once, run on either."""

    def __init__(self, raw: Any, is_pg: bool, *, pool: Any = None) -> None:
        self._raw = raw
        self._pg = is_pg
        # When set, this connection was borrowed from a warm read pool: close() RETURNS it instead of
        # tearing down the (expensive-to-reopen) socket. Discarded only on error (see reading).
        self._pool = pool

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

    def close(self, *, discard: bool = False) -> None:
        """Tear down (fresh connections) or return to the warm pool (borrowed read connections).
        `discard` forces a pooled connection to be CLOSED on return — used when a read block errored,
        so a possibly broken/half-dead socket is never handed to the next borrower."""
        if self._pool is not None:
            try:
                self._pool.putconn(self._raw, close=discard or bool(getattr(self._raw, "closed", 0)))
            except Exception:  # noqa: BLE001 — pool refused it (already closed/full): drop the socket directly
                try:
                    self._raw.close()
                except Exception:  # noqa: BLE001
                    pass
        else:
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

    def insert_or_get(self, table: str, row: dict[str, Any], *, conflict_cols: list[str]) -> str:
        """Idempotent insert against a UNIQUE on `conflict_cols`: `ON CONFLICT (cols) DO NOTHING`, returning the
        NEW id on insert or the EXISTING row's id on conflict. The conflict-safe twin of `insert` for a re-run
        that re-touches a row a UNIQUE index already covers (e.g. a re-promoted brut cell against uq_tracks_cell):
        the second call is a harmless no-op that hands back the original id instead of raising IntegrityError.

        DO NOTHING returns no row, so on a conflict we read the existing id back by the conflict key. The conflict
        columns are a fixed internal whitelist (never user input), safe to embed in the SQL. NULLs in a conflict
        column are treated as DISTINCT by both backends (so a version-wide NULL-symbol/venue row never collides) —
        the existing-id read uses `IS` so it still resolves a row whose conflict key contains NULLs."""
        record = {"id": row.get("id", str(uuid4())), **row}
        keys = list(record.keys())
        placeholders = ", ".join("?" for _ in keys)
        target = ", ".join(conflict_cols)
        cur = self._con.execute(
            f"INSERT INTO {table} ({', '.join(keys)}) VALUES ({placeholders}) "
            f"ON CONFLICT ({target}) DO NOTHING RETURNING id",
            [_serialize(record[key]) for key in keys],
        )
        inserted = cur.fetchone() if cur is not None and cur.description is not None else None
        if inserted is not None:
            return str(record["id"])
        # Conflict (DO NOTHING returned no row): fetch the pre-existing row's id by the conflict key. Use the
        # null-safe equality per backend (Postgres `IS NOT DISTINCT FROM`, SQLite `IS`) so a NULL conflict-column
        # value still matches — a conflict on a partial/NULLable key only happens when the colliding values are
        # identical, which for NULLs needs the null-safe operator (plain `=` would never match a NULL).
        op = "IS NOT DISTINCT FROM" if self._con._pg else "IS"
        where = " AND ".join(f"{c} {op} ?" for c in conflict_cols)
        existing = self._con.execute(
            f"SELECT id FROM {table} WHERE {where} LIMIT 1",
            [_serialize(record[c]) for c in conflict_cols],
        ).fetchone()
        return str(existing["id"]) if existing is not None else str(record["id"])

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
            dsn = _pg_dsn(self.settings.database_url)
            import psycopg2
            import psycopg2.extras
            import psycopg2.pool

            # READ path (autocommit) → borrow a WARM connection from the pool (skips the ~1.7s Supabase
            # handshake). WRITE path → a fresh transactional connection, unchanged (money path untouched).
            if autocommit:
                try:
                    pool = _pg_read_pool(dsn)
                    raw = pool.getconn()
                    raw.autocommit = True
                    return _Conn(raw, True, pool=pool)
                except psycopg2.pool.PoolError:
                    pass  # pool exhausted under burst → fall through to a direct connection (old behavior)
            raw = psycopg2.connect(dsn, connect_timeout=15)
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
        ok = False
        try:
            yield
            ok = True
        finally:
            _session.con = None
            con.close(discard=not ok)  # on error, drop the pooled socket; never reuse a broken one

    def warm_reads(self) -> None:
        """Pre-open the warm read pool at BOOT so the first user request never pays the ~1.7s Supabase
        connection handshake (×2 for the pool's minconn) — that cold spike, landing on the slow multi-read
        strategy-detail sheet, is what made it exceed the web timeout and read "engine did not respond".
        Best-effort + offline-safe: a DB hiccup at boot must not crash the app (we just stay cold and pay
        the handshake lazily on first use). No-op on SQLite (local file open is already cheap)."""
        if not self._is_pg:
            return
        try:
            with self.reading():
                self.row("SELECT 1")
        except Exception:  # noqa: BLE001 — boot warm is best-effort; never crash the app
            pass

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

    def insert_or_get(self, table: str, row: dict[str, Any], *, conflict_cols: list[str]) -> str:
        """Conflict-safe insert (see Writer.insert_or_get): new id on insert, existing id on a UNIQUE collision."""
        with self.batch() as writer:
            return writer.insert_or_get(table, row, conflict_cols=conflict_cols)

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
        # Outside a reading() block: a read-only statement on Postgres borrows a WARM pooled connection
        # (no per-call handshake — the big win for the many routers that fire bare store.rows() reads). Writes
        # and the SQLite path keep the plain connect() route, so transactional/local semantics are unchanged.
        if self._is_pg and _is_read_sql(query):
            con = self._open(autocommit=True)  # pooled
            ok = False
            try:
                cur = con.execute(query, params)
                out = [] if cur.description is None else [dict(r) for r in cur.fetchall()]
                ok = True
                return out
            finally:
                con.close(discard=not ok)  # return to pool, or drop a broken socket on error
        with self.connect() as con:
            cur = con.execute(query, params)
            if cur.description is None:  # non-SELECT (INSERT/UPDATE) — nothing to fetch on either backend
                return []
            return [dict(r) for r in cur.fetchall()]

    def row(self, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        rows = self.rows(query, params)
        return rows[0] if rows else None


# --- schema probe: are the BRUT per-cell columns live on `tracks`? ---------------------------------
# Postgres applies its schema/migrations OUT-OF-BAND (see Store.migrate). The brut per-cell migration
# (2026-06-18_tracks_per_cell.sql) is deliberately HELD for the operator, so prod `tracks` still has NO
# `symbol`/`venue_id` columns while a fresh schema (test SQLite, any new DB) DOES. Every cell-keyed read/write
# of `tracks` must therefore probe the LIVE schema and pick the cell-keyed or the legacy version-only SQL —
# referencing `symbol`/`venue_id` against a pre-migration prod table raises `UndefinedColumn` and crashes the
# paper-clock cron BEFORE any `if row is None` fallback can run. Memoized per DSN (the schema is fixed for a
# process's lifetime; a migration is an out-of-band, restart-bounded event), keyed so two test stores on
# different files never share a verdict.
_TRACKS_CELL_COLUMNS: dict[str, bool] = {}
_TRACKS_CELL_LOCK = threading.Lock()


def tracks_has_cell_columns(store: Store) -> bool:
    """True when the live `tracks` table carries the BRUT per-cell columns (`symbol` AND `venue_id`).

    The single gate every per-cell `tracks` access routes through: present → use the cell-keyed
    (version+symbol+venue) SQL; absent → fall back to the legacy version-only SQL byte-for-byte (no
    symbol/venue_id referenced at all), so the code is correct on BOTH a pre-migration prod table and a
    post-migration / fresh schema with NO code change. Result is memoized per database_url. Tests that mutate a
    store's schema in-process call `reset_tracks_cell_columns_cache()` to re-probe."""
    key = store.settings.database_url
    cached = _TRACKS_CELL_COLUMNS.get(key)
    if cached is not None:
        return cached
    with _TRACKS_CELL_LOCK:
        cached = _TRACKS_CELL_COLUMNS.get(key)  # re-check under lock
        if cached is not None:
            return cached
        if store._is_pg:
            rows = store.rows(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'tracks'"
            )
            names = {r["column_name"] for r in rows}
        else:
            rows = store.rows("PRAGMA table_info(tracks)")
            names = {r["name"] for r in rows}
        present = "symbol" in names and "venue_id" in names
        _TRACKS_CELL_COLUMNS[key] = present
        return present


def reset_tracks_cell_columns_cache() -> None:
    """Clear the per-DSN `tracks` cell-column memo. For tests that ALTER a store's schema in-process (drop/add
    the cell columns) so the next probe re-reads the live table; never needed in prod (schema is fixed per
    process, a migration being an out-of-band restart-bounded event)."""
    with _TRACKS_CELL_LOCK:
        _TRACKS_CELL_COLUMNS.clear()
