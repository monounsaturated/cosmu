# intent: the LLM strategy MODEL artifact (kind='llm'). An AgentSpec is a reasoning-loop strategy — the Mind
# reasons over `sources` per its `rationale` and emits typed Decisions; Gate B (scientific-flexible, NOT the quant
# backtest) scores the evidence, and a HUMAN launches it live. It mirrors StrategySpec's ROLE for the quant model
# but carries NO param_space / compiled code: an agent reasons over unstructured info, it is not grid-optimised.
# INVARIANT: the LLM only PROPOSES a Decision; deterministic admission + the risk gauntlet + sizing + the order
# path dispose/size/fire — never the LLM, and the LLM never defines its own success metric. Every AgentSpec MUST
# carry an exit policy (stop/take/trailing) — no LLM strategy is exit-less. See docs/epics/agentic-lane.md.
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AgentExitPolicy(BaseModel):
    """Mandatory exit policy for an LLM strategy. CONCRETE fractions (not ParamRefs — agents aren't grid-fitted);
    these are the defaults a Decision inherits unless it overrides per-trade. Trailing is first-class."""

    # hard stop / take-profit as a fraction of entry; trailing-stop distance once in profit (None = off).
    stop_loss_pct: float = Field(gt=0, le=1)
    take_profit_pct: float = Field(gt=0)
    trailing_pct: float | None = Field(default=None, gt=0)
    time_stop_days: float | None = Field(default=None, gt=0)


class AgentSpec(BaseModel):
    """An LLM / agentic strategy: reasons over unstructured info, proposes Decisions, validated by Gate B and
    launched by a human. NOT the quant model — no param_space, no compiled code, no optimizer."""

    name: str
    # The NL thesis/summary — the creation contract AND the modular summary shown in the UI, kept as ONE field
    # (low-debt: a strategy is "mostly a natural-language summary", not a wall of quantified columns).
    rationale: str = Field(min_length=1)
    kind: Literal["llm"] = "llm"  # the model discriminator, mirrors strategy_versions.kind
    # The assets it watches / may trade. A SINGLE symbol is fine (small social markets are the point); a single
    # source is caution, never an auto-discard.
    symbols: list[str] = Field(min_length=1)
    # The venues it trades each symbol on — the OTHER half of the product axis (symbol × venue). At least one
    # (mirrors symbols): the observe loop runs over every (symbol, venue) PRODUCT and stamps the venue on each
    # Decision so a per-venue fee/funding/legality read is attributable later.
    venues: list[str] = Field(default_factory=lambda: ["binance"], min_length=1)
    exit: AgentExitPolicy  # MANDATORY — no exit-less LLM strategy
    # Sizing cap; the unified per-strategy caps still clamp it when live (see docs/epics/agentic-lane.md).
    max_position_pct: float = Field(default=0.05, gt=0, le=1)
    sources: list[str] = Field(default_factory=list)  # where the agent looks (free-form; no allow/deny list)
    mode: Literal["autonomous", "slack_hitl", "manual"] = "autonomous"
    cadence: Literal["1h", "4h", "1d"] = "4h"  # how often the reasoning loop runs


class Decision(BaseModel):
    """One typed trade intent the agent emits. The LLM PROPOSES this; deterministic code disposes/sizes/fires.
    SL/TP/trailing default from AgentSpec.exit but may be overridden per-decision. `trace` is the visible
    reasoning so the operator can SEE the agentic process step by step."""

    symbol: str
    # The PRODUCT axis: which venue this intent is for (symbol × venue). The LLM does NOT propose it — the
    # observe loop stamps it as it iterates an agent's venues — so it is None on a freshly-proposed Decision and
    # carries the venue once recorded. Kept on the Decision so each recorded read is attributable to a product.
    venue: str | None = None
    side: Literal["long", "short", "flat"]
    confidence: float = Field(ge=0, le=1)
    # The price zone the signal is valid in — past it the signal is stale (the operator/agent can skip a late fill).
    entry_low: float | None = None
    entry_high: float | None = None
    stop_loss_pct: float = Field(gt=0, le=1)
    take_profit_pct: float = Field(gt=0)
    trailing_pct: float | None = Field(default=None, gt=0)
    size_request: float = Field(ge=0, le=1)  # fraction requested; the unified caps clamp it downstream
    rationale: str = Field(min_length=1)  # brief NL why
    sources: list[str] = Field(default_factory=list)  # corroborating sources (1 allowed — caution, not kill)
    trace: list[str] = Field(default_factory=list)  # the visible reasoning steps (for the trace UI)
