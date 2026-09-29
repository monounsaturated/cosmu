from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

# ---- Verdict ledger: parsed phase0-*-verdict.md research history. ----


class VerdictRow(BaseModel):
    """One parsed phase0 verdict file — the research history made scannable."""

    slug: str
    thesis: str
    id: str
    date: str
    status: Literal["PASS", "FAIL", "INSUFFICIENT-DATA", "DATA-BLOCKED"]
    deflated_sharpe: float | None = None
    trades: int | None = None
    cost_ratio: float | None = None
    reason: str


class VerdictsResponse(BaseModel):
    rows: list[VerdictRow]
