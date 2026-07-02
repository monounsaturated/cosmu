# intent: liveness + fleet-freshness probes; inputs: none (/health) / store read (/health/fleet); outputs:
# static ok payload / heartbeat.check() dict + stale flag; invariants: /health never touches the store;
# /health/fleet ALWAYS returns HTTP 200 (even on a store read error) so an external prober can distinguish
# "engine up but fleet stale" (200 + stale:true) from "engine down" (conn refused / 5xx). Both are auth-exempt.

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

# The shared singletons (patched by the back-compat injection seam in cosmu.api.app — health is in
# _INJECTABLE_MODULES). Value-imported so a test that monkeypatches app.store/app.settings reaches here.
from cosmu.api._shared import settings, store  # noqa: F401 — settings kept for the injection seam

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"ok": "true", "service": "cosmu-engine"}


@router.get("/health/fleet")
def health_fleet() -> dict[str, Any]:
    """External dead-man probe target (curled by the off-Modal .github fleet-watchdog cron). Returns
    heartbeat.check(store)'s dict plus a top-level `stale: bool` and the age of the newest watchdog_pulse
    (the heartbeat's own aliveness beacon). ALWAYS HTTP 200 — a store read error yields {ok:false, stale:true,
    error:...} at 200 so the prober reads "engine up but fleet stale" rather than confusing it with the engine
    being down (which surfaces as a connection refusal / 5xx). Auth-exempt (in _AUTH_EXEMPT_PATHS) so the
    external prober can reach it without the x-api-key the browser proxy injects."""
    from cosmu.ops.heartbeat import check

    try:
        report = check(store)
        report["stale"] = not report.get("ok", False)
        report["watchdog_pulse_age_h"] = report.get("ages_h", {}).get("watchdog")
        return report
    except Exception as exc:  # noqa: BLE001 — a store/DB blip must read as STALE (engine up), never a 5xx
        return {"ok": False, "stale": True, "watchdog_pulse_age_h": None, "error": str(exc)}
