# intent: the operator OPS control-plane — the MANUAL capital-guard kill-switch (mass / per-combo forced
# close); inputs: a confirmed KillswitchRequest; outputs: what the forced reduce-only pass closed; invariants:
# requires confirm=true (two-click safety); every close is REDUCE-ONLY (only ever shrinks exposure, never opens);
# sim-closes until a venue is armed; same x-api-key auth as every route; a no-op with nothing funded in scope.

from __future__ import annotations

from fastapi import APIRouter

from cosmu.api._shared import (  # noqa: F401 — settings kept for the back-compat injection seam
    settings,
    store,
)
from cosmu.api.models import KillswitchRequest, KillswitchResponse

router = APIRouter()


@router.post("/ops/killswitch", response_model=KillswitchResponse)
def ops_killswitch(request: KillswitchRequest) -> KillswitchResponse:
    """The MANUAL capital-guard kill-switch — the operator's "stop everything now" backstop. Force-closes (a
    threshold-FREE reduce-only liquidation of the full held qty) every funded holding in scope, routed through
    the SAME one order path the automatic capital guard uses: a real reduce-only order on an ARMED venue, a
    deterministic sim-close otherwise (so it degrades to a no-op while live is off).

    ONE route, two callers: the front's kill button POSTs it, and Claude Code `curl`s it — same shape, same
    x-api-key auth as every route. Two scopes:
      • scope='all'  (the GLOBAL mass-kill) closes EVERY funded holding;
      • scope='combo' (with version_id = the combo/track id) closes ONLY that one cell — siblings untouched.

    Safety: `confirm` MUST be true (two-click — an accidental call never flattens the book); a reduce-only close
    is gauntlet-EXEMPT from caps/kill/regime (closing IS the safety move) so a genuine stop always routes; it can
    only ever REDUCE exposure (never opens/grows). Audited per-leg as `capital_guard_action` (actor='human') by
    the guard, plus an `ops_killswitch` summary event here. Idempotent + a clean no-op when nothing in scope is
    funded/held (triggered=true, closed=0)."""
    from cosmu.ops import capital_guard

    if not request.confirm:
        # Two-click safety: never flatten the book on an unconfirmed call. No state touched.
        return KillswitchResponse(
            triggered=False, scope=request.scope, version_id=request.version_id,
            reason="kill-switch requires confirm=true",
        )

    report = capital_guard.kill(store, scope=request.scope, version_id=request.version_id)

    store.append_event(
        actor="human",
        kind="ops_killswitch",
        ref_type="capital_guard",
        ref_id=request.version_id or "global",
        payload={
            "scope": request.scope,
            "version_id": request.version_id,
            "evaluated": report.evaluated,
            "closed": report.protected,
        },
    )
    return KillswitchResponse(
        triggered=True,
        scope=request.scope,
        version_id=request.version_id,
        evaluated=report.evaluated,
        closed=report.protected,
        actions=report.actions,
    )
