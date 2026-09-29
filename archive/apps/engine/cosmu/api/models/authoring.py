from __future__ import annotations

from typing import Any

from pydantic import BaseModel

# ---- chat strategy authoring ----


class AuthorRequest(BaseModel):
    brief: str
    features: list[str] | None = None
    venues: list[str] | None = None


class AuthorResponse(BaseModel):
    name: str
    rationale: str
    base_template: str
    features: list[str]
    data_sources: list[str]
    venues: list[str]
    valid: bool
    issues: list[str]
    requires_approval: bool
    guardrails: list[str]
    notes: list[str]
    spec: dict[str, Any]


class AuthorRunRequest(BaseModel):
    brief: str
    features: list[str] | None = None
    venues: list[str] | None = None
    cohort_size: int | None = None
