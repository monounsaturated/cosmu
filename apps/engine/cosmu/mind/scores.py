# intent: compose the SCORES COCKPIT — per-source + composite INDEX scores grouped by category
# (crypto · social · macro · OSINT · metals/forex). Inputs: the source-trust scoreboard (freshness ×
# realized gate contribution) + which provider keys are present in the engine env. Outputs: a category
# tree with an index in [0, 1], freshness, a plain-language "what this means" review, and per-source
# rows that carry a key-gating flag so the UI can grey out a source whose key is not set. Invariants:
# HONEST — a category/source with no ingested data reports connected=False and NEVER a fabricated score;
# a key-gated source with no key shows disabled=True; reviews are DETERMINISTIC plain-language reads
# derived from the data (LLM-optional narration, NEVER on the gate/scoring/money path); read-only.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cosmu.mind.source_trust import SourceTrustRow, build_source_trust

# ── Category taxonomy ────────────────────────────────────────────────────────
# Each registry source string maps to exactly one cockpit category. Unknown sources fall back to
# "macro" (the broad cross-asset bucket). `metals_forex` is declared but currently has no dedicated
# feed wired (DXY rolls up under macro/FRED) — it renders as an honest offline category, never faked.

CATEGORY_ORDER: tuple[str, ...] = ("crypto", "social", "macro", "osint", "metals_forex")

CATEGORY_LABELS: dict[str, str] = {
    "crypto": "Crypto",
    "social": "Social",
    "macro": "Macro",
    "osint": "OSINT",
    "metals_forex": "Metals / Forex",
}

SOURCE_CATEGORY: dict[str, str] = {
    # crypto-native price / derivatives / on-chain / news
    "ccxt": "crypto",
    "alternative.me": "crypto",
    "defillama": "crypto",
    "exchange": "crypto",
    "coinglass": "crypto",
    "parquet_bars": "crypto",
    "news_headlines": "crypto",
    "news": "crypto",
    # social / crowd
    "reddit": "social",
    "lunarcrush": "social",
    "xai": "social",
    # macro / cross-asset / positioning / odds / fundamentals
    "fred": "macro",
    "fred/cboe": "macro",
    "cboe": "macro",
    "cftc": "macro",
    "polymarket": "macro",
    "polymarket_clob": "macro",
    "sec_edgar": "macro",
    "fundamentals_vendor": "macro",
    # OSINT (best-effort, low-confidence)
    "opensky": "osint",
}

# ── Key-gating ───────────────────────────────────────────────────────────────
# A source that needs a provider key to return data. The env var NAME is what the engine reads on
# Railway; the UI greys the source out (disabled=True) when that key is absent. Keyless free providers
# are omitted here (they are never disabled). Polymarket needs a market token (not a secret) to be live.

SOURCE_KEY: dict[str, str] = {
    "xai": "XAI_API_KEY",
    "lunarcrush": "LUNARCRUSH_API_KEY",
    "fred": "FRED_API_KEY",
    "fred/cboe": "FRED_API_KEY",
    "polymarket": "POLYMARKET_TOKEN",
    "polymarket_clob": "POLYMARKET_TOKEN",
}


@dataclass(frozen=True)
class ScoreSourceRow:
    """One source inside a category. `connected` is True iff data has been ingested (status != no data).
    `key_required`/`key_present` describe the env-key gate; `disabled` = required AND absent (grey it out)."""

    source: str
    category: str
    features: list[str]
    last_at: str | None
    freshness_label: str
    status: str  # "fresh" | "recent" | "aging" | "stale" | "no data"
    trust_score: float
    tier: str
    hours_since: float | None
    connected: bool
    key_required: bool
    key_name: str | None
    key_present: bool
    disabled: bool
    review: str


@dataclass(frozen=True)
class ScoreCategory:
    """A cockpit category with its composite INDEX over the sources that actually have data."""

    key: str
    label: str
    index_score: float | None  # [0, 1] mean trust over live sources; None when nothing live
    status: str  # best source status, or "offline" when no source has data
    freshness_label: str
    connected: bool
    live_sources: int
    total_sources: int
    review: str
    sources: list[ScoreSourceRow] = field(default_factory=list)


@dataclass(frozen=True)
class ScoresSnapshot:
    as_of: str
    composite_index: float | None
    composite_status: str
    composite_review: str
    categories: list[ScoreCategory]


def _grade(score: float | None) -> str:
    if score is None:
        return "offline"
    if score >= 0.7:
        return "strong"
    if score >= 0.4:
        return "moderate"
    if score > 0.0:
        return "thin"
    return "offline"


