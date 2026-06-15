# The snipe AGENT end-to-end — offline, pure, LLM stubbed. Proves the autonomous loop is safe + behaves: the
# agent proposes off (injected) data, the deterministic gate disposes, a mispriced market passes while a
# fairly-priced one is rejected on edge, propose-only fires nothing, bounded-autonomous green-lights only the
# passing bet, and the Mermaid viz renders the graph (LLM node + gate node present).

from __future__ import annotations

from decimal import Decimal

from cosmu.snipe import (
    ConvictionCaps,
    ConvictionGate,
    ExecutionMode,
    FairEstimate,
    GateState,
    MarketCandidate,
    SnipeAgent,
    agent_mermaid,
    pipeline_mermaid,
    viz_markdown,
    write_viz,
)


class _Source:
    def candidates(self) -> list[MarketCandidate]:
        return [
            # mispriced: market says 40c, agent thinks 60c → 20-pt edge (passes the 5-pt floor)
            MarketCandidate("m1", "Will A win?", "Yes", "t1", price=Decimal("0.40"), book_depth_usd=Decimal("1000")),
            # fair: 50c vs 50c → 0 edge (rejected on min-edge)
            MarketCandidate("m2", "Will B win?", "Yes", "t2", price=Decimal("0.50"), book_depth_usd=Decimal("1000")),
        ]


class _Estimator:
    def __init__(self, fair: dict[str, Decimal]) -> None:
        self._fair = fair

    def estimate(self, candidate: MarketCandidate, *, prompt: str, context: str) -> FairEstimate:
        return FairEstimate(
            fair_prob=self._fair[candidate.token_id],
            confidence=Decimal("0.80"),
            rationale=f"stub fair {self._fair[candidate.token_id]} for {candidate.market_id}",
            disconfirmer="resolves the other way",
        )


def _agent(mode: ExecutionMode) -> SnipeAgent:
    return SnipeAgent(
        prompt="Find mispriced World-Cup markets.",
        source=_Source(),
        estimator=_Estimator({"t1": Decimal("0.60"), "t2": Decimal("0.50")}),
        gate=ConvictionGate(),
        caps=ConvictionCaps(mode=mode),
    )


def test_agent_proposes_and_gate_disposes_propose_only() -> None:
    run = _agent(ExecutionMode.PROPOSE_ONLY).run(GateState())
    assert len(run.proposals) == 2
    by_market = {p.market_id: d for p, d in run.results}
    assert by_market["m1"].ok is True       # 20-pt edge clears the gate
    assert by_market["m2"].ok is False       # 0 edge → rejected
    assert any("edge_below_min" in r for r in by_market["m2"].reasons)
    # propose-only moves nothing — even the passing bet is not green-lit to fire.
    assert run.to_execute == [] and run.awaiting_confirm == []
    # confidence-scaled size, clamped to the per-bet cap (0.8 × $25 = $20).
    p1 = next(p for p in run.proposals if p.market_id == "m1")
    assert p1.size_usd == Decimal("20.00")


def test_bounded_autonomous_greenlights_only_the_passing_bet() -> None:
    run = _agent(ExecutionMode.BOUNDED_AUTONOMOUS).run(GateState())
    to_exec = run.to_execute
    assert [p.market_id for p in to_exec] == ["m1"]  # only the mispriced one auto-fires; the fair one doesn't


def test_human_confirm_queues_the_passing_bet() -> None:
    run = _agent(ExecutionMode.HUMAN_CONFIRM).run(GateState())
    assert [p.market_id for p in run.awaiting_confirm] == ["m1"]
    assert run.to_execute == []  # nothing auto-fires in human-confirm


def test_mermaid_viz_renders_the_graph() -> None:
    g = agent_mermaid()
    assert g.startswith("flowchart TD")
    for node in ("markets", "estimate", "gate", "route"):
        assert node in g
    assert "Estimate fair probability" in g  # the LLM node label
    assert "ConvictionGate" in g             # the deterministic gate node
    assert "flowchart LR" in pipeline_mermaid()
    assert "```mermaid" in viz_markdown()


def test_write_viz_emits_a_file(tmp_path) -> None:
    p = write_viz(tmp_path / "scratch" / "snipe_viz.md")
    assert p.exists()
    text = p.read_text()
    assert "Agent node graph" in text and "```mermaid" in text
