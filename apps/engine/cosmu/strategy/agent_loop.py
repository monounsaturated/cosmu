# intent: the reasoning loop for an LLM strategy — turn the Mind's analyst panel into ONE typed Decision per
# symbol. "LLM proposes": the Mind's market analysts read point-in-time signals (and, when a judge seam is on, an
# LLM re-scores the evidence) into weighted directional Stances; this maps their weighted consensus into a typed
# Decision. "Deterministic disposes": finalize_decision (agent_decision.py) then sizes/guards it; nothing here
# funds or fires. ABSTAIN is honoured — if no market analyst has data, NO Decision is produced (never fabricate a
# read). The mapping is a PURE function (stances_to_decision) so it is fully testable without an LLM. The judge
# is injected (offline/heuristic by default; cheap OpenRouter at runtime). See docs/epics/agentic-lane.md.
from __future__ import annotations

from cosmu.mind.analysts import MindContext, Stance, run_panel
from cosmu.mind.judge import JudgeFn
from cosmu.strategy.agent_spec import AgentSpec, Decision

# |weighted consensus| below this = no clear direction → a 'flat' Decision (the agent LOOKED and saw no edge,
# which is recorded for the trace — distinct from ABSTAIN, where there was no data to look at).
_DIR_DEADBAND = 0.1


def stances_to_decision(agent: AgentSpec, symbol: str, stances: list[Stance]) -> Decision | None:
    """Map the Mind panel's Stances to one typed Decision for `symbol`, PURELY (no LLM, no IO). Only MARKET
    stances with weight > 0 vote (process/abstaining stances inform but don't direct). Returns None when no
    market analyst has data (ABSTAIN — never fabricate). Exit defaults come from the agent's mandatory policy."""
    market = [s for s in stances if s.kind == "market" and s.weight > 0]
    if not market:
        return None  # no data → abstain
    wsum = sum(s.weight for s in market)
    consensus = sum(s.weight * s.score for s in market) / wsum if wsum > 0 else 0.0
    if consensus > _DIR_DEADBAND:
        side = "long"
    elif consensus < -_DIR_DEADBAND:
        side = "short"
    else:
        side = "flat"
    return Decision(
        symbol=symbol,
        side=side,
        confidence=round(min(1.0, abs(consensus)), 4),
        stop_loss_pct=agent.exit.stop_loss_pct,
        take_profit_pct=agent.exit.take_profit_pct,
        trailing_pct=agent.exit.trailing_pct,
        size_request=agent.max_position_pct,
        rationale=f"panel consensus {consensus:+.2f} on {symbol} across {len(market)} market analyst(s)",
        sources=[s.perspective for s in market],
        trace=[f"{s.perspective}: {s.lean} (conv {s.conviction:.2f}, w {s.weight:.2f}) — {s.headline}" for s in market],
    )


def agent_reason(
    agent: AgentSpec, symbol: str, ctx: MindContext, *, judge: JudgeFn | None = None
) -> Decision | None:
    """Run the Mind panel over `ctx` (offline/heuristic when judge is None; LLM-judged when supplied) and map it
    to a Decision for `symbol`. Thin wrapper over run_panel + the pure stances_to_decision."""
    return stances_to_decision(agent, symbol, run_panel(ctx, judge=judge))
