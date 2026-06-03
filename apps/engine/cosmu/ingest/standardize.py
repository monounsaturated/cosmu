# intent: the LLM universal adapter — turn unstructured headlines into a validated numeric feature, ONCE, at ingest time; inputs: NewsItem headlines; outputs: point-in-time AltDataPoint sentiment series and typed NewsEventScore events; invariants: LLM (when present) runs cheap-tier, batched, content-hash-cached, behind a frozen versioned transform — and NEVER in any backtest/scoring/decision path. Offline it falls back to a deterministic lexicon so the gate runs with no key.

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from datetime import datetime  # used in ScoredNewsEvent type annotation

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from cosmu.data.altdata import AltDataPoint, NewsItem

# Frozen transform version — pinned into any feature built from it (feature_registry: news_sentiment).
# Bump this string if the standardization logic changes, so old survivors stay reproducible.
TRANSFORM_VERSION = "news-sentiment-v1"

# Frozen transform version for the typed event/news scorer.
# Bump when the scoring logic changes so gate-passed survivors stay reproducible.
EVENT_SCORE_TRANSFORM_VERSION = "news-event-score-v1"

_BULLISH = frozenset(
    {"surge", "surges", "rally", "rallies", "breakout", "record", "adoption", "approval", "approved",
     "partnership", "bullish", "gains", "soars", "soar", "upgrade", "inflow", "inflows", "etf", "all-time"}
)
_BEARISH = frozenset(
    {"crash", "crashes", "plunge", "plunges", "hack", "hacked", "ban", "banned", "lawsuit", "selloff",
     "bearish", "dump", "dumps", "downgrade", "outflow", "outflows", "exploit", "fear", "liquidation", "liquidations"}
)


