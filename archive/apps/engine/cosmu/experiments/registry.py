# intent: the EXPERIMENTS REGISTRY — the thin, append-only ledger every finder/gate run logs to so each result
# carries its exact config + seed + data_version + metrics and is therefore COMPARABLE across runs and EXACTLY
# REGENERABLE. inputs: a Store + per-run ExperimentRecords; outputs: persisted `experiments` rows (+ one audit
# event per batch); invariants: BEST-EFFORT (a registry failure never breaks the finder/gate/money path — the
# hook is instrumentation, not a gate), append-only, LLM-free (a record of what the deterministic engine ran),
# and uniform across SQLite/Postgres via the store's `?`-placeholder layer. The soft_label field carries the
# continuous forward-P&L so the ML ranker has a gradient before any gate-pass exists (see soft_labels.py).

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from cosmu.knowledge.store import Store, utcnow

# The kinds an experiment can be — mirrors the engines that emit them. Free-form on the column, listed here so
# the vocabulary stays discoverable and the readers can filter without magic strings.
KIND_FINDER = "finder"
KIND_FINDER_REFINE = "finder_refine"
KIND_EDGE_GATE = "edge_gate"
KIND_ABLATION = "ablation"
KIND_CROSS_ASSET = "cross_asset"


@dataclass(frozen=True)
class ExperimentRecord:
    """One logged run (or one variant of a run). `config` + `seed` + `data_version` are the regeneration key:
    re-supply matching data and re-run with this config/seed → identical `metrics`. `soft_label` is the
    continuous forward-P&L (gradient before any gate-pass). `gate_passed` is the deterministic verdict if known."""

    kind: str
    source: str
    config: dict[str, Any]
    metrics: dict[str, Any]
    seed: int
    data_version: str
    label: str | None = None
    code_hash: str | None = None
    soft_label: float | None = None
    gate_passed: bool | None = None

    def to_row(self) -> dict[str, Any]:
        now = utcnow()
        return {
            "id": str(uuid4()),
            "ts": now,
            "kind": self.kind,
            "source": self.source,
            "label": self.label,
            "seed": int(self.seed),
            "data_version": self.data_version,
            "code_hash": self.code_hash,
            "config": json.dumps(self.config, sort_keys=True, default=str),
            "metrics": json.dumps(self.metrics, sort_keys=True, default=str),
            "soft_label": None if self.soft_label is None else float(self.soft_label),
            "gate_passed": None if self.gate_passed is None else int(self.gate_passed),
            "created_at": now,
        }


_COLUMNS = (
    "id", "ts", "kind", "source", "label", "seed", "data_version",
    "code_hash", "config", "metrics", "soft_label", "gate_passed", "created_at",
)
_INSERT_SQL = (
    "INSERT INTO experiments (" + ", ".join(_COLUMNS) + ") "
    "VALUES (" + ", ".join("?" for _ in _COLUMNS) + ")"
)


def log_experiment(store: Store, record: ExperimentRecord) -> str | None:
    """Log ONE run to the registry. Best-effort: returns the new row id, or None if the write failed (the
    table is absent on this backend, the store is read-only, etc.) — the caller's finder/gate run is never
    interrupted by instrumentation. Use `log_experiments` for a whole finder grid (one transaction)."""
    ids = log_experiments(store, [record])
    return ids[0] if ids else None


def log_experiments(store: Store, records: list[ExperimentRecord]) -> list[str]:
    """Log MANY runs in ONE transaction (a finder grid is hundreds of variants — one connect, not hundreds).
    Best-effort: on any failure returns [] and leaves the discovery path untouched. Emits a single audit event
    summarizing the batch so the registry write is itself traceable."""
    if not records:
        return []
    rows = [r.to_row() for r in records]
    try:
        with store.batch() as b:
            for row in rows:
                b.execute(_INSERT_SQL, [row[c] for c in _COLUMNS])
            kinds = sorted({r.kind for r in records})
            data_versions = sorted({r.data_version for r in records})
            b.append_event(
                actor="experiments",
                kind="experiments_logged",
                ref_type="experiment_batch",
                ref_id=rows[0]["id"],
                payload={"n": len(rows), "kinds": kinds, "data_versions": data_versions},
            )
    except Exception:  # noqa: BLE001 — instrumentation must never break the finder/gate/money path
        return []
    return [row["id"] for row in rows]


# --------------------------------------------------------------------------- readers


def _decode(row: dict[str, Any]) -> dict[str, Any]:
    """Parse the JSON columns back into dicts for ergonomic reads. Tolerant of already-decoded values."""
    out = dict(row)
    for col in ("config", "metrics"):
        val = out.get(col)
        if isinstance(val, str):
            try:
                out[col] = json.loads(val)
            except (ValueError, TypeError):
                out[col] = {}
    return out


def recent_experiments(
    store: Store, *, kind: str | None = None, data_version: str | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    """The most recent experiments, newest first — optionally filtered by kind and/or data_version (the two
    indexed columns). JSON columns come back decoded. Read-only; safe to call from the API/overview."""
    clauses: list[str] = []
    params: list[Any] = []
    if kind is not None:
        clauses.append("kind = ?")
        params.append(kind)
    if data_version is not None:
        clauses.append("data_version = ?")
        params.append(data_version)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(int(limit))
    try:
        rows = store.rows(f"SELECT * FROM experiments{where} ORDER BY id DESC LIMIT ?", tuple(params))
    except Exception:  # noqa: BLE001 — table absent / backend hiccup → empty, never raise into a reader
        return []
    return [_decode(r) for r in rows]


def count_experiments(store: Store, *, kind: str | None = None) -> int:
    """How many experiments have been logged (optionally by kind). A cheap registry-health/overview number."""
    try:
        if kind is None:
            row = store.row("SELECT COUNT(*) AS n FROM experiments")
        else:
            row = store.row("SELECT COUNT(*) AS n FROM experiments WHERE kind = ?", (kind,))
    except Exception:  # noqa: BLE001
        return 0
    return int(row["n"]) if row else 0
