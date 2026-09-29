# Guard test for the LLM strategy artifact (AgentSpec / Decision) — the P0.4a foundation of the LLM model.
# Proves the typed contract: kind is fixed 'llm', an exit policy is MANDATORY (no exit-less LLM strategy), at
# least one symbol is required (single symbol allowed — small markets), trailing is first-class+optional, and a
# Decision round-trips. See docs/epics/agentic-lane.md.

from __future__ import annotations

import pytest
from pydantic import ValidationError

from cosmu.strategy.agent_spec import AgentExitPolicy, AgentSpec, Decision


def _exit() -> AgentExitPolicy:
    return AgentExitPolicy(stop_loss_pct=0.05, take_profit_pct=0.15, trailing_pct=0.03)


def _agent(**kw) -> AgentSpec:
    base = dict(name="tweet-sniper", rationale="small-cap social catalyst", symbols=["DOGEUSDT"], exit=_exit())
    base.update(kw)
    return AgentSpec(**base)


def test_agentspec_kind_is_fixed_llm():
    assert _agent().kind == "llm"
    # the discriminator is not overridable to quant — that's the StrategySpec model's job
    with pytest.raises(ValidationError):
        _agent(kind="quant")


def test_exit_policy_is_mandatory():
    with pytest.raises(ValidationError):
        AgentSpec(name="x", rationale="r", symbols=["BTCUSDT"])  # no exit


def test_at_least_one_symbol_required_single_allowed():
    assert _agent(symbols=["PEPEUSDT"]).symbols == ["PEPEUSDT"]  # single symbol is fine
    with pytest.raises(ValidationError):
        _agent(symbols=[])


def test_rationale_required():
    with pytest.raises(ValidationError):
        _agent(rationale="")


def test_trailing_is_optional_and_positive():
    assert AgentExitPolicy(stop_loss_pct=0.05, take_profit_pct=0.1).trailing_pct is None
    with pytest.raises(ValidationError):
        AgentExitPolicy(stop_loss_pct=0.05, take_profit_pct=0.1, trailing_pct=0)


def test_defaults_are_sane():
    a = _agent()
    assert a.venues == ["binance"]
    assert a.mode == "autonomous"
    assert a.cadence == "4h"
    assert 0 < a.max_position_pct <= 1


def test_decision_round_trips_and_validates():
    d = Decision(
        symbol="DOGEUSDT", side="long", confidence=0.6,
        stop_loss_pct=0.05, take_profit_pct=0.2, trailing_pct=0.03, size_request=0.02,
        rationale="influencer with real reach called it; one corroborating tweet",
        sources=["x:@someone"], trace=["read x", "checked follower authenticity", "no momentum yet"],
    )
    again = Decision.model_validate(d.model_dump(mode="json"))
    assert again.side == "long" and again.confidence == 0.6
    # confidence is bounded; a bad side is rejected
    with pytest.raises(ValidationError):
        Decision(symbol="X", side="sideways", confidence=0.5, stop_loss_pct=0.05, take_profit_pct=0.1,
                 size_request=0.01, rationale="r")
    with pytest.raises(ValidationError):
        Decision(symbol="X", side="long", confidence=1.5, stop_loss_pct=0.05, take_profit_pct=0.1,
                 size_request=0.01, rationale="r")
