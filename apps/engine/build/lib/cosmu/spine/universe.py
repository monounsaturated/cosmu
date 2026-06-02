# intent: read/write the global trading universe — which venues and asset classes are enabled system-wide; inputs: the venues table (seeded from default_catalog on boot); outputs: enabled venue/asset-class sets + audited toggle writes; invariants: at least one venue stays enabled, every change appends an event, and this gate is deterministic and out of any LLM path.

from __future__ import annotations

from typing import Any

from cosmu.knowledge.store import Store
from cosmu.spine.venue import default_catalog

# Venues/asset classes that have a real data + execution path wired today. The rest are
# modelled in the catalog but cannot trade yet, so the UI shows them as "no data yet".
VENUES_WITH_DATA: frozenset[str] = frozenset({"binance"})
CLASSES_WITH_DATA: frozenset[str] = frozenset({"crypto"})

CLASS_LABELS: dict[str, str] = {
    "crypto": "Crypto",
    "equity": "Stocks",
    "prediction": "Prediction markets",
}


def venue_rows(store: Store) -> list[dict[str, Any]]:
    """Current venue states. Falls back to the static catalog when the DB is not yet seeded
    (e.g. a fresh test store), so the gate has a sane default of Binance/crypto enabled."""
    rows = store.rows("SELECT id, name, kind, enabled FROM venues ORDER BY id")
    if rows:
        return [{"id": r["id"], "name": r["name"], "kind": r["kind"], "enabled": bool(r["enabled"])} for r in rows]
    return [{"id": v.id, "name": v.name, "kind": v.kind, "enabled": v.enabled} for v in default_catalog().venues]


def class_active(store: Store) -> dict[str, bool]:
    """Per-asset-class gate. A class not present in the table defaults to active."""
    rows = store.rows("SELECT kind, active FROM asset_class_gates")
    return {r["kind"]: bool(r["active"]) for r in rows}


def enabled_universe(store: Store) -> tuple[set[str], set[str]]:
    """Effective (venue ids, asset classes) the farm/execution may touch.

    Effective = the venue is ticked AND its asset class is active. This is what lets a venue stay
    ticked (its choice remembered) while greyed out because its parent class is switched off.
    """
    rows = venue_rows(store)
    gates = class_active(store)
    venues = {r["id"] for r in rows if r["enabled"] and gates.get(r["kind"], True)}
    classes = {r["kind"] for r in rows if r["enabled"] and gates.get(r["kind"], True)}
    return venues, classes


def set_class_active(store: Store, kind: str, active: bool) -> None:
    """Flip an asset-class gate, audited. Refuses to switch off the last active class."""
    rows = venue_rows(store)
    kinds = {r["kind"] for r in rows}
    if kind not in kinds:
        raise KeyError(kind)
    gates = class_active(store)
    if not active and not any(gates.get(k, True) and k != kind for k in kinds):
        raise ValueError("at least one asset class must stay active")
    store.rows(
        "INSERT INTO asset_class_gates(kind, active) VALUES (?, ?) "
        "ON CONFLICT(kind) DO UPDATE SET active = excluded.active",
        (kind, int(active)),
    )
    store.append_event(actor="human", kind="asset_class_toggle_changed", ref_type="asset_class", ref_id=kind, payload={"active": active})


def has_live_data(store: Store) -> bool:
    """True when at least one enabled venue can actually fetch bars / trade today."""
    venues, _ = enabled_universe(store)
    return bool(venues & VENUES_WITH_DATA)


def set_venue_enabled(store: Store, venue_id: str, enabled: bool) -> list[dict[str, Any]]:
    """Flip a venue on/off, audited. Refuses to disable the last enabled venue."""
    rows = venue_rows(store)
    if venue_id not in {r["id"] for r in rows}:
        raise KeyError(venue_id)
    if not enabled and not any(r["enabled"] and r["id"] != venue_id for r in rows):
        raise ValueError("at least one venue must stay enabled")
    store.rows("UPDATE venues SET enabled = ? WHERE id = ?", (int(enabled), venue_id))
    store.append_event(
        actor="human",
        kind="venue_toggle_changed",
        ref_type="venue",
        ref_id=venue_id,
        payload={"enabled": enabled},
    )
    return venue_rows(store)
