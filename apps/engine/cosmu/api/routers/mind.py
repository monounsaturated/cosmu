# intent: the Mind — the agent's standardized self-knowledge (KNOWS/THINKS/LEARNED) + source-trust + news intel; inputs: none/symbol; outputs: typed snapshots; invariants: reasons only, never funds or fires an order; abstains rather than fabricates.

from __future__ import annotations

from fastapi import APIRouter

from cosmu.api._shared import _brain_reference_bars, settings, store
from cosmu.api.models import (
    MindResponse,
    NewsEventRow,
    NewsIntelResponse,
    SourceTrustResponse,
    SourceTrustRow,
)

router = APIRouter()


@router.get("/mind", response_model=MindResponse)
def mind() -> MindResponse:
    """The Mind — the agent's standardized self-knowledge in one read: what it KNOWS (point-in-time data sources
    + freshness), how it THINKS (the analyst panel + the debate's consensus), and what it has LEARNED (memory,
    the ML survival model, regime coverage, gate efficiency). The panel reads REAL ingested signals only — a
    perspective with no data abstains, never fabricates. RAILGUARD: this reasons; it never funds or fires an
    order — the deterministic gate alone disposes."""
    from cosmu.mind import build_mind, judge_from_settings

    # LLM-as-judge is OPT-IN (MIND_JUDGE_ENABLED): off → the committee is fully deterministic (default, $0,
    # fast). On + a key → pillars WITH data are rubric-scored by the model; the consensus stays deterministic
    # math and the gate alone disposes. The seam degrades gracefully, so enabling it can never stall the read.
    judge = judge_from_settings(settings) if settings.mind_judge_enabled else None
    return MindResponse(**build_mind(store, reference_bars=_brain_reference_bars(), judge=judge))


@router.get("/mind/source-trust", response_model=SourceTrustResponse)
def mind_source_trust() -> SourceTrustResponse:
    """Source-trust scoreboard — for every registered data source, a plain-language trust score.

    Trust = freshness × realized gate contribution (how many gate-passed backtests used this source).
    Honest: a source with no data ingested shows trust_score=0, status="no data" — never fabricates.
    Read-only; no LLM on this path; the Gate/money path is deterministic and separate."""
    from cosmu.knowledge.store import utcnow
    from cosmu.mind.source_trust import build_source_trust

    with store.reading():
        rows = build_source_trust(store)
    return SourceTrustResponse(
        as_of=utcnow(),
        rows=[
            SourceTrustRow(
                source=r.source,
                features=r.features,
                last_at=r.last_at,
                freshness_label=r.freshness_label,
                status=r.status,
                gate_pass_count=r.gate_pass_count,
                trust_score=r.trust_score,
                summary=r.summary,
                tier=r.tier,
                hours_since=r.hours_since,
            )
            for r in rows
        ],
    )


@router.get("/mind/news-intel", response_model=NewsIntelResponse)
def mind_news_intel(symbol: str = "BTCUSDT", limit: int = 20) -> NewsIntelResponse:
    """Recent scored news events for a symbol — the typed, dated, point-in-time news/intel panel.

    Each event has: ts, available_at, value (signed magnitude in [-1, 1]), event_type (bullish/bearish/neutral).
    Honest empty state when no news has been ingested yet. No LLM on this path — events were scored at ingest."""
    from cosmu.mind.news_intel import recent_news_events

    with store.reading():
        raw = recent_news_events(store, symbol=symbol, limit=min(limit, 100))
    return NewsIntelResponse(
        symbol=symbol,
        events=[
            NewsEventRow(
                ts=r.get("ts"),
                available_at=r.get("available_at"),
                value=float(r["value"]),
                event_type=r["event_type"],
                symbol=symbol,
            )
            for r in raw
        ],
    )
