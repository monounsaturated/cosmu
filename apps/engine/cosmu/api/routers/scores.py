# intent: the Scores cockpit — per-source + composite INDEX scores by category; inputs: none; outputs: ScoresResponse; invariants: no fabricated scores (no data → null/disconnected); no LLM on the scoring path.

from __future__ import annotations

from fastapi import APIRouter

from cosmu.api._shared import settings, store
from cosmu.api.models import ScoreCategory, ScoreSourceRow, ScoresResponse

router = APIRouter()


def _present_provider_keys() -> set[str]:
    """Which provider env keys are set on the engine (Railway). Drives the cockpit's grey/disabled state:
    a key-gated source with no key here renders disabled. Read straight off the typed settings."""
    present: set[str] = set()
    if settings.xai_api_key:
        present.add("XAI_API_KEY")
    if settings.lunarcrush_api_key:
        present.add("LUNARCRUSH_API_KEY")
    if settings.fred_api_key:
        present.add("FRED_API_KEY")
    if settings.polymarket_token:
        present.add("POLYMARKET_TOKEN")
    return present


@router.get("/scores", response_model=ScoresResponse)
def scores() -> ScoresResponse:
    """The SCORES COCKPIT — per-source + composite INDEX scores grouped by category (crypto · social ·
    macro · OSINT · metals/forex), each with freshness and a plain-language "what this means" review.

    Composite index = freshness × realized gate contribution, averaged over the sources that actually have
    data. HONEST: a category/source with no ingested data reports connected=False and index=null — never a
    fabricated score. A key-gated source whose key is not set on the engine shows disabled=True so the UI
    greys it out. Reviews are deterministic plain-language reads; no LLM on the gate/scoring/money path."""
    from cosmu.mind.scores import build_scores

    snap = build_scores(store, present_keys=_present_provider_keys())
    return ScoresResponse(
        as_of=snap.as_of,
        composite_index=snap.composite_index,
        composite_status=snap.composite_status,
        composite_review=snap.composite_review,
        categories=[
            ScoreCategory(
                key=c.key,
                label=c.label,
                index_score=c.index_score,
                status=c.status,
                freshness_label=c.freshness_label,
                connected=c.connected,
                live_sources=c.live_sources,
                total_sources=c.total_sources,
                review=c.review,
                sources=[
                    ScoreSourceRow(
                        source=s.source,
                        category=s.category,
                        features=s.features,
                        last_at=s.last_at,
                        freshness_label=s.freshness_label,
                        status=s.status,
                        trust_score=s.trust_score,
                        tier=s.tier,
                        hours_since=s.hours_since,
                        connected=s.connected,
                        key_required=s.key_required,
                        key_name=s.key_name,
                        key_present=s.key_present,
                        disabled=s.disabled,
                        review=s.review,
                    )
                    for s in c.sources
                ],
            )
            for c in snap.categories
        ],
    )
