# intent: the DETERMINISTIC half of "LLM proposes, deterministic disposes" for ONE Decision. Takes a Decision the
# Mind proposed + its AgentSpec and finalizes it into a sized, exit-complete intent (or no-trade) by deterministic
# rules ONLY — the LLM never sizes or fires. Operator philosophy: we are a RISK MACHINE. A thin/single-source or
# low-confidence signal is sized DOWN (and always carries a hard stop), NEVER auto-discarded — missing real alpha
# out of caution is the worse error. The unified per-strategy caps clamp the result AGAIN at the order path; this
# is the strategy-level finalize, not the live cap. See docs/epics/agentic-lane.md.
from __future__ import annotations

from dataclasses import dataclass, field

from cosmu.strategy.agent_spec import AgentSpec, Decision

# Below this many independent corroborating sources we still PROCEED, but size down + flag caution (never kill).
_MIN_CORROBORATION = 2
_THIN_SOURCE_SIZE_MULT = 0.5  # single/thin-source signal: act small, don't skip
_LOW_CONF = 0.5               # below this confidence: also size down (still act)
_LOW_CONF_SIZE_MULT = 0.5


@dataclass
class ResolvedDecision:
    """The deterministic outcome for one proposed Decision: the finalized intent (trailing defaulted from the spec
    exit), the caution-adjusted + capped capital fraction, whether it would trade, and human-readable caution
    notes (shown so the operator SEES why a signal was sized down — never silently dropped)."""

    decision: Decision
    sized_fraction: float
    would_trade: bool
    caution: list[str] = field(default_factory=list)


def finalize_decision(agent: AgentSpec, decision: Decision) -> ResolvedDecision:
    """Deterministically finalize a proposed Decision. Guarantees an exit (SL/TP are mandatory on Decision;
    trailing defaults from the spec policy), caps the size at the spec's max_position_pct, and applies the
    risk-machine caution rule (thin corroboration / low confidence → smaller, never discarded)."""
    caution: list[str] = []
    # Exit completeness: default trailing from the spec policy when the decision did not set it.
    trailing = decision.trailing_pct if decision.trailing_pct is not None else agent.exit.trailing_pct
    d = decision.model_copy(update={"trailing_pct": trailing})

    if d.side == "flat":
        return ResolvedDecision(decision=d, sized_fraction=0.0, would_trade=False, caution=["flat — no trade"])

    size = min(max(d.size_request, 0.0), agent.max_position_pct)
    if len([s for s in d.sources if s.strip()]) < _MIN_CORROBORATION:
        size *= _THIN_SOURCE_SIZE_MULT
        caution.append(f"thin corroboration (<{_MIN_CORROBORATION} sources) — sized down, hard stop in place")
    if d.confidence < _LOW_CONF:
        size *= _LOW_CONF_SIZE_MULT
        caution.append(f"low confidence (<{_LOW_CONF}) — sized down")

    size = round(size, 6)
    return ResolvedDecision(decision=d, sized_fraction=size, would_trade=size > 0.0, caution=caution)
