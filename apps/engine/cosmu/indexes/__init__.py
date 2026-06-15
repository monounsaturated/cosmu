# intent: the INDEX subsystem — operator-defined, deterministically-scored, point-in-time composite series that
# strategies later key off. Public surface: the spec, the registry (define/list/get), the compute pipeline
# (text + social, reusing the standardize grid + authority scorer), the health/stability monitor, and the
# strategy-feature routing seam. invariants: deterministic scoring (stable ranking), PIT storage, LLM-at-ingest
# only, honest empties — an index is data plumbing, never a funder.

from __future__ import annotations

from cosmu.indexes.compute import (  # noqa: F401
    compute_social_point,
    compute_text_point,
    read_index_series,
    rubric_from_spec,
    store_index_points,
)
from cosmu.indexes.monitor import IndexHealth, index_health  # noqa: F401
from cosmu.indexes.registry import (  # noqa: F401
    active_indexes,
    get_index,
    indexes_available,
    list_indexes,
    register_index,
)
from cosmu.indexes.routing import index_routes, store_provider_with_indexes  # noqa: F401
from cosmu.indexes.spec import INDEX_PROVIDER, INDEX_TRANSFORM_VERSION, IndexSpec  # noqa: F401

__all__ = [
    "INDEX_PROVIDER",
    "INDEX_TRANSFORM_VERSION",
    "IndexHealth",
    "IndexSpec",
    "active_indexes",
    "compute_social_point",
    "compute_text_point",
    "get_index",
    "rubric_from_spec",
    "index_health",
    "index_routes",
    "indexes_available",
    "list_indexes",
    "read_index_series",
    "register_index",
    "store_index_points",
    "store_provider_with_indexes",
]
