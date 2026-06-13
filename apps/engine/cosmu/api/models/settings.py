from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

# ---- Settings → Keys: a read-only inventory of which provider keys are configured. ----


class KeyPresence(BaseModel):
    """Whether a key is present at each LOCATION, checked INDEPENDENTLY. A running engine can only observe its
    OWN env (the process it's in), so exactly one side is a real bool and the other is `None` (not False) — the
    honest "unverified" state. `local` = present in the laptop/.env.local env; `host` = present on the deployed
    host (Railway). The v18 Keys page colours the host name green/red/grey from `host`, and never fabricates the
    side it cannot see."""

    local: bool | None = None
    host: bool | None = None


class SettingsKeyRow(BaseModel):
    """One configurable secret/key (ONE row PER env var), surfaced so the operator sees what's plugged vs missing.

    SECURITY: presence is a boolean only — the VALUE is NEVER read, returned, or logged. `requirement` is
    "required" (core job), "optional" (paid/extra path), or "live-only" (only to move real money). `cost` is
    "free"/"paid".

    v18 fields: `name` (the bare env var, the index key), `service` (provider/group label), `description` (the
    short "what it unlocks" copy), `host` (which deploy host the var belongs on), `present` (per-location
    presence), `status` (connected | unverified | missing | unset — the status dot). The legacy `key`/`env_var`/
    `unlocks`/`where`/`configured` fields are kept (additive) for back-compat."""

    # legacy (kept for back-compat)
    key: str
    env_var: str
    configured: bool
    unlocks: str
    where: str
    # v18 per-env-var index
    name: str
    service: str
    description: str
    host: Literal["railway", "vercel", "local", "none"] = "railway"
    present: KeyPresence = KeyPresence()
    status: Literal["connected", "unverified", "missing", "unset"] = "unset"
    requirement: Literal["required", "optional", "live-only"]
    cost: Literal["free", "paid"]


class SettingsKeysResponse(BaseModel):
    """Read-only key inventory for the Keys page. Values are never exposed — only whether each key is
    configured (per location) and what it unlocks. Safe to render in the browser."""

    rows: list[SettingsKeyRow]
