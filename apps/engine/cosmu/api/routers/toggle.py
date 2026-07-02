# intent: the global live on/off toggle; inputs: ToggleRequest; outputs: ToggleResponse; invariants: enabling live requires confirm=true; flipping the toggle never funds — sim fills only.

from __future__ import annotations

from fastapi import APIRouter

from cosmu.api._shared import settings, store
from cosmu.api.models import ToggleRequest, ToggleResponse
from cosmu.knowledge.store import utcnow

router = APIRouter()


@router.post("/toggle/live", response_model=ToggleResponse)
def toggle_live(request: ToggleRequest) -> ToggleResponse:
    if request.enabled and not request.confirm:
        # Hardened: enabling live requires explicit confirm. We do NOT mutate state — the UI must re-submit
        # with confirm=true. Returning requires_confirm keeps the contract honest instead of a 400 surprise.
        return ToggleResponse(
            enabled=False,
            promoted=[],
            caps={"per_strategy": float(settings.live.per_strategy_live_cap), "global": float(settings.live.global_live_cap)},
            requires_confirm=True,
            reason="enabling live requires confirm=true",
        )
    if request.enabled:
        # WEIGHT-ON-WHEELS INTERLOCK: a LATCHED circuit-breaker means a hard aggregate breach already disarmed
        # live + liquidated the book. Re-enabling live is IMPOSSIBLE until a human explicitly re-arms the breaker
        # (POST /ops/breaker/rearm) — checked BEFORE the UPDATE so a latched breaker can never be flipped back on
        # by this route (the aviation model: you can't re-close a tripped breaker just by re-flipping the switch).
        from cosmu.ops import breaker

        if breaker.is_latched(store):
            return ToggleResponse(
                enabled=False,
                promoted=[],
                caps={"per_strategy": float(settings.live.per_strategy_live_cap), "global": float(settings.live.global_live_cap)},
                requires_confirm=False,
                reason="breaker latched — POST /ops/breaker/rearm first",
            )
    store.rows("UPDATE live_toggle SET enabled = ?, enabled_at = ?, enabled_by = ? WHERE id = 'global'", (int(request.enabled), utcnow(), "local"))
    store.append_event(actor="human", kind="live_toggle_changed", ref_type="live_toggle", ref_id="global", payload={"enabled": request.enabled})
    return ToggleResponse(
        enabled=request.enabled,
        promoted=[] if not request.enabled else ["simulation-only"],
        caps={"per_strategy": float(settings.live.per_strategy_live_cap), "global": float(settings.live.global_live_cap)},
        requires_confirm=False,
    )
