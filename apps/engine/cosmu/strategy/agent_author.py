# intent: persist an AgentSpec as a kind='llm' strategy_version so the LLM model exists end-to-end (and shows in
# the leaderboard with the `llm` badge). This is the ONE deliberate `kind='llm'` write site — every quant writer
# stays on the DB default 'quant'. The agent strategy is born `status='screened'` and ZERO-CAPITAL / observe-only:
# it carries no compiled code or params (an agent reasons, it isn't grid-fitted), so the NOT NULL quant columns
# get harmless placeholders (the same pattern the documented arms use). It does NOT open a funded track or move
# money — Gate B scores its evidence and a HUMAN launches it live later. See docs/epics/agentic-lane.md.
from __future__ import annotations

import hashlib
import json

from cosmu.knowledge.store import Store, utcnow
from cosmu.strategy.agent_spec import AgentSpec


def agent_code_hash(agent: AgentSpec) -> str:
    """Stable content hash of the agent spec (for dedup + the live-replication freeze, mirroring the quant path)."""
    payload = json.dumps(agent.model_dump(mode="json"), sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def open_agent_strategy(store: Store, agent: AgentSpec, *, origin: str = "agent") -> str:
    """Author an LLM strategy: insert its `strategies` parent + a kind='llm' `strategy_versions` row. Returns the
    version_id. Observe-only — no track, no capital, no order. Idempotent-friendly: re-authoring an identical spec
    produces the same code_hash so callers can dedup upstream."""
    spec_json = agent.model_dump(mode="json")
    with store.batch() as b:
        strategy_id = b.insert(
            "strategies",
            {"name": agent.name, "thesis": agent.rationale, "origin": origin, "created_at": utcnow()},
        )
        version_id = b.insert(
            "strategy_versions",
            {
                "strategy_id": strategy_id,
                "parent_id": None,
                "spec": spec_json,
                "generated_code": "# LLM agent strategy — reasoned by the Mind, not compiled spec code.",
                "code_hash": agent_code_hash(agent),
                "params": {},
                "origin": origin,
                "status": "screened",
                "kind": "llm",
                "authored_by": "agent",
                "created_at": utcnow(),
            },
        )
        b.append_event(
            actor="agent",
            kind="agent_strategy_authored",
            ref_type="strategy_version",
            ref_id=version_id,
            payload={"name": agent.name, "symbols": agent.symbols, "mode": agent.mode},
        )
    return version_id