class StandardizedNews(BaseModel):
    """The validated numeric row the messy headline collapses to."""

    event_type: str  # "bullish" | "bearish" | "neutral"
    sentiment: float = Field(ge=-1.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Typed event/news scorer — point-in-time signal with sign + magnitude.
# The LLM ONLY standardizes text here; it is NEVER on the gate/money path.
# ---------------------------------------------------------------------------


class NewsEventScore(BaseModel):
    """The typed, dated, point-in-time event/news signal.

    `sign` is the direction: +1 (bullish), -1 (bearish), 0 (neutral).
    `magnitude` in [0, 1] is how strong the event is (0 = very weak, 1 = maximum).
    `event_type` is a human-readable label ("bullish" / "bearish" / "neutral").
    `confidence` in [0, 1] is how confident the scorer is in the classification.
    `headline` is the source text (for audit/display).
    `transform_version` is pinned so gate-passed survivors remain re-runnable.
    """

    sign: Literal[-1, 0, 1]
    magnitude: float = Field(ge=0.0, le=1.0)
    event_type: Literal["bullish", "bearish", "neutral"]
    confidence: float = Field(ge=0.0, le=1.0)
    headline: str
    transform_version: str = EVENT_SCORE_TRANSFORM_VERSION


@dataclass(frozen=True)
class ScoredNewsEvent:
    """One point-in-time scored event (the scored analogue of a NewsItem).

    `ts` and `available_at` mirror NewsItem semantics so this can be stored as an AltDataPoint.
    `score` is the signed magnitude (sign × magnitude) — the gate-readable numeric value in [-1, 1].
    """

    ts: "datetime"  # observation time (from NewsItem)
    available_at: "datetime"  # when we'd have known it (point-in-time, no look-ahead)
    headline: str
    event_type: Literal["bullish", "bearish", "neutral"]
    sign: Literal[-1, 0, 1]
    magnitude: float  # [0, 1]
    confidence: float  # [0, 1]

    @property
    def score(self) -> float:
        """Signed magnitude in [-1, 1]. This is the value stored as an AltDataPoint."""
        return float(self.sign) * self.magnitude


def standardize_headline(headline: str) -> StandardizedNews:
    """Deterministic offline lexicon standardizer (the no-key path). Validated by the same model
    the LLM path returns, so swapping in the LLM changes accuracy, not the contract."""
    words = set(re.findall(r"[a-z'\-]+", headline.lower()))
    bull = len(words & _BULLISH)
    bear = len(words & _BEARISH)
    total = bull + bear
    if total == 0:
        return StandardizedNews(event_type="neutral", sentiment=0.0, confidence=0.0)
    sentiment = round((bull - bear) / total, 6)
    return StandardizedNews(
        event_type="bullish" if sentiment > 0 else "bearish" if sentiment < 0 else "neutral",
        sentiment=sentiment,
        confidence=round(min(1.0, total / 3.0), 6),
    )


def standardize_news(
    items: list[NewsItem],
    *,
    cache: dict[str, StandardizedNews] | None = None,
    llm: Callable[[str], StandardizedNews] | None = None,
    counter: dict[str, int] | None = None,
) -> list[AltDataPoint]:
    """Map headlines → point-in-time sentiment points. Content-hash cached so a repeated headline
    never triggers a second computation/LLM call. `llm` (validated via instructor upstream) slots in
    when a key is set; default is the deterministic offline path."""
    cache = cache if cache is not None else {}
    compute = llm or standardize_headline
    out: list[AltDataPoint] = []
    for item in items:
        key = hashlib.sha256(item.headline.encode("utf-8")).hexdigest()
        if key not in cache:
            cache[key] = compute(item.headline)
            if counter is not None:
                counter["calls"] = counter.get("calls", 0) + 1
        out.append(AltDataPoint(ts=item.ts, available_at=item.available_at, value=cache[key].sentiment))
    return sorted(out, key=lambda p: p.ts)


# ---------------------------------------------------------------------------
# score_news_events: turn NewsItems into typed ScoredNewsEvents, then store
# the signed-magnitude as the `news_event_score` AltDataPoint series.
# The LLM (when present) only scores text — NEVER touches the gate path.
# ---------------------------------------------------------------------------


def _score_headline(headline: str) -> NewsEventScore:
    """Deterministic offline lexicon scorer for `news_event_score`.

    Same lexicons as `standardize_headline` but returns a typed `NewsEventScore`
    with an explicit sign and magnitude rather than a raw [-1,1] float.
    This is the no-LLM path; an injected `llm` scorer slots in when keyed."""
    words = set(re.findall(r"[a-z'\-]+", headline.lower()))
    bull = len(words & _BULLISH)
    bear = len(words & _BEARISH)
    total = bull + bear
    if total == 0:
        return NewsEventScore(sign=0, magnitude=0.0, event_type="neutral", confidence=0.0, headline=headline)
    raw = (bull - bear) / total
    sign: Literal[-1, 0, 1] = 1 if raw > 0 else (-1 if raw < 0 else 0)
    magnitude = round(abs(raw), 6)
    confidence = round(min(1.0, total / 3.0), 6)
    event_type: Literal["bullish", "bearish", "neutral"] = "bullish" if sign == 1 else ("bearish" if sign == -1 else "neutral")
    return NewsEventScore(sign=sign, magnitude=magnitude, event_type=event_type, confidence=confidence, headline=headline)


def score_news_events(
    items: list[NewsItem],
    *,
    cache: dict[str, NewsEventScore] | None = None,
    llm: Callable[[str], NewsEventScore] | None = None,
    counter: dict[str, int] | None = None,
) -> list[ScoredNewsEvent]:
    """Score headlines into typed ScoredNewsEvents (sign + magnitude + event_type + confidence).

    Content-hash cached so repeated headlines cost nothing. `llm` slots in when a key is set;
    the default is the deterministic offline lexicon. The LLM ONLY standardizes text here —
    it is NEVER on the gate/scoring/money path. Returns sorted by ts (point-in-time order)."""
    cache = cache if cache is not None else {}
    compute = llm or _score_headline
    out: list[ScoredNewsEvent] = []
    for item in items:
        key = hashlib.sha256(item.headline.encode("utf-8")).hexdigest()
        if key not in cache:
            cache[key] = compute(item.headline)
            if counter is not None:
                counter["calls"] = counter.get("calls", 0) + 1
        scored = cache[key]
        out.append(
            ScoredNewsEvent(
                ts=item.ts,
                available_at=item.available_at,
                headline=item.headline,
                event_type=scored.event_type,
                sign=scored.sign,
                magnitude=scored.magnitude,
                confidence=scored.confidence,
            )
        )
    return sorted(out, key=lambda e: e.ts)


def scored_events_to_altdata(events: list[ScoredNewsEvent]) -> list[AltDataPoint]:
    """Convert ScoredNewsEvents to the AltDataPoint series the ingest store expects.

    The stored value is `sign × magnitude` (the signed magnitude in [-1, 1]), preserving
    direction and strength as a single number the gate can consume point-in-time."""
    return [AltDataPoint(ts=e.ts, available_at=e.available_at, value=e.score) for e in events]
