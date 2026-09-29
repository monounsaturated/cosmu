# intent: tradable-universe venue/class toggles; inputs: toggle requests; outputs: UniverseResponse; invariants: toggles gate WHAT data/venues are active, never money.

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from cosmu.api._shared import store
from cosmu.api.models import (
    AssetClassState,
    ClassToggleRequest,
    UniverseResponse,
    VenueState,
    VenueToggleRequest,
)
from cosmu.spine.universe import (
    CLASS_LABELS,
    CLASSES_WITH_DATA,
    VENUES_WITH_DATA,
    class_active,
    set_class_active,
    set_venue_enabled,
    venue_rows,
)

router = APIRouter()


def _universe_response() -> UniverseResponse:
    rows = venue_rows(store)
    gates = class_active(store)
    venues = [
        VenueState(
            id=r["id"],
            name=r["name"],
            kind=r["kind"],
            enabled=r["enabled"],
            effective=r["enabled"] and gates.get(r["kind"], True),
            has_data=r["id"] in VENUES_WITH_DATA,
        )
        for r in rows
    ]
    ticked_kinds = {r["kind"] for r in rows if r["enabled"]}
    asset_classes = [
        AssetClassState(
            kind=kind,  # type: ignore[arg-type]
            label=CLASS_LABELS.get(kind, kind.title()),
            active=gates.get(kind, True),
            enabled=gates.get(kind, True) and kind in ticked_kinds,
            has_data=kind in CLASSES_WITH_DATA,
        )
        for kind in dict.fromkeys(r["kind"] for r in rows)
    ]
    return UniverseResponse(venues=venues, asset_classes=asset_classes)


@router.get("/universe", response_model=UniverseResponse)
def universe() -> UniverseResponse:
    return _universe_response()


@router.post("/universe/venue", response_model=UniverseResponse)
def universe_toggle_venue(request: VenueToggleRequest) -> UniverseResponse:
    try:
        set_venue_enabled(store, request.venue_id, request.enabled)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown venue: {request.venue_id}") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return _universe_response()


@router.post("/universe/class", response_model=UniverseResponse)
def universe_toggle_class(request: ClassToggleRequest) -> UniverseResponse:
    try:
        set_class_active(store, request.kind, request.active)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown asset class: {request.kind}") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return _universe_response()
