from __future__ import annotations

from pydantic import BaseModel

# ---- alpha-decay: edge half-life + live-vs-funded drift (master/drift; web consumes) ----


class DriftTrack(BaseModel):
    """One funded track's alpha-decay snapshot. `defund` is the anticipatory verdict (pull capital BEFORE P&L
    turns); `half_life` is the estimated periods for the realized edge to halve (null = not decaying); `z`/`cusum`
    measure how far live has drifted below the edge it was funded on (`reference`)."""

    version_id: str
    defund: bool
    reason: str
    half_life: float | None
    periods_to_zero: float | None
    realized_edge: float
    reference_edge: float
    reference: str
    z: float
    cusum: float
    n: int


class DriftResponse(BaseModel):
    tracks: list[DriftTrack]
