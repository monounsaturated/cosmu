# intent: expose the engine's typed control-plane API; inputs: HTTP requests; outputs: Pydantic responses/OpenAPI; invariants: mutating money routes are gated and live remains off by default.

from __future__ import annotations

import hmac
import sys as _sys
import types as _types

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from cosmu.api import _shared as _shared_mod
from cosmu.api._lifespan import lifespan

# Pure helpers live in cosmu.api._shared; re-exported here so `from cosmu.api.app import _metric / _json /
# ensure_recommendations` keeps working. The mutable singletons (store, settings) and _alt_store are served
# dynamically by the back-compat module proxy installed at the bottom of this file — see _CompatModule.
from cosmu.api._shared import (  # noqa: F401 — re-exported for backwards-compatible imports
    _json,
    _metric,
    ensure_recommendations,
)
from cosmu.api.routers import (
    autonomy,
    blocks,
    console,
    correlations,
    costs,
    events,
    evolution,
    explorer,
    health,
    indexes,
    intelligence,
    lab,
    leaderboard,
    live,
    market,
    memory,
    mind,
    overview,
    population,
    readiness,
    realtime,
    recommendations,
    research,
    scores,
    skills,
    spine,
    strategies,
    strategy,
    toggle,
    universe,
    verdicts,
)
from cosmu.api.routers import (
    settings as settings_router,
)

app = FastAPI(title="Cosmu Engine", version="0.1.0", lifespan=lifespan)

# Private single-user app behind API_SECRET_KEY — allow all origins so Vercel preview
# deploys (which get new URLs) work without updating CORS_EXTRA_ORIGINS every time.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# API AUTH — the shared-secret gate docs/KEYS.md documents. When API_SECRET_KEY is set (production), every
# route except /health (the platform healthcheck) requires a matching `x-api-key` header — the Next.js proxy
# injects it server-side, so the secret never reaches a browser and nobody else can drive the control plane
# (toggle live, launch, override forward tests). Unset (local dev / tests) → the gate is a no-op, exactly as
# documented. Reads settings through the _shared seam at REQUEST time so the test-injection path (writes to
# cosmu.api.app.settings fan out below) governs auth too. OPTIONS passes: CORS preflights carry no headers.
_AUTH_EXEMPT_PATHS = frozenset({"/health"})


@app.middleware("http")
async def _require_api_key(request: Request, call_next):
    secret = getattr(_shared_mod.settings, "api_secret_key", None)
    if secret and request.method != "OPTIONS" and request.url.path not in _AUTH_EXEMPT_PATHS:
        presented = request.headers.get("x-api-key") or ""
        # Compare as BYTES: hmac.compare_digest raises TypeError on non-ASCII str (e.g. a key with a
        # smart-quote / stray byte), which would surface as a confusing 500 instead of a clean 401.
        if not hmac.compare_digest(presented.encode("utf-8"), secret.encode("utf-8")):
            return JSONResponse(status_code=401, content={"detail": "missing or invalid x-api-key"})
    return await call_next(request)

# One APIRouter per URL prefix. Order is irrelevant to behavior (no overlapping paths) and to the generated
# OpenAPI schema (contracts are emitted with sorted keys), but grouped here for readability.
for _module in (
    health,
    spine,
    evolution,
    population,
    strategy,
    lab,
    overview,
    leaderboard,
    strategies,
    explorer,
    console,
    recommendations,
    autonomy,
    toggle,
    live,
    market,
    universe,
    research,
    mind,
    scores,
    settings_router,
    skills,
    memory,
    costs,
    events,
    intelligence,
    verdicts,
    correlations,
    realtime,
    blocks,
    readiness,
    indexes,
):
    app.include_router(_module.router)


# ---------------------------------------------------------------------------
# Back-compat injection seam (zero behavior change after the route split).
# Before app.py was split into routers, callers and tests monkeypatched
# `cosmu.api.app.store` / `.settings` (and `._alt_store`) to point the running
# app at a test Store/Settings or a fixture alt-data store. Those singletons now
# live in cosmu.api._shared (store, settings) and cosmu.api.routers.research
# (_alt_store), and each router value-imported them at module load. To preserve
# that exact seam, reads of these names proxy to their canonical home and writes
# FAN OUT to every module that holds a reference — so a single patch on this
# module reaches every route, exactly as when they shared one module global.
# ---------------------------------------------------------------------------
# Every module that did `from cosmu.api._shared import store, settings` (plus the
# canonical _shared) — a write to app.store/app.settings must update all of them.
_INJECTABLE_MODULES = (
    _shared_mod, autonomy, console, correlations, costs, events, evolution, explorer, health,
    indexes, intelligence, lab, leaderboard, live, memory, mind, overview, population,
    recommendations, research, scores, settings_router, skills, spine,
    strategies, strategy, toggle, universe, verdicts,
)


class _CompatModule(_types.ModuleType):
    def __getattr__(self, name):  # only consulted when normal lookup fails
        if name in ("store", "settings"):
            return getattr(_shared_mod, name)
        if name == "_alt_store":
            return research._alt_store
        raise AttributeError(f"module {self.__name__!r} has no attribute {name!r}")

    def __setattr__(self, name, value):
        if name in ("store", "settings"):
            for _m in _INJECTABLE_MODULES:
                if hasattr(_m, name):
                    setattr(_m, name, value)
            return
        if name == "_alt_store":
            research._alt_store = value
            return
        super().__setattr__(name, value)


_sys.modules[__name__].__class__ = _CompatModule


if __name__ == "__main__":
    import os

    # Bind for BOTH local dev and production (Railway/any PaaS injects $PORT). Default 0.0.0.0 so the container
    # is reachable; reload only in local/dev. Production (APP_ENV=production) → no reload, real $PORT.
    _port = int(os.environ.get("PORT", "8000"))
    _host = os.environ.get("HOST", "0.0.0.0")
    _reload = os.environ.get("APP_ENV", "dev").strip().lower() in ("dev", "local")
    import uvicorn

    uvicorn.run("cosmu.api.app:app", host=_host, port=_port, reload=_reload)
