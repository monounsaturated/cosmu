# intent: the OBSERVE-ONLY executor for LLM strategies. For each kind='llm' strategy, reason over each PRODUCT
# (symbol × venue) — the Mind panel -> Decision — stamp the venue on the Decision, finalize it deterministically
# (size/exit/caution), and RECORD the decision + its trace as an audit event. ZERO CAPITAL: it never opens a
# track, position, or order — it makes the agentic process VISIBLE so the operator can watch; Gate B + a HUMAN
# launch decide if it ever touches money. The reasoning seam is injected (the default wires the Mind; tests
# inject a stub) so this is fully testable offline. A malformed spec or a reasoning error is an HONEST skip,
# never a crash of the observe loop. See docs/epics/agentic-lane.md.
from __future__ import annotations

from collections.abc import Callable

from cosmu.knowledge.store import Store
from cosmu.mind.analysts import MindContext, context_for_symbol, gather_context
from cosmu.mind.judge import JudgeFn
from cosmu.strategy.agent_decision import ResolvedDecision, finalize_decision
from cosmu.strategy.agent_loop import agent_reason
from cosmu.strategy.agent_spec import AgentSpec, Decision

# (agent, symbol, venue) -> a proposed Decision (or None to abstain). The venue is passed so a per-venue reason
# is possible later; the loop stamps it on the returned Decision authoritatively regardless.
ReasonFn = Callable[[AgentSpec, str, str], Decision | None]


def default_reason_fn(store: Store, *, judge: JudgeFn | None = None) -> ReasonFn:
    """The runnable reasoning seam over the PRODUCT (symbol × venue). Market-wide context (fear_greed, macro, the
    FRED block, OSINT) is gathered ONCE; the per-symbol metrics (funding/sentiment/positioning) are resolved PER
    SYMBOL and cached, so the panel reasons on THIS asset's funding/sentiment instead of whichever symbol's row
    was newest. Venue is the recorded product axis: alt_data has no venue column, so an agent's venues share the
    per-symbol context — we record the venue honestly rather than fabricate per-venue funding we don't have.
    (Per-symbol reference bars / per-venue feeds are a refinement — backlogged.)"""
    market_ctx = gather_context(store)
    by_symbol: dict[str, MindContext] = {}

    def reason(agent: AgentSpec, symbol: str, venue: str) -> Decision | None:
        ctx = by_symbol.get(symbol)
        if ctx is None:
            ctx = context_for_symbol(store, market_ctx, symbol)
            by_symbol[symbol] = ctx
        return agent_reason(agent, symbol, ctx, judge=judge)

    return reason


def _record_decision(store: Store, version_id: str, resolved: ResolvedDecision) -> None:
    d = resolved.decision
    with store.batch() as b:
        b.append_event(
            actor="agent", kind="agent_decision", ref_type="strategy_version", ref_id=version_id,
            payload={
                "symbol": d.symbol, "venue": d.venue, "side": d.side, "confidence": d.confidence,
                "sized_fraction": resolved.sized_fraction, "would_trade": resolved.would_trade,
                "stop_loss_pct": d.stop_loss_pct, "take_profit_pct": d.take_profit_pct,
                "trailing_pct": d.trailing_pct, "caution": resolved.caution,
                "sources": d.sources, "rationale": d.rationale, "trace": d.trace,
            },
        )


def _record_abstain(store: Store, version_id: str, symbol: str, venue: str) -> None:
    with store.batch() as b:
        b.append_event(
            actor="agent", kind="agent_abstain", ref_type="strategy_version", ref_id=version_id,
            payload={"symbol": symbol, "venue": venue, "reason": "no market analyst had data"},
        )


def step_agent_strategy(
    store: Store, agent: AgentSpec, version_id: str, *, reason_fn: ReasonFn
) -> list[ResolvedDecision]:
    """Observe-only over the PRODUCT (symbol × venue): reason for each (symbol, venue), STAMP the venue on the
    Decision (the loop owns the product axis — the LLM never proposes a venue), finalize, and RECORD the
    decision/abstain. Never opens a track/position/order — no capital moves. Returns the resolved decisions for
    the caller's aggregate."""
    out: list[ResolvedDecision] = []
    for symbol in agent.symbols:
        for venue in agent.venues:
            decision = reason_fn(agent, symbol, venue)
            if decision is None:
                _record_abstain(store, version_id, symbol, venue)
                continue
            decision = decision.model_copy(update={"venue": venue})
            resolved = finalize_decision(agent, decision)
            _record_decision(store, version_id, resolved)
            out.append(resolved)
    return out


def run_agent_strategies(
    store: Store, *, reason_fn: ReasonFn | None = None, judge: JudgeFn | None = None
) -> dict:
    """Observe-only runner over every live (non-killed) kind='llm' strategy — the entry point a tick cron calls.
    Returns a small summary; NO capital moves anywhere."""
    rows = store.rows("SELECT id, spec FROM strategy_versions WHERE kind = 'llm' AND status != 'killed'")
    rf = reason_fn if reason_fn is not None else default_reason_fn(store, judge=judge)
    n_strats = 0
    n_decisions = 0
    for r in rows:
        try:
            agent = AgentSpec.model_validate_json(r["spec"])
        except Exception:  # noqa: BLE001 — a malformed spec is an honest skip, never a crash of the observe loop
            continue
        resolveds = step_agent_strategy(store, agent, r["id"], reason_fn=rf)
        n_strats += 1
        n_decisions += sum(1 for x in resolveds if x.would_trade)
    return {"strategies": n_strats, "decisions": n_decisions}
