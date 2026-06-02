# intent: the LLM universal adapter — turn unstructured headlines into a validated numeric feature, ONCE, at ingest time; inputs: NewsItem headlines; outputs: point-in-time AltDataPoint sentiment series; invariants: LLM (when present) runs cheap-tier, batched, content-hash-cached, behind a frozen versioned transform — and NEVER in any backtest/scoring/decision path. Offline it falls back to a deterministic lexicon so the gate runs with no key.

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable

from pydantic import BaseModel, Field

from cosmu.data.altdata import AltDataPoint, NewsItem

# Frozen transform version — pinned into any feature built from it (feature_registry: news_sentiment).
# Bump this string if the standardization logic changes, so old survivors stay reproducible.
TRANSFORM_VERSION = "news-sentiment-v1"

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
