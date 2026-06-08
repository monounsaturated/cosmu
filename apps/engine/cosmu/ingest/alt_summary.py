# intent: keep a tiny per-(provider, metric) rollup of the append-only alt_data store fresh, so the UI's
# "how fresh / how much" reads don't GROUP BY over the ~17M-row alt_data table on every request. inputs:
# the rows just appended in an ingest pass (provider, metric, the batch's MAX(available_at) and count);
# outputs: an INCREMENTAL upsert into alt_data_provider_summary (n_rows += batch_count, latest_available_at
# = max(existing, batch_max)) — never a full re-aggregate of alt_data. invariants: HONEST (a provider/metric
# with no ingested rows has no summary row, so an empty summary → empty answer, never fabricated); best-effort
# on write (a failed upsert NEVER aborts an ingest pass); backend-agnostic (one ON CONFLICT upsert runs on both
# SQLite and Postgres); read-only on the read helpers. No LLM on this path.

from __future__ import annotations

import logging
from typing import Any

from cosmu.knowledge.store import utcnow

logger = logging.getLogger("cosmu.ingest.alt_summary")

# One backend-agnostic upsert: ON CONFLICT is identical syntax on SQLite and Postgres, and `?` placeholders are
# rewritten to `%s` for psycopg2 by the store's _Conn. n_rows ACCUMULATES (+= the batch count) and
# latest_available_at takes the MAX of the existing value and this batch's max — so this stays a running rollup
# that never has to re-scan alt_data. excluded.* is the would-be-inserted row on both backends.
_UPSERT_SQL = (
    "INSERT INTO alt_data_provider_summary (provider, metric, n_rows, latest_available_at, latest_value, updated_at) "
    "VALUES (?, ?, ?, ?, ?, ?) "
    "ON CONFLICT (provider, metric) DO UPDATE SET "
    "n_rows = alt_data_provider_summary.n_rows + excluded.n_rows, "
    # latest_value tracks the VALUE of the newest-available row (PIT: newest available_at wins). All SET
    # expressions read the OLD row state, so this CASE compares against the PRE-update latest_available_at.
    "latest_value = CASE "
    "WHEN alt_data_provider_summary.latest_available_at IS NULL THEN excluded.latest_value "
    "WHEN excluded.latest_available_at IS NULL THEN alt_data_provider_summary.latest_value "
    "WHEN excluded.latest_available_at > alt_data_provider_summary.latest_available_at THEN excluded.latest_value "
    "ELSE alt_data_provider_summary.latest_value END, "
    "latest_available_at = CASE "
    "WHEN alt_data_provider_summary.latest_available_at IS NULL THEN excluded.latest_available_at "
    "WHEN excluded.latest_available_at IS NULL THEN alt_data_provider_summary.latest_available_at "
    "WHEN excluded.latest_available_at > alt_data_provider_summary.latest_available_at "
    "THEN excluded.latest_available_at "
    "ELSE alt_data_provider_summary.latest_available_at END, "
    "updated_at = excluded.updated_at"
)


def record_ingest(writer: Any, provider: str, metric: str, *, n_rows: int, latest_available_at: str | None,
                  latest_value: str | None = None) -> None:
    """Incrementally roll a single just-ingested (provider, metric) batch into alt_data_provider_summary on an
    OPEN write transaction (the same batch that wrote the alt_data rows). n_rows is the count just appended;
    latest_available_at is the MAX(available_at) of that batch (ISO-8601, or None if unknown). A no-op when
    n_rows <= 0 — we never write a 0-row summary, so an empty store stays honestly empty.

    `writer` is a knowledge.store.Writer (has .execute). Best-effort: this NEVER raises — a summary write must
    not be able to abort the ingest pass that produced the data."""
    if n_rows <= 0:
        return
    try:
        writer.execute(
            _UPSERT_SQL,
            (provider, metric, int(n_rows), latest_available_at, latest_value, utcnow()),
        )
    except Exception as exc:  # noqa: BLE001 — the rollup is a cache; a failed upsert must never abort ingest
        logger.warning("alt_data_provider_summary upsert failed for %s/%s (ignored): %s", provider, metric, exc)


def latest_value_per_metric(store: Any) -> dict[str, tuple[float, str | None]]:
    """Latest VALUE per metric (across all providers), read from the summary table (instant) instead of a
    JOIN/GROUP BY over the ~17M-row alt_data table. PIT-honest: for each metric, the provider row with the
    newest latest_available_at wins (newest available value). Returns {metric: (value, latest_available_at)};
    a non-numeric/None latest_value is skipped. Honest-empty / offline-safe: empty or missing table → {}."""
    try:
        rows = store.rows(
            "SELECT metric, latest_value, latest_available_at FROM alt_data_provider_summary"
        )
    except Exception:  # noqa: BLE001 — table may not exist on a fresh/legacy store
        return {}
    best: dict[str, tuple[float, str | None]] = {}
    best_at: dict[str, str] = {}
    for r in rows:
        metric = r.get("metric")
        val = r.get("latest_value")
        at = r.get("latest_available_at")
        if not metric or val is None:
            continue
        try:
            fval = float(val)
        except (TypeError, ValueError):
            continue
        # newest available_at wins (ISO-8601 sorts lexically); first-seen on a None-at tie.
        prev_at = best_at.get(metric)
        if metric not in best or (at is not None and (prev_at is None or at > prev_at)):
            best[metric] = (fval, at)
            if at is not None:
                best_at[metric] = at
    return best


def latest_per_provider(store: Any) -> list[dict[str, Any]]:
    """Per-PROVIDER freshness rollup for the /intelligence data-freshness panel, read from the summary table
    (instant) instead of a GROUP BY over alt_data. Returns one row per provider: {source, last_at, points},
    aggregating the per-(provider, metric) summary rows (SUM n_rows, MAX latest_available_at). Honest-empty:
    an empty summary → []. Offline-safe: a missing table → [] (never fabricated)."""
    try:
        rows = store.rows(
            "SELECT provider, "
            "MAX(latest_available_at) AS last_at, "
            "SUM(n_rows) AS points "
            "FROM alt_data_provider_summary "
            "GROUP BY provider ORDER BY provider"
        )
    except Exception:  # noqa: BLE001 — table may not exist on a fresh/legacy store
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        points = r.get("points")
        out.append(
            {
                "source": r["provider"],
                "last_at": r.get("last_at"),
                "points": int(points) if points is not None else 0,
            }
        )
    return out


def latest_per_metric(store: Any, metrics: list[str]) -> dict[str, str]:
    """Latest available_at per metric (across all providers/symbols), read from the summary table (instant)
    instead of a GROUP BY over alt_data. Returns {metric: latest_available_at_iso} for the requested metrics
    that have data. Honest-empty / offline-safe: empty input or a missing table → {} (never fabricated)."""
    if not metrics:
        return {}
    placeholders = ", ".join("?" for _ in metrics)
    try:
        rows = store.rows(
            f"SELECT metric, MAX(latest_available_at) AS last_at "
            f"FROM alt_data_provider_summary "
            f"WHERE metric IN ({placeholders}) "
            f"GROUP BY metric",
            tuple(metrics),
        )
    except Exception:  # noqa: BLE001 — table may not exist on a fresh/legacy store
        return {}
    out: dict[str, str] = {}
    for r in rows:
        last = r.get("last_at")
        if r.get("metric") and last:
            out[r["metric"]] = str(last)
    return out
