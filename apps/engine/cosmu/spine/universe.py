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


def enabled_universe(store: Store) -> tuple[set[str], set[str]]:
    """(enabled venue ids, enabled asset classes). The farm and execution only touch these."""
    rows = venue_rows(store)
    venues = {r["id"] for r in rows if r["enabled"]}
    classes = {r["kind"] for r in rows if r["enabled"]}
    return venues, classes


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
