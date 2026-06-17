# Guard test for the deterministic decision finalizer (P0.4c). Encodes the operator's risk-machine philosophy:
# thin/single-source + low-confidence signals are SIZED DOWN (with a mandatory hard stop), NEVER auto-discarded;
# size is capped at the spec; a flat signal trades nothing; exit (trailing) defaults from the spec. The LLM never
# sizes — this deterministic layer does. See docs/epics/agentic-lane.md.

from __future__ import annotations

from cosmu.strategy.agent_decision import finalize_decision
from cosmu.strategy.agent_spec import AgentExitPolicy, AgentSpec, Decision


def _agent(max_pos: float = 0.05, trailing: float | None = 0.03) -> AgentSpec:
    return AgentSpec(
        name="a", rationale="r", symbols=["DOGEUSDT"], max_position_pct=max_pos,
        exit=AgentExitPolicy(stop_loss_pct=0.05, take_profit_pct=0.2, trailing_pct=trailing),
    )


def _dec(**kw) -> Decision:
    base = dict(symbol="DOGEUSDT", side="long", confidence=0.9, stop_loss_pct=0.05, take_profit_pct=0.2,
                size_request=0.05, rationale="why", sources=["x:@a", "news:b"])
    base.update(kw)
    return Decision(**base)


def test_strong_signal_full_size_no_caution():
    r = finalize_decision(_agent(), _dec())
    assert r.would_trade and r.sized_fraction == 0.05 and r.caution == []


def test_size_capped_at_spec_max():
    r = finalize_decision(_agent(max_pos=0.02), _dec(size_request=0.5))
    assert r.sized_fraction == 0.02  # capped, not the requested 0.5


def test_single_source_is_sized_down_NOT_killed():
    # the core philosophy: one source is caution, never discard
    r = finalize_decision(_agent(), _dec(sources=["x:@only_one"]))
    assert r.would_trade is True
    assert r.sized_fraction == 0.025  # 0.05 * 0.5
    assert any("thin corroboration" in c for c in r.caution)


def test_low_confidence_is_sized_down_NOT_killed():
    r = finalize_decision(_agent(), _dec(confidence=0.3))
    assert r.would_trade is True
    assert r.sized_fraction == 0.025
    assert any("low confidence" in c for c in r.caution)


def test_thin_and_low_conf_compound_but_still_trade():
    r = finalize_decision(_agent(), _dec(sources=["x:@one"], confidence=0.2))
    assert r.would_trade is True
    assert r.sized_fraction == 0.0125  # 0.05 * 0.5 * 0.5 — small but real
    assert len(r.caution) == 2


def test_flat_signal_trades_nothing():
    r = finalize_decision(_agent(), _dec(side="flat"))
    assert r.would_trade is False and r.sized_fraction == 0.0


def test_trailing_defaults_from_spec_when_decision_unset():
    r = finalize_decision(_agent(trailing=0.04), _dec(trailing_pct=None))
    assert r.decision.trailing_pct == 0.04  # inherited the mandatory exit policy
    # and a per-decision trailing overrides the spec default
    r2 = finalize_decision(_agent(trailing=0.04), _dec(trailing_pct=0.01))
    assert r2.decision.trailing_pct == 0.01
