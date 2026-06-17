# Guard test for the Mind->Decision mapping (P0.4d), the pure core of the agent reasoning loop. Proves: only
# weighted MARKET stances vote; weighted bullish/bearish consensus -> long/short; a weak/mixed consensus -> flat
# (looked, no edge); all-abstain/all-process -> None (ABSTAIN, never fabricate); exit defaults come from the
# agent's mandatory policy; sources + trace are populated for the visible process. No LLM needed. See
# docs/epics/agentic-lane.md.

from __future__ import annotations

from cosmu.mind.analysts import Stance
from cosmu.strategy.agent_loop import stances_to_decision
from cosmu.strategy.agent_spec import AgentExitPolicy, AgentSpec


def _agent() -> AgentSpec:
    return AgentSpec(
        name="a", rationale="r", symbols=["BTCUSDT"],
        exit=AgentExitPolicy(stop_loss_pct=0.05, take_profit_pct=0.2, trailing_pct=0.03),
    )


def _market(score: float, weight: float = 1.0, perspective: str = "Technical") -> Stance:
    return Stance(perspective=perspective, kind="market", lean="x", conviction=abs(score),
                  weight=weight, headline="h", rationale="r", score=score)


def _process(perspective: str = "ML") -> Stance:
    return Stance(perspective=perspective, kind="process", lean="neutral", conviction=0.0,
                  weight=0.0, headline="h", rationale="r", score=0.0)


def test_bullish_consensus_is_long_with_spec_exit():
    d = stances_to_decision(_agent(), "BTCUSDT", [_market(0.8), _market(0.6, perspective="Macro")])
    assert d is not None
    assert d.side == "long" and d.confidence == 0.7
    assert d.stop_loss_pct == 0.05 and d.take_profit_pct == 0.2 and d.trailing_pct == 0.03
    assert set(d.sources) == {"Technical", "Macro"} and len(d.trace) == 2


def test_bearish_consensus_is_short():
    d = stances_to_decision(_agent(), "BTCUSDT", [_market(-0.5)])
    assert d is not None and d.side == "short" and d.confidence == 0.5


def test_weak_or_mixed_consensus_is_flat():
    d = stances_to_decision(_agent(), "BTCUSDT", [_market(0.1), _market(-0.05)])  # avg 0.025 < deadband
    assert d is not None and d.side == "flat"


def test_weighting_lets_a_strong_minority_dominate():
    # (0.5*0.9 + 2.0*-0.6) / 2.5 = -0.3 -> short despite the bullish stance existing
    d = stances_to_decision(_agent(), "BTCUSDT", [_market(0.9, weight=0.5), _market(-0.6, weight=2.0)])
    assert d is not None and d.side == "short" and d.confidence == 0.3


def test_all_process_or_abstain_returns_none():
    assert stances_to_decision(_agent(), "BTCUSDT", [_process(), _process("Memory")]) is None
    assert stances_to_decision(_agent(), "BTCUSDT", [_market(0.9, weight=0.0)]) is None  # abstained market stance
