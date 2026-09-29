# intent: read/define API over the INDEX registry — list every index with its current value + health, one
# index's detail (definition + series + strategies built on it), and define a new index. inputs: none / an
# index_id / an IndexSpec body; outputs: IndexesResponse / IndexDetail / IndexDefineResponse; invariants:
# fail-open `available=False` until the 2026-06-15 migration is applied (honest "not active yet", never a
# crash); defining an index only registers a DEFINITION — it never computes, funds, or fires anything (the
# compute pass / Modal job populates the series). Read-only except POST, which is gated by the app's x-api-key.

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter

from cosmu.api._shared import store
from cosmu.api.models import (
    IndexCard,
    IndexDefineResponse,
    IndexDetail,
    IndexesResponse,
    IndexHealthModel,
    IndexSeries,
    IndexSeriesPoint,
    IndexSpec,
    IndexStrategyRef,
)
from cosmu.indexes.compute import read_index_series
from cosmu.indexes.monitor import index_health
from cosmu.indexes.registry import get_index, indexes_available, list_indexes, register_index

router = APIRouter()


def _strategies_using(metric: str) -> list[dict[str, Any]]:
    """Versions whose spec references this index's metric (idx_<id>) — the 'strategies built on this index'
    list. Best-effort substring match on the stored spec JSON; fail-open to [] (the metric name is distinctive,
    and until strategies-on-indexes is wired this is correctly empty)."""
    try:
        return store.rows(
            "SELECT sv.id AS version_id, s.name, sv.status FROM strategy_versions sv "
            "JOIN strategies s ON s.id = sv.strategy_id WHERE sv.spec LIKE ? "
            "ORDER BY sv.created_at DESC LIMIT 50",
            (f"%{metric}%",),
        )
    except Exception:  # noqa: BLE001 — observational; never break the index read
        return []


def _card(spec: IndexSpec) -> IndexCard:
    health = IndexHealthModel(**asdict(index_health(store, spec)))
    using = _strategies_using(spec.metric)
    return IndexCard(
        id=spec.id,
        name=spec.name,
        rationale=spec.rationale,
        kind=spec.kind,
        definition=dict(spec.definition),
        status=spec.status,
        market_wide=spec.market_wide,
        metric=spec.metric,
        entities=list(spec.entities),
        cadence_minutes=spec.cadence_minutes,
        created_at=spec.created_at,
        health=health,
        n_strategies_using=len(using),
    )


@router.get("/indexes", response_model=IndexesResponse)
def indexes() -> IndexesResponse:
    if not indexes_available(store):
        return IndexesResponse(available=False, indexes=[])
    return IndexesResponse(available=True, indexes=[_card(s) for s in list_indexes(store)])


@router.get("/indexes/{index_id}", response_model=IndexDetail)
def index_detail(index_id: str) -> IndexDetail:
    if not indexes_available(store):
        return IndexDetail(available=False, index=None, series=[], strategies_using=[])
    spec = get_index(store, index_id)
    if spec is None:
        return IndexDetail(available=True, index=None, series=[], strategies_using=[])
    series: list[IndexSeries] = []
    for sym in spec.symbols():
        pts = read_index_series(store, spec, sym)
        if pts:
            series.append(
                IndexSeries(
                    symbol=sym,
                    points=[IndexSeriesPoint(ts=p.available_at.isoformat(), value=round(p.value, 6)) for p in pts[-500:]],
                )
            )
    using = [
        IndexStrategyRef(version_id=r["version_id"], name=r["name"], status=r.get("status") or "")
        for r in _strategies_using(spec.metric)
    ]
    return IndexDetail(available=True, index=_card(spec), series=series, strategies_using=using)


@router.post("/indexes", response_model=IndexDefineResponse)
def define_index(spec: IndexSpec) -> IndexDefineResponse:
    """Register (or update by id) an index DEFINITION. Validation of the kind-specific definition happens in
    IndexSpec (FastAPI returns 422 on a bad shape). This never computes the series — the compute pass does."""
    if not indexes_available(store):
        return IndexDefineResponse(
            ok=False, available=False, index=None,
            error="index registry not active — apply the 2026-06-15_indexes migration on the store",
        )
    saved = register_index(store, spec)
    return IndexDefineResponse(ok=True, available=True, index=_card(saved))
