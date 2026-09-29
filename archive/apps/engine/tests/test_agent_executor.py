# Guard test for the observe-only LLM executor (P0.4e). Proves: it reasons over each PRODUCT (symbol × venue),
# STAMPS the venue on each Decision, RECORDS each decision + its trace (and abstains) as audit events, and moves
# ZERO capital (no tracks, no positions, no orders). The reasoning seam is injected so the test is fully
# offline/deterministic. See docs/epics/agentic-lane.md.

from __future__ import annotations

import json

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.strategy.agent_author import open_agent_strategy
from cosmu.strategy.agent_executor import run_agent_strategies, step_agent_strategy
from cosmu.strategy.agent_spec import AgentExitPolicy, AgentSpec, Decision


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/exec.sqlite3"))


def _agent(symbols, venues=None) -> AgentSpec:
    return AgentSpec(
        name="a", rationale="r", symbols=symbols, max_position_pct=0.05,
        venues=venues or ["binance"],
        exit=AgentExitPolicy(stop_loss_pct=0.05, take_profit_pct=0.2, trailing_pct=0.03),
    )


def _strong(symbol: str) -> Decision:
    return Decision(symbol=symbol, side="long", confidence=0.9, stop_loss_pct=0.05, take_profit_pct=0.2,
                    size_request=0.05, rationale="strong", sources=["x:@a", "news:b"], trace=["read x", "read news"])


def _payloads(store: Store, vid: str, kind: str) -> list[dict]:
    return [json.loads(r["payload"]) for r in
            store.rows("SELECT payload FROM events WHERE ref_id = ? AND kind = ?", (vid, kind))]


def test_step_records_decisions_and_abstains_no_capital(tmp_path):
    store = _store(tmp_path)
    agent = _agent(["AAA", "BBB"])
    vid = open_agent_strategy(store, agent)
    # reason: AAA -> a strong decision; BBB -> abstain (None). The reason_fn now takes (agent, symbol, venue).
    reason_fn = lambda a, s, v: _strong(s) if s == "AAA" else None  # noqa: E731
    resolved = step_agent_strategy(store, agent, vid, reason_fn=reason_fn)

    assert len(resolved) == 1 and resolved[0].decision.symbol == "AAA" and resolved[0].would_trade
    dec = _payloads(store, vid, "agent_decision")
    abst = _payloads(store, vid, "agent_abstain")
    assert len(dec) == 1 and len(abst) == 1
    # the PRODUCT axis is recorded: the loop stamped the venue on the decision AND the abstain
    assert dec[0]["venue"] == "binance" and dec[0]["symbol"] == "AAA"
    assert abst[0]["venue"] == "binance" and abst[0]["symbol"] == "BBB"
    # ZERO capital: observe-only never opens a track or position
    assert store.row("SELECT COUNT(*) AS n FROM tracks")["n"] == 0
    assert store.row("SELECT COUNT(*) AS n FROM positions")["n"] == 0


def test_step_runs_over_the_symbol_times_venue_product(tmp_path):
    store = _store(tmp_path)
    agent = _agent(["AAA"], venues=["binance", "kraken"])
    vid = open_agent_strategy(store, agent)
    seen: list[tuple[str, str]] = []

    def reason_fn(a, symbol, venue):
        seen.append((symbol, venue))
        return _strong(symbol)

    resolved = step_agent_strategy(store, agent, vid, reason_fn=reason_fn)
    # one Decision PER product (1 symbol × 2 venues), each stamped with its own venue
    assert seen == [("AAA", "binance"), ("AAA", "kraken")]
    assert {r.decision.venue for r in resolved} == {"binance", "kraken"}
    venues = {p["venue"] for p in _payloads(store, vid, "agent_decision")}
    assert venues == {"binance", "kraken"}


def test_run_agent_strategies_summary(tmp_path):
    store = _store(tmp_path)
    open_agent_strategy(store, _agent(["AAA", "BBB"]))
    reason_fn = lambda a, s, v: _strong(s) if s == "AAA" else None  # noqa: E731
    summary = run_agent_strategies(store, reason_fn=reason_fn)
    assert summary["strategies"] == 1
    assert summary["decisions"] == 1  # only the AAA would-trade decision counts


def test_killed_llm_strategies_are_skipped(tmp_path):
    store = _store(tmp_path)
    vid = open_agent_strategy(store, _agent(["AAA"]))
    with store.batch() as b:
        b.execute("UPDATE strategy_versions SET status = 'killed' WHERE id = ?", (vid,))
    summary = run_agent_strategies(store, reason_fn=lambda a, s, v: _strong(s))
    assert summary["strategies"] == 0
