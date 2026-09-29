# intent: ONE canonical ISO-8601 form for every point-in-time timestamp written to the alt-data store (Postgres
# hot tier, Parquet/DuckLake cold tier, JSONL). The store's point-in-time read compares timestamps as TEXT
# (string <=), so lexical order MUST equal chronological order. A vendor source that emits a NAIVE datetime or a
# 'Z' suffix breaks that silently: a naive string sorts before the same aware instant, and 'Z' (0x5A) sorts
# AFTER '+' (0x2B) — so an as-of cut would wrongly include/exclude rows. iso_utc() forces tz-aware UTC with a
# '+00:00' offset and Python's DEFAULT fractional-seconds rule (which is exactly what utcnow()/datetime.isoformat
# already produce for the existing stored rows — so applying it is a no-op on clean data, never a reformat that
# would desync old vs new rows). CANON_RE pins the invariant for a write-path assert.
from __future__ import annotations

import re
from datetime import UTC, datetime

# YYYY-MM-DDTHH:MM:SS[.ffffff]+00:00 — the only shape the store may persist. Fractional seconds optional
# (Python omits them when zero), offset ALWAYS the literal '+00:00' (never 'Z', never naive, never a non-UTC
# offset). Matches the existing alt_data rows, so it is a guard, not a migration.
CANON_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?\+00:00$")


def iso_utc(dt: datetime) -> str:
    """The canonical point-in-time string for `dt`: tz-aware UTC, '+00:00' offset, default fractional seconds.

    A naive datetime is ASSUMED UTC (the store's documented invariant — every ingested clock is UTC); a non-UTC
    offset is converted; a 'Z' form can never appear. Idempotent on already-canonical input, so running it over
    rows written by the old `.isoformat()` path produces an identical string (no silent reformat).
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()
