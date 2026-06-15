# intent: the RESEARCH read store — a union of PG-hot ∪ DuckLake-cold so a sweep/backtest sees the WHOLE history
# even after retention prunes aged rows out of Postgres. A pure swap (pg XOR lake) would silently lose either the
# hot 90d or the cold archive the instant a row moves across the boundary — a look-ahead / data-gap class that
# poisons the LOCKED gate. The money/UI paths NEVER use this (they read raw hot PG for sub-ms latency; a per-tick
# R2 read would be 100-800ms); the tiered reader is wired only behind alt_data_backend='tiered'. WRITES always go
# to the hot tier (PG) — the cold lake is fed only by the aged-out exporter. invariants: the seam dedup
# reproduces PgAltDataStore's revision winner EXACTLY — on an exact (ts, available_at) collision PG is
# authoritative; otherwise the latest available_at wins — so the union is tuple-identical to a single store
# holding all rows (pinned by tests/test_ducklake_cold_tier.py::test_tiered_union_equals_single_store).

from __future__ import annotations

from datetime import datetime
from typing import Any

from ._types import AltDataPoint


class TieredAltDataStore:
    """Compose a HOT store (PgAltDataStore — recent window, authoritative) and a COLD store (DuckLake — full
    archive) into one point-in-time read view. Same append/read_asof/read_all interface as the leaf stores."""

    def __init__(self, hot: Any, cold: Any) -> None:
        self.hot = hot
        self.cold = cold

    def append(self, provider: str, symbol: str, metric: str, points: list[AltDataPoint]) -> None:
        """Writes ALWAYS land in the hot tier (PG). The cold lake is fed exclusively by the aged-out exporter, so
        the tiered store never dual-writes."""
        self.hot.append(provider, symbol, metric, points)

    def read_asof(self, provider: str, symbol: str, metric: str, as_of: datetime) -> list[AltDataPoint]:
        """Latest-revision row per ts across BOTH tiers. Cold first, then hot overwrites on `available_at >=`
        (PG authoritative on a tie) — so the union picks the same PIT winner a single PG holding all rows would."""
        by_ts: dict[datetime, AltDataPoint] = {}
        for p in self.cold.read_asof(provider, symbol, metric, as_of):
            by_ts[p.ts] = p
        for p in self.hot.read_asof(provider, symbol, metric, as_of):
            ex = by_ts.get(p.ts)
            if ex is None or p.available_at >= ex.available_at:
                by_ts[p.ts] = p
        return sorted(by_ts.values(), key=lambda p: p.ts)

    def read_all(self, provider: str, symbol: str, metric: str) -> list[AltDataPoint]:
        """Full revision history across both tiers, deduped on exact (ts, available_at) with PG authoritative —
        same ordering (available_at, ts) as PgAltDataStore.read_all, so the per-bar as-of join collapses it
        identically."""
        by_key: dict[tuple[datetime, datetime], AltDataPoint] = {}
        for p in self.cold.read_all(provider, symbol, metric):
            by_key[(p.ts, p.available_at)] = p
        for p in self.hot.read_all(provider, symbol, metric):
            by_key[(p.ts, p.available_at)] = p  # PG wins an exact (ts, available_at) collision
        return sorted(by_key.values(), key=lambda p: (p.available_at, p.ts))
