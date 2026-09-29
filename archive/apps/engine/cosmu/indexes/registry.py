# intent: persistence for the INDEX definition registry — create / list / get the operator's indexes; inputs:
# a Store + IndexSpecs; outputs: indexes rows + IndexSpec reads; invariants: FAIL-OPEN (a prod DB whose
# migration hasn't run yet reports indexes_available()=False and the API serves an honest "not active" state,
# never a crash), definitions are immutable-by-id (re-register = upsert of the SAME id, audited via updated_at),
# the registry stores DEFINITIONS only — index VALUES live point-in-time in alt_data (provider='index').

from __future__ import annotations

import json

from cosmu.indexes.spec import IndexSpec
from cosmu.knowledge.store import Store, utcnow


def indexes_available(store: Store) -> bool:
    """True when the `indexes` table exists. Probed OUTSIDE any write tx (a failed statement aborts a PG tx);
    callers cache per-request. Mirrors knowledge.block_registry.blocks_available."""
    try:
        store.row("SELECT id FROM indexes LIMIT 1")
        return True
    except Exception:  # noqa: BLE001 — table absent / migration not applied: the registry is simply off
        return False


def register_index(store: Store, spec: IndexSpec) -> IndexSpec:
    """Create or update an index definition (upsert by id). created_at is set once; updated_at moves every save.
    Returns the persisted spec (with created_at populated)."""
    now = utcnow()
    existing = store.row("SELECT created_at FROM indexes WHERE id = ?", (spec.id,))
    created_at = (existing or {}).get("created_at") or spec.created_at or now
    row = {
        "id": spec.id,
        "name": spec.name,
        "rationale": spec.rationale,
        "kind": spec.kind,
        "definition": json.dumps(spec.definition, sort_keys=True),
        "entities": json.dumps(list(spec.entities), sort_keys=True),
        "metric": spec.metric,
        "market_wide": 1 if spec.market_wide else 0,
        "transform_version": spec.transform_version,
        "cadence_minutes": spec.cadence_minutes,
        "status": spec.status,
        "created_at": created_at,
        "updated_at": now,
    }
    cols = list(row.keys())
    placeholders = ", ".join("?" for _ in cols)
    updates = ", ".join(f"{c} = excluded.{c}" for c in cols if c not in ("id", "created_at"))
    with store.batch() as w:
        w.execute(
            f"INSERT INTO indexes ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT (id) DO UPDATE SET {updates}",
            tuple(row[c] for c in cols),
        )
    return spec.model_copy(update={"created_at": created_at})


def _row_to_spec(r: dict) -> IndexSpec:
    return IndexSpec(
        id=r["id"],
        name=r["name"],
        rationale=r["rationale"],
        kind=r["kind"],
        definition=json.loads(r["definition"]) if r.get("definition") else {},
        entities=json.loads(r["entities"]) if r.get("entities") else [],
        transform_version=r.get("transform_version") or "index-v1",
        cadence_minutes=int(r.get("cadence_minutes") or 60),
        status=r.get("status") or "draft",
        created_at=r.get("created_at"),
    )


def list_indexes(store: Store, *, include_drafts: bool = True) -> list[IndexSpec]:
    """All registered indexes, newest first. Fail-open: an unmigrated store returns []."""
    if not indexes_available(store):
        return []
    where = "" if include_drafts else "WHERE status != 'draft'"
    rows = store.rows(f"SELECT * FROM indexes {where} ORDER BY created_at DESC, id ASC")
    return [_row_to_spec(r) for r in rows]


def get_index(store: Store, index_id: str) -> IndexSpec | None:
    if not indexes_available(store):
        return None
    r = store.row("SELECT * FROM indexes WHERE id = ?", (index_id,))
    return _row_to_spec(r) if r else None


def active_indexes(store: Store) -> list[IndexSpec]:
    """The indexes the compute pass should refresh (status='active'). Drafts/paused are skipped."""
    return [s for s in list_indexes(store) if s.status == "active"]
