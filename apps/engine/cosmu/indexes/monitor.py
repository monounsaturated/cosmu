# intent: the deterministic health/reliability readout for an index — freshness, coverage, and ranking
# STABILITY — so the operator can trust an index before building strategies on it. inputs: a Store + IndexSpec
# + an injected clock; outputs: an IndexHealth (plain floats/labels the API maps to a contract); invariants:
# PURE + deterministic (no LLM, no randomness), honest (no points → 'never'/'untested', never a fabricated
# value), point-in-time (reads the stored series only). Reliability is a transparent function of the realized
# series — it never judges or funds anything.

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

from cosmu.data.altdata import AltDataPoint, PgAltDataStore
from cosmu.indexes.spec import INDEX_PROVIDER, IndexSpec
from cosmu.knowledge.store import Store

# Recency horizon for the stability stat (most recent N points). Policy constant.
_STABILITY_N = 14
# Reliability thresholds on the recent-value standard deviation (index values live in [-1, +1]).
_STABLE_MAX = 0.10
_MODERATE_MAX = 0.25
_MIN_POINTS = 3


@dataclass(frozen=True)
class IndexHealth:
    n_points: int
    latest_value: float | None
    latest_at: str | None
    staleness_hours: float | None
    freshness: str          # "fresh" | "stale" | "never"
    stability: float | None  # stdev of the recent values; lower = steadier
    reliability: str        # "stable" | "moderate" | "volatile" | "untested"
    transform_version: str


def _representative(store: Store, spec: IndexSpec) -> list[AltDataPoint]:
    """The single series to read freshness/stability off: the MARKET series for a market-wide index, else the
    per-date mean across the index's entity series (the same aggregation compute uses for a market view)."""
    alt = PgAltDataStore(store)
    if spec.market_wide:
        return alt.read_all(INDEX_PROVIDER, "MARKET", spec.metric)
    by_date: dict[datetime, list[float]] = defaultdict(list)
    for entity in spec.entities:
        for p in alt.read_all(INDEX_PROVIDER, entity, spec.metric):
            by_date[p.available_at].append(p.value)
    return [
        AltDataPoint(ts=d, available_at=d, value=sum(vals) / len(vals))
        for d, vals in sorted(by_date.items())
        if vals
    ]


def index_health(store: Store, spec: IndexSpec, *, now: datetime | None = None) -> IndexHealth:
    """Freshness (vs the index's own cadence), coverage, and ranking stability for one index. Deterministic;
    honest empties when the index hasn't computed yet."""
    now = now or datetime.now(tz=UTC)
    series = _representative(store, spec)
    if not series:
        return IndexHealth(
            n_points=0, latest_value=None, latest_at=None, staleness_hours=None,
            freshness="never", stability=None, reliability="untested",
            transform_version=spec.transform_version,
        )
    series.sort(key=lambda p: p.available_at)
    latest = series[-1]
    latest_at = latest.available_at
    if latest_at.tzinfo is None:
        latest_at = latest_at.replace(tzinfo=UTC)
    staleness_hours = max(0.0, (now - latest_at).total_seconds() / 3600.0)
    # Fresh while within ~2 cadences of the last point; else stale. Cadence is the index's own declared period.
    cadence_hours = max(spec.cadence_minutes / 60.0, 0.25)
    freshness = "fresh" if staleness_hours <= 2 * cadence_hours else "stale"

    recent = [p.value for p in series[-_STABILITY_N:]]
    stability = round(statistics.pstdev(recent), 6) if len(recent) >= 2 else None
    if len(series) < _MIN_POINTS or stability is None:
        reliability = "untested"
    elif stability <= _STABLE_MAX:
        reliability = "stable"
    elif stability <= _MODERATE_MAX:
        reliability = "moderate"
    else:
        reliability = "volatile"

    return IndexHealth(
        n_points=len(series),
        latest_value=round(latest.value, 6),
        latest_at=latest.available_at.isoformat(),
        staleness_hours=round(staleness_hours, 3),
        freshness=freshness,
        stability=stability,
        reliability=reliability,
        transform_version=spec.transform_version,
    )
