# intent: liveness probe; inputs: none; outputs: static ok payload; invariants: never touches the store.

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"ok": "true", "service": "cosmu-engine"}
