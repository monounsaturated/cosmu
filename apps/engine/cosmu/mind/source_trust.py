# intent: compute a plain-language trust score for every registered data source. Inputs: the
# append-only alt_data store (point-in-time freshness) + gate_verdicts (realized contribution to
# gate-passed edge). Outputs: SourceTrustRow per source with freshness label, gate-pass count,
# a normalized trust score in [0, 1], and a plain-English summary. Invariants: HONEST — abstains
# (score = 0, status = "no data") when no data exists; never fabricates a contribution; read-only;
# offline-safe (graceful fallback on missing tables). No LLM on this path.

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from cosmu.config.feature_registry import FEATURE_REGISTRY

# Freshness buckets (hours since last `available_at`). Anything older than STALE_H is labelled stale.
FRESH_H = 8          # ≤ 8 h → "fresh"
RECENT_H = 48        # ≤ 48 h → "recent"
STALE_H = 7 * 24     # > 7 d → "stale"; everything in between is "aging"


@dataclass(frozen=True)
class SourceTrustRow:
    """Trust metadata for one data source.

    `source` is the registry source string (e.g. "alternative.me", "fred", "news").
    `features` lists the feature names served by this source.
    `last_at` is the latest `available_at` across all metrics for this source (ISO-8601, UTC, or None).
    `freshness_label` is plain-language freshness ("fresh N h", "recent N h", "aging N d", "stale", "no data").
    `gate_pass_count` is the number of gate-passed backtests that referenced any feature from this source.
    `trust_score` is a normalized [0, 1] composite (freshness component + realized gate contribution).
    `summary` is a one-liner in plain English for the UI ("Funding: fresh 4 h, high-signal; contributed to 3 gate passes").
    `status` is "fresh" | "recent" | "aging" | "stale" | "no data" (for badge colours).
    `tier` is "tier0" or "tier1" from the highest-confidence feature on this source.
    """

    source: str
    features: list[str]
    last_at: str | None
    freshness_label: str
    status: str  # "fresh" | "recent" | "aging" | "stale" | "no data"
    gate_pass_count: int
    trust_score: float  # [0, 1]
    summary: str
    tier: str = "tier1"
    hours_since: float | None = None


def _freshness(last_at: datetime | None, now: datetime) -> tuple[str, str, float | None]:
    """Return (freshness_label, status, hours_since) from the last availability timestamp."""
    if last_at is None:
        return "no data", "no data", None
    delta = now - last_at
    hours = delta.total_seconds() / 3600.0
    if hours <= FRESH_H:
        return f"fresh {hours:.0f} h", "fresh", hours
    if hours <= RECENT_H:
        return f"recent {hours:.0f} h", "recent", hours
    days = hours / 24.0
    if hours <= STALE_H:
        return f"aging {days:.0f} d", "aging", hours
    return f"stale {days:.0f} d", "stale", hours


def _trust_score(status: str, gate_pass_count: int) -> float:
    """Normalized trust score in [0, 1]: freshness × gate contribution.

    Freshness component: fresh=1.0, recent=0.7, aging=0.3, stale=0.1, no_data=0.
    Gate component: log-scaled so even 1 pass is meaningful; capped at 1.0 at ~20 passes.
    Combined: 0.6 × freshness + 0.4 × gate. Never fabricates — abstains at 0 with no data."""
    import math

    freshness_map = {"fresh": 1.0, "recent": 0.7, "aging": 0.3, "stale": 0.1, "no data": 0.0}
    f = freshness_map.get(status, 0.0)
    g = min(1.0, math.log1p(gate_pass_count) / math.log1p(20))
    return round(0.6 * f + 0.4 * g, 3)


def _summary(source: str, features: list[str], freshness_label: str, gate_pass_count: int, trust_score: float, tier: str) -> str:
    """Plain-English one-liner for the UI."""
    source_label = source.replace(".", " ").replace("_", " ").title()
    parts: list[str] = [f"{source_label}: {freshness_label}"]
    if gate_pass_count > 0:
        sig = "high-signal" if trust_score >= 0.7 else ("medium-signal" if trust_score >= 0.4 else "low-signal")
        parts.append(f"{sig}; contributed to {gate_pass_count} gate pass{'es' if gate_pass_count != 1 else ''}")
    else:
        parts.append("no gate contribution recorded yet")
    if tier == "tier1":
        parts.append("(tier 1, low-confidence until validated OOS)")
    return "; ".join(parts)


