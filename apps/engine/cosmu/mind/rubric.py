# intent: the committee's RUBRICS + the typed VERDICT an LLM judge returns. Each MARKET pillar has a rubric —
# its trading prior, the criteria it weighs, and what a positive vs negative score MEANS — so an LLM can score
# the pillar's point-in-time evidence into a structured {lean, score, confidence, rationale}. The Verdict is
# instructor-style: a Pydantic shape with extra="forbid" so the model can only ever return the typed thing (no
# smuggled threshold, no code, no money move). invariants: the LLM SCORES a pillar; it may NOT abstain (abstain
# is a no-data FACT decided in Python before any judge runs) and it NEVER funds — the deterministic gate alone
# disposes. The rubric is pure description; it only steers the judge's prompt.

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# An LLM judge may only land on a directional lean — "abstain" is NOT in this set on purpose: a pillar with no
# ingested data abstains in Python and is never sent to the model, so the model can never fabricate a read.
VERDICT_LEANS = ("bullish", "bearish", "neutral")


@dataclass(frozen=True)
class Rubric:
    """How ONE pillar is scored. `prior` is the trading edge it encodes; `criteria` are the things to weigh;
    `scale` says what a positive vs a negative score means. Pure description — it drives the judge's prompt and
    nothing else. There is intentionally no rubric for the PROCESS pillars (ML survival, Memory): they report
    the machine's self-knowledge, not a price call, so they are never LLM-judged."""

    pillar: str
    prior: str
    criteria: tuple[str, ...]
    scale: str


class Verdict(BaseModel):
    """The typed thing an LLM judge returns for one pillar: a rubric-scored read. `extra="forbid"` means the
    model can emit ONLY these four fields — anything else (a numeric threshold, a position size, a money move)
    is rejected outright, the same typed boundary the strategy author uses. `score` is the signed directional
    strength (-1 fully bearish … +1 fully bullish); `confidence` is how sure the pillar is (0..1). The LLM
    SCORES; the deterministic aggregation COMBINES; the gate DISPOSES. The model may not abstain."""

    model_config = ConfigDict(extra="forbid")

    lean: Literal["bullish", "bearish", "neutral"]
    score: float = Field(description="signed directional strength in [-1, 1]")
    confidence: float = Field(description="confidence in [0, 1]")
    rationale: str = Field(description="one plain-language sentence on the why")

    @field_validator("score")
    @classmethod
    def _clamp_score(cls, v: float) -> float:
        return max(-1.0, min(1.0, float(v)))

    @field_validator("confidence")
    @classmethod
    def _clamp_confidence(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))

    @field_validator("rationale")
    @classmethod
    def _trim_rationale(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("rationale must not be empty")
        return v[:280]


# One rubric per MARKET pillar, keyed by the analyst's `perspective` (matches analysts.py exactly). The prior
# mirrors each analyst's documented edge so the LLM judge scores the SAME thesis the deterministic heuristic
# encodes — the model re-reads the point-in-time evidence under that rubric, it does not invent a new strategy.
RUBRICS: dict[str, Rubric] = {
    "Technical": Rubric(
        pillar="Technical",
        prior="Trend persistence × realized-volatility regime on a real reference series.",
        criteria=("trend sign (bull/bear/chop)", "realized-volatility tercile (low/mid/high)"),
        scale="+1 = clean bullish trend in calm vol; -1 = bearish trend; 0 = chop / no edge.",
    ),
    "Macro": Rubric(
        pillar="Macro",
        prior="Curve slope, real rates and liquidity condition risk premia across every asset class.",
        criteria=("macro regime", "yield curve 2s10s", "credit spread", "DXY", "VIX term slope"),
        scale="+1 = broad risk-on (steepening curve, tight credit, easing liquidity); -1 = risk-off.",
    ),
    "Sentiment": Rubric(
        pillar="Sentiment",
        prior="Buy fear, fade greed: crowd sentiment extremes mean-revert at the swing horizon.",
        criteria=("Fear & Greed index (0-100)", "Reddit crowd chatter (low-confidence cross-check)"),
        scale="+1 = extreme fear (contrarian bullish); -1 = extreme greed (contrarian bearish); 0 = balanced.",
    ),
    "Social & News": Rubric(
        pillar="Social & News",
        prior="A positive news/social-flow shift precedes multi-day continuation before it is fully priced.",
        criteria=("news-flow sentiment [-1,1]", "LunarCrush social sentiment", "social volume (attention only)"),
        scale="+1 = strongly positive flow shift; -1 = negative; volume is attention, not direction.",
    ),
    "Positioning": Rubric(
        pillar="Positioning",
        prior="Funding extremes proxy crowded leverage; liquidation cascades overshoot and exhaust.",
        criteria=("perp funding z-score", "open interest", "perp-spot basis", "exchange netflow", "liquidation cascade"),
        scale="+1 = room to run (light/negative funding, exhausted sellers); -1 = crowded longs.",
    ),
    "OSINT": Rubric(
        pillar="OSINT",
        prior="Aircraft activity as a crude, low-confidence economic-activity / risk-appetite proxy.",
        criteria=("OSINT air-activity index",),
        scale="+1 = elevated activity (risk-on proxy); -1 = subdued; weak signal — keep confidence low.",
    ),
}
