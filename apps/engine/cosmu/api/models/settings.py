from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

# ---- Settings → Keys: a read-only inventory of which provider keys are configured. ----


class SettingsKeyRow(BaseModel):
    """One configurable secret/key, surfaced to the operator so they can see what's plugged vs missing.

    SECURITY: `configured` is a boolean only — the VALUE is NEVER read, returned, or logged. `requirement`
    is one of "required" (the app needs it to do its core job), "optional" (unlocks a paid/extra path), or
    "live-only" (only needed to move real money). `cost` is "free" or "paid". `where` tells the operator
    which env var to set on the engine."""

    key: str
    env_var: str
    configured: bool
    unlocks: str
    requirement: Literal["required", "optional", "live-only"]
    cost: Literal["free", "paid"]
    where: str


class SettingsKeysResponse(BaseModel):
    """Read-only key inventory for the Settings → Keys page. Values are never exposed — only whether each
    key is configured on the engine and what it unlocks. Safe to render in the browser."""

    rows: list[SettingsKeyRow]