def _latest_per_source(store: Any) -> dict[str, datetime | None]:
    """Latest `available_at` per metric from the store, mapped to source strings in the registry."""
    try:
        rows = store.rows(
            "SELECT a.metric AS metric, MAX(a.available_at) AS last_at "
            "FROM alt_data a "
            "GROUP BY a.metric"
        )
    except Exception:  # noqa: BLE001 — table may not exist on a fresh store
        return {}
    metric_to_last: dict[str, datetime] = {}
    for r in rows:
        raw = r.get("last_at")
        if not raw:
            continue
        try:
            metric_to_last[r["metric"]] = datetime.fromisoformat(str(raw)).replace(tzinfo=UTC)
        except (ValueError, AttributeError):
            continue
    # Map metric → source(s) via the feature registry
    source_to_last: dict[str, datetime | None] = {}
    for feat in FEATURE_REGISTRY:
        if not feat.enabled:
            continue
        last = metric_to_last.get(feat.name)
        current = source_to_last.get(feat.source)
        if last is not None and (current is None or last > current):
            source_to_last[feat.source] = last
    return source_to_last


def _gate_pass_counts_per_source(store: Any) -> dict[str, int]:
    """Count gate-passed backtests per registry source (via the strategy_versions / backtests join).

    A feature contributes to its source's count when ANY strategy that used that feature's source
    passed the gate. We proxy via the `strategy_versions` spec JSON to avoid a schema dependency.
    Fallback: 0 for every source (no fabrication)."""
    # Approach: read all gate-passed backtests; for each, look up the spec's `features` list;
    # map each feature name to its source(s) in the registry; increment the counter.
    feature_to_source: dict[str, str] = {f.name: f.source for f in FEATURE_REGISTRY if f.enabled}
    counts: dict[str, int] = {}
    try:
        import json as _json
        rows = store.rows(
            "SELECT sv.spec FROM strategy_versions sv "
            "JOIN backtests b ON b.strategy_version_id = sv.id "
            "WHERE b.passed_gates = 1"
        )
    except Exception:  # noqa: BLE001
        return counts
    for r in rows:
        raw_spec = r.get("spec")
        if not raw_spec:
            continue
        try:
            spec = _json.loads(raw_spec) if isinstance(raw_spec, str) else raw_spec
        except (ValueError, TypeError):
            continue
        features_used = spec.get("features") or []
        seen_sources: set[str] = set()
        for feat_name in features_used:
            src = feature_to_source.get(feat_name)
            if src and src not in seen_sources:
                counts[src] = counts.get(src, 0) + 1
                seen_sources.add(src)
    return counts


def build_source_trust(store: Any) -> list[SourceTrustRow]:
    """Build the source trust scoreboard.

    For each distinct source in the feature registry, compute:
    - freshness (latest available_at from alt_data)
    - gate_pass_count (how many gate-passed backtests used any feature from this source)
    - trust_score (normalized composite)
    - plain-English summary

    Read-only and offline-safe: missing tables / empty store → all sources show "no data, trust=0".
    Never fabricates: a source with no data shows 'no data', never a fake freshness label."""
    now = datetime.now(UTC)
    source_to_last = _latest_per_source(store)
    gate_counts = _gate_pass_counts_per_source(store)

    # Group features by source, pick the best tier per source
    source_features: dict[str, list[str]] = {}
    source_tier: dict[str, str] = {}
    for feat in FEATURE_REGISTRY:
        if not feat.enabled:
            continue
        source_features.setdefault(feat.source, []).append(feat.name)
        # tier0 > tier1: keep the best tier
        existing = source_tier.get(feat.source, "tier1")
        if feat.tier == "tier0":
            source_tier[feat.source] = "tier0"
        elif existing != "tier0":
            source_tier[feat.source] = feat.tier

    rows: list[SourceTrustRow] = []
    for source, features in sorted(source_features.items()):
        last_at = source_to_last.get(source)
        freshness_label, status, hours_since = _freshness(last_at, now)
        gate_pass_count = gate_counts.get(source, 0)
        tier = source_tier.get(source, "tier1")
        score = _trust_score(status, gate_pass_count)
        summary = _summary(source, features, freshness_label, gate_pass_count, score, tier)
        rows.append(SourceTrustRow(
            source=source,
            features=sorted(features),
            last_at=last_at.isoformat() if last_at else None,
            freshness_label=freshness_label,
            status=status,
            gate_pass_count=gate_pass_count,
            trust_score=score,
            summary=summary,
            tier=tier,
            hours_since=hours_since,
        ))
    # Sort: fresh + high-trust first; no-data last
    rows.sort(key=lambda r: (-r.trust_score, r.source))
    return rows
