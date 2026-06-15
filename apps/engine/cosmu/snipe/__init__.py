# intent: the SNIPE LANE — an independent, lean prediction-market conviction-betting path (Polymarket-direct),
# deliberately separate from the Binance/statistical-gate lane. The agent PROPOSES (proposal.py); the
# deterministic ConvictionGate (gate.py) disposes within hard operator caps; the execution adapter (added next)
# only ever fires what the gate green-lights, per the operator's autonomy mode. Real money OFF until wallet keys
# + caps + an explicit opt-in. The LLM never fires; the deterministic caps + kill-switch are the hard safety.

from cosmu.snipe.agent import (
    AgentRun,
    FairEstimate,
    FairEstimator,
    MarketCandidate,
    MarketSource,
    Memory,
    Node,
    NODES,
    SnipeAgent,
)
from cosmu.snipe.gate import (
    ConvictionCaps,
    ConvictionGate,
    ExecutionMode,
    GateDecision,
    GateState,
)
from cosmu.snipe.proposal import ConvictionProposal
from cosmu.snipe.viz import agent_mermaid, pipeline_mermaid, viz_markdown, write_viz

__all__ = [
    "NODES",
    "AgentRun",
    "ConvictionCaps",
    "ConvictionGate",
    "ConvictionProposal",
    "ExecutionMode",
    "FairEstimate",
    "FairEstimator",
    "GateDecision",
    "GateState",
    "MarketCandidate",
    "MarketSource",
    "Memory",
    "Node",
    "SnipeAgent",
    "agent_mermaid",
    "pipeline_mermaid",
    "viz_markdown",
    "write_viz",
]