def _source_review(row: SourceTrustRow, *, disabled: bool, key_name: str | None) -> str:
    """Plain-language one-liner for a source. Deterministic; honest about a missing key or no data."""
    if disabled:
        return f"Disabled — {key_name} is not set on the engine. Add the key on Railway to start ingesting this source."
    return row.summary


def _category_review(label: str, index: float | None, live: int, total: int, freshest: ScoreSourceRow | None) -> str:
    if total == 0:
        return f"No {label.lower()} feed wired yet — nothing to score."
    if index is None:
        return f"{label}: {total} source{'s' if total != 1 else ''} registered, none live yet. Honest offline — no fabricated score."
    grade = _grade(index)
    fresh = f" Freshest {freshest.source} ({freshest.freshness_label})." if freshest else ""
    return f"{label}: {live}/{total} sources live, composite {index:.2f} — {grade} read.{fresh}"


def _composite_review(index: float | None, cats_live: int, cats_total: int) -> str:
    if index is None:
        return "No live data in any category yet — the composite index is offline until a source ingests. Nothing fabricated."
    grade = _grade(index)
    return f"{cats_live}/{cats_total} categories live · composite INDEX {index:.2f} — {grade}. Freshness × realized gate contribution, net of any source with no data."


def build_scores(store: Any, *, present_keys: set[str] | None = None) -> ScoresSnapshot:
    """Build the scores cockpit from the source-trust scoreboard + the set of env-key NAMES present.

    Read-only and offline-safe: an empty store yields every category offline (connected=False, index=None),
    never a fabricated number. A key-gated source whose key is absent is marked disabled (greyed in the UI)."""
    present = present_keys or set()
    with store.reading():
        trust_rows = build_source_trust(store)
    by_source = {r.source: r for r in trust_rows}
    from cosmu.knowledge.store import utcnow

    categories: list[ScoreCategory] = []
    live_indices: list[float] = []

    for cat_key in CATEGORY_ORDER:
        label = CATEGORY_LABELS[cat_key]
        rows: list[ScoreSourceRow] = []
        for src, r in sorted(by_source.items()):
            if SOURCE_CATEGORY.get(src, "macro") != cat_key:
                continue
            key_name = SOURCE_KEY.get(src)
            key_required = key_name is not None
            key_present = key_name in present if key_name else True
            connected = r.status != "no data"
            disabled = bool(key_required and not key_present)
            rows.append(
                ScoreSourceRow(
                    source=src,
                    category=cat_key,
                    features=list(r.features),
                    last_at=r.last_at,
                    freshness_label=r.freshness_label,
                    status=r.status,
                    trust_score=r.trust_score,
                    tier=r.tier,
                    hours_since=r.hours_since,
                    connected=connected,
                    key_required=key_required,
                    key_name=key_name,
                    key_present=key_present,
                    disabled=disabled,
                    review=_source_review(r, disabled=disabled, key_name=key_name),
                )
            )

        # Index over sources that have data AND are not disabled by a missing key.
        scored = [s for s in rows if s.connected and not s.disabled]
        index = round(sum(s.trust_score for s in scored) / len(scored), 3) if scored else None
        # Best (freshest) live source drives the category status + headline freshness.
        freshest = min(
            (s for s in scored if s.hours_since is not None),
            key=lambda s: s.hours_since,  # type: ignore[arg-type,return-value]
            default=None,
        )
        status = freshest.status if freshest else ("offline" if not rows else "no data")
        freshness_label = freshest.freshness_label if freshest else "no data"
        connected = bool(scored)
        if index is not None:
            live_indices.append(index)
        categories.append(
            ScoreCategory(
                key=cat_key,
                label=label,
                index_score=index,
                status=status,
                freshness_label=freshness_label,
                connected=connected,
                live_sources=len(scored),
                total_sources=len(rows),
                review=_category_review(label, index, len(scored), len(rows), freshest),
                sources=rows,
            )
        )

    composite = round(sum(live_indices) / len(live_indices), 3) if live_indices else None
    cats_live = len(live_indices)
    composite_status = _grade(composite) if composite is not None else "offline"
    return ScoresSnapshot(
        as_of=utcnow(),
        composite_index=composite,
        composite_status=composite_status,
        composite_review=_composite_review(composite, cats_live, len(CATEGORY_ORDER)),
        categories=categories,
    )


__all__ = [
    "CATEGORY_LABELS",
    "CATEGORY_ORDER",
    "ScoreCategory",
    "ScoreSourceRow",
    "ScoresSnapshot",
    "SOURCE_CATEGORY",
    "SOURCE_KEY",
    "build_scores",
]
