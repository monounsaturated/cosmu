# intent: the OBSERVE-ONLY executor for LLM strategies. For each kind='llm' strategy, reason per symbol (the Mind
# panel -> Decision), finalize it deterministically (size/exit/caution), and RECORD the decision + its trace as an
# audit event. ZERO CAPITAL: it never opens a track, position, or order — it makes the agentic process VISIBLE so
# the operator can watch; Gate B + a HUMAN launch decide if it ever touches money. The reasoning seam is injected
# (the default wires the Mind; tests inject a stub) so this is fully testable offline. A malformed spec or a
# reasoning error is an HONEST skip, never a crash of the observe loop. See docs/epics/agentic-lane.md.
from __future__ import annotations

from collections.abc import Callable

from cosmu.knowledge.store import Store
from cosmu.mind.analysts import gather_context
from cosmu.mind.judge import JudgeFn
from cosmu.strategy.agent_decision import ResolvedDecision, finalize_decision
from cosmu.strategy.agent_loop import agent_reason
from cosmu.strategy.agent_spec import AgentSpec, Decision

ReasonFn = Callable[[AgentSpec, str], Decision | None]


def default_reason_fn(store: Store, *, judge: JudgeFn | None = None) -> ReasonFn:
    """The runnable reasoning seam: the Mind panel over the current global context, gathered ONCE per run.
    (Per-symbol reference bars are a refinement — backlogged; v1 reasons off the global macro/sentiment/positioning
    panel and abstains cleanly when no analyst has data.)"""
    ctx = gather_context(store)
    return lambda agent, symbol: agent_reason(agent, symbol, ctx, judge=judge)


def _record_decision(store: Store, version_id: str, resolved: ResolvedDecision) -> None:
    d = resolved.decision
    with store.batch() as b:
        b.append_event(
            actor="agent", kind="agent_decision", ref_type="strategy_version", ref_id=version_id,
            payload={
                "symbol": d.symbol, "side": d.side, "confidence": d.confidence,
                "sized_fraction": resolved.sized_fraction, "would_trade": resolved.would_trade,
                "stop_loss_pct": d.stop_loss_pct, "take_profit_pct": d.take_profit_pct,
                "trailing_pct": d.trailing_pct, "caution": resolved.caution,
                "sources": d.sources, "rationale": d.rationale, "trace": d.trace,
            },
        )


def _record_abstain(store: Store, version_id: str, symbol: str) -> None:
    with store.batch() as b:
        b.append_event(
            actor="agent", kind="agent_abstain", ref_type="strategy_version", ref_id=version_id,
            payload={"symbol": symbol, "reason": "no market analyst had data"},
        )


def step_agent_strategy(
    store: Store, agent: AgentSpec, version_id: str, *, reason_fn: ReasonFn
) -> list[ResolvedDecision]:
    """Observe-only: reason over each of the agent's symbols, finalize, and RECORD the decision/abstain. Never
    opens a track/position/order — no capital moves. Returns the resolved decisions for the caller's aggregate."""
    out: list[ResolvedDecision] = []
    for symbol in agent.symbols:
        decision = reason_fn(agent, symbol)
        if decision is None:
            _record_abstain(store, version_id, symbol)
            continue
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
