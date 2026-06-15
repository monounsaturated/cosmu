# intent: the snipe-lane AGENT — a framework-agnostic, VISUALIZABLE node graph that turns data + memory + a
# prompt into ConvictionProposals and routes them through the deterministic ConvictionGate. The LLM lives in
# exactly ONE node (FairEstimator) and only ESTIMATES fair probability + rationale/disconfirmer; every money
# decision is the gate's. inputs: injected MarketSource / FairEstimator / Memory + caps + a prompt; outputs: an
# AgentRun of (proposal, decision). invariants: pure given its injected providers (offline-testable, the LLM is
# stubbable), the LLM proposes and the gate disposes, and NOTHING here places an order — it emits decisions the
# executor (added next) acts on per the autonomy mode. Deliberately a thin typed graph (no framework lock-in,
# per VISION) that can be rendered to Mermaid (viz.py) or backed by LangGraph later.

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal, Protocol
from uuid import uuid4

from cosmu.snipe.gate import ConvictionCaps, ConvictionGate, GateDecision, GateState
from cosmu.snipe.proposal import ConvictionProposal


@dataclass(frozen=True)
class MarketCandidate:
    """One tradable prediction-market outcome the agent considers, with its CURRENT market price + book depth."""

    market_id: str
    question: str
    outcome: str
    token_id: str
    price: Decimal               # current market price in probability units [0,1]
    book_depth_usd: Decimal | None = None


@dataclass(frozen=True)
class FairEstimate:
    """The LLM/model node's output for one candidate — the ESTIMATE, never an order. Carries the mandatory
    rationale + disconfirmer that the proposal requires."""

    fair_prob: Decimal
    confidence: Decimal
    rationale: str
    disconfirmer: str


class MarketSource(Protocol):
    def candidates(self) -> list[MarketCandidate]: ...


class FairEstimator(Protocol):
    """The ONE LLM seam. A prod impl calls a model (via OpenRouter) over the candidate + prompt + memory; tests
    inject a deterministic stub. It estimates — it cannot move money."""

    def estimate(self, candidate: MarketCandidate, *, prompt: str, context: str) -> FairEstimate: ...


class Memory(Protocol):
    def recall(self, market_id: str) -> str: ...


# ── the pipeline as DATA (so it renders itself — viz.py) ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class Node:
    name: str
    label: str
    kind: Literal["data", "memory", "llm", "deterministic", "gate", "route"]
    deps: tuple[str, ...] = ()


# The fixed snipe pipeline. `kind` lets the viz color-code the LLM node distinctly from the deterministic gate —
# making "LLM proposes, deterministic disposes" visible at a glance.
NODES: tuple[Node, ...] = (
    Node("markets", "Load candidate markets (Polymarket odds + depth)", "data"),
    Node("memory", "Recall prior proposals + outcomes", "memory"),
    Node("estimate", "Estimate fair probability + rationale (LLM)", "llm", ("markets", "memory")),
    Node("edges", "Compute edge vs market price", "deterministic", ("estimate",)),
    Node("propose", "Emit ConvictionProposal (bounded, rationale+disconfirmer)", "deterministic", ("edges",)),
    Node("gate", "ConvictionGate — deterministic money envelope", "gate", ("propose",)),
    Node("route", "Route by mode: surface / human-confirm / auto-fire", "route", ("gate",)),
)


@dataclass(frozen=True)
class AgentRun:
    run_id: str
    prompt: str
    results: list[tuple[ConvictionProposal, GateDecision]]
    now: datetime

    @property
    def proposals(self) -> list[ConvictionProposal]:
        return [p for p, _ in self.results]

    @property
    def passed(self) -> list[tuple[ConvictionProposal, GateDecision]]:
        return [(p, d) for p, d in self.results if d.ok]

    @property
    def to_execute(self) -> list[ConvictionProposal]:
        """The proposals the gate green-lit for autonomous firing (BOUNDED_AUTONOMOUS, kill off). Empty in
        propose-only / human-confirm — the executor (next) is what actually places these."""
        return [p for p, d in self.results if d.would_execute]

    @property
    def awaiting_confirm(self) -> list[ConvictionProposal]:
        return [p for p, d in self.results if d.requires_human]


@dataclass(frozen=True)
class SnipeAgent:
    """Runs the node graph: data → memory → (LLM) estimate → edge → propose → gate → route. Pure given its
    injected providers. The size it proposes is confidence-scaled but ALWAYS ≤ the per-bet cap, so the agent
    never even asks for more than the operator allows — and the gate caps regardless."""

    prompt: str
    source: MarketSource
    estimator: FairEstimator
    gate: ConvictionGate
    caps: ConvictionCaps
    memory: Memory | None = None
    proposal_ttl_hours: int = 24
    _gate: ConvictionGate = field(default_factory=ConvictionGate, init=False)

    def _size(self, est: FairEstimate) -> Decimal:
        # Confidence-scaled stake, hard-clamped to the per-bet cap. The gate is the real bound; this just keeps
        # the proposal honest (a low-confidence idea stakes less).
        raw = (self.caps.per_bet_usd * est.confidence).quantize(Decimal("0.01"))
        return min(raw, self.caps.per_bet_usd)

    def run(self, state: GateState | None = None, *, now: datetime | None = None) -> AgentRun:
        now = now or datetime.now(tz=UTC)
        state = state or GateState(now=now)
        run_id = uuid4().hex
        expiry = now + timedelta(hours=self.proposal_ttl_hours)
        results: list[tuple[ConvictionProposal, GateDecision]] = []
        for c in self.source.candidates():
            context = self.memory.recall(c.market_id) if self.memory else ""
            est = self.estimator.estimate(c, prompt=self.prompt, context=context)
            proposal = ConvictionProposal(
                market_id=c.market_id,
                market_question=c.question,
                outcome=c.outcome,
                token_id=c.token_id,
                side="buy",
                size_usd=self._size(est),
                limit_price=c.price,
                fair_prob=est.fair_prob,
                confidence=est.confidence,
                rationale=est.rationale,
                disconfirmer=est.disconfirmer,
                expiry=expiry,
                source=run_id,
            )
            decision = self.gate.evaluate(proposal, self.caps, GateState(
                staked_today_usd=state.staked_today_usd,
                open_exposure_usd=state.open_exposure_usd,
                open_bets=state.open_bets,
                book_depth_usd=c.book_depth_usd,
                now=now,
            ))
            results.append((proposal, decision))
        return AgentRun(run_id=run_id, prompt=self.prompt, results=results, now=now)
