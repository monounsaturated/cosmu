# Guard test for the observe-only LLM executor (P0.4e). Proves: it reasons per symbol, RECORDS each decision +
# its trace (and abstains) as audit events, and moves ZERO capital (no tracks, no positions, no orders). The
# reasoning seam is injected so the test is fully offline/deterministic. See docs/epics/agentic-lane.md.

from __future__ import annotations

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.strategy.agent_author import open_agent_strategy
from cosmu.strategy.agent_executor import run_agent_strategies, step_agent_strategy
from cosmu.strategy.agent_spec import AgentExitPolicy, AgentSpec, Decision


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/exec.sqlite3"))


def _agent(symbols) -> AgentSpec:
    return AgentSpec(
        name="a", rationale="r", symbols=symbols, max_position_pct=0.05,
        exit=AgentExitPolicy(stop_loss_pct=0.05, take_profit_pct=0.2, trailing_pct=0.03),
    )


def _strong(symbol: str) -> Decision:
    return Decision(symbol=symbol, side="long", confidence=0.9, stop_loss_pct=0.05, take_profit_pct=0.2,
                    size_request=0.05, rationale="strong", sources=["x:@a", "news:b"], trace=["read x", "read news"])


def test_step_records_decisions_and_abstains_no_capital(tmp_path):
    store = _store(tmp_path)
    agent = _agent(["AAA", "BBB"])
    vid = open_agent_strategy(store, agent)
    # reason: AAA -> a strong decision; BBB -> abstain (None)
    reason_fn = lambda a, s: _strong(s) if s == "AAA" else None  # noqa: E731
    resolved = step_agent_strategy(store, agent, vid, reason_fn=reason_fn)

    assert len(resolved) == 1 and resolved[0].decision.symbol == "AAA" and resolved[0].would_trade
    dec = store.rows("SELECT payload FROM events WHERE ref_id = ? AND kind = 'agent_decision'", (vid,))
    abst = store.rows("SELECT payload FROM events WHERE ref_id = ? AND kind = 'agent_abstain'", (vid,))
    assert len(dec) == 1 and len(abst) == 1
    # ZERO capital: observe-only never opens a track or position
    assert store.row("SELECT COUNT(*) AS n FROM tracks")["n"] == 0
    assert store.row("SELECT COUNT(*) AS n FROM positions")["n"] == 0


def test_run_agent_strategies_summary(tmp_path):
    store = _store(tmp_path)
    open_agent_strategy(store, _agent(["AAA", "BBB"]))
    reason_fn = lambda a, s: _strong(s) if s == "AAA" else None  # noqa: E731
    summary = run_agent_strategies(store, reason_fn=reason_fn)
    assert summary["strategies"] == 1
    assert summary["decisions"] == 1  # only the AAA would-trade decision counts


def test_killed_llm_strategies_are_skipped(tmp_path):
    store = _store(tmp_path)
    vid = open_agent_strategy(store, _agent(["AAA"]))
    with store.batch() as b:
        b.execute("UPDATE strategy_versions SET status = 'killed' WHERE id = ?", (vid,))
    summary = run_agent_strategies(store, reason_fn=lambda a, s: _strong(s))
    assert summary["strategies"] == 0
