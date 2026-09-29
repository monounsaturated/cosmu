# Guard test for authoring an LLM strategy (P0.4b). Proves: open_agent_strategy persists a kind='llm'
# strategy_version (observe-only, born 'screened'), its spec round-trips back to an AgentSpec, the parent
# `strategies` row exists, an audit event is written, the content hash is stable, and NO track/position is opened
# (no capital moves). See docs/epics/agentic-lane.md.

from __future__ import annotations

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.strategy.agent_author import agent_code_hash, open_agent_strategy
from cosmu.strategy.agent_spec import AgentExitPolicy, AgentSpec


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/agent.sqlite3"))


def _agent() -> AgentSpec:
    return AgentSpec(
        name="tweet-sniper",
        rationale="small-cap social catalyst on a credible account",
        symbols=["DOGEUSDT"],
        exit=AgentExitPolicy(stop_loss_pct=0.05, take_profit_pct=0.2, trailing_pct=0.03),
        sources=["x:@someone"],
    )


def test_open_agent_strategy_persists_kind_llm(tmp_path):
    store = _store(tmp_path)
    vid = open_agent_strategy(store, _agent())
    row = store.row("SELECT kind, status, origin, spec, strategy_id FROM strategy_versions WHERE id = ?", (vid,))
    assert row is not None
    assert row["kind"] == "llm"
    assert row["status"] == "screened"
    assert row["origin"] == "agent"
    # spec round-trips back into a typed AgentSpec
    again = AgentSpec.model_validate_json(row["spec"])
    assert again.name == "tweet-sniper" and again.symbols == ["DOGEUSDT"] and again.kind == "llm"
    # parent strategies row exists
    parent = store.row("SELECT name, origin FROM strategies WHERE id = ?", (row["strategy_id"],))
    assert parent is not None and parent["name"] == "tweet-sniper"


def test_authoring_writes_an_audit_event(tmp_path):
    store = _store(tmp_path)
    vid = open_agent_strategy(store, _agent())
    ev = store.row("SELECT kind FROM events WHERE ref_id = ? AND kind = 'agent_strategy_authored'", (vid,))
    assert ev is not None


def test_no_track_or_position_opened(tmp_path):
    # observe-only: authoring an LLM strategy must NOT fund a track or open a position (no capital moves)
    store = _store(tmp_path)
    open_agent_strategy(store, _agent())
    assert store.row("SELECT COUNT(*) AS n FROM tracks")["n"] == 0
    assert store.row("SELECT COUNT(*) AS n FROM positions")["n"] == 0


def test_code_hash_is_stable_and_content_addressed(tmp_path):
    a = _agent()
    assert agent_code_hash(a) == agent_code_hash(a)
    b = a.model_copy(update={"rationale": "a different thesis"})
    assert agent_code_hash(a) != agent_code_hash(b)
