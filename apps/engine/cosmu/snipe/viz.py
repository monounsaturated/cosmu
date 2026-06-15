# intent: render the snipe AGENT's node graph (and the lane's end-to-end pipeline) to Mermaid, so the operator
# can SEE the agent — and, critically, where the single LLM node sits vs. the deterministic money gate. Pure
# string generation (no deps): write to a disposable .md for Claude Code, or hand the Mermaid to the front. The
# colour legend makes "LLM proposes, deterministic disposes" visible at a glance. Extensible: any pipeline that
# exposes a list[Node] can be rendered the same way (the hook for visualizing other agents/pipelines later).

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from cosmu.snipe.agent import NODES, Node

# kind → Mermaid node style. The LLM node is amber (the ONE place a model reasons); the gate is green (the
# deterministic safety). The contrast IS the architecture diagram.
_STYLE: dict[str, str] = {
    "data": "fill:#13243b,stroke:#4a90d9,color:#eaf2fb",
    "memory": "fill:#2a1840,stroke:#9b59b6,color:#f3eafb",
    "llm": "fill:#4a2c10,stroke:#e67e22,color:#fdf0e3",
    "deterministic": "fill:#1f1f1f,stroke:#7a7a7a,color:#eee",
    "gate": "fill:#0f3d22,stroke:#2ecc71,color:#e7fbef",
    "route": "fill:#0f3d3d,stroke:#1abc9c,color:#e7fbf8",
}


def agent_mermaid(nodes: Sequence[Node] = NODES) -> str:
    """The agent's node graph as a Mermaid flowchart (top-down), colour-coded by node kind."""
    lines = ["flowchart TD"]
    for n in nodes:
        lines.append(f'  {n.name}["{n.label}"]')
    for n in nodes:
        for dep in n.deps:
            lines.append(f"  {dep} --> {n.name}")
    for n in nodes:
        lines.append(f"  style {n.name} {_STYLE[n.kind]}")
    return "\n".join(lines)


def pipeline_mermaid() -> str:
    """The end-to-end lane: operator prompt + data → agent → deterministic gate → the autonomy modes → the
    Polymarket adapter. Shows the safety envelope (caps + kill-switch + real-money-off) explicitly."""
    return "\n".join(
        [
            "flowchart LR",
            '  prompt["Operator prompt + caps"]',
            '  data["Data sources<br/>(Polymarket odds, news, memory)"]',
            '  agent["Snipe agent<br/>(LLM estimates fair prob)"]',
            '  gate["ConvictionGate<br/>(deterministic caps + kill-switch)"]',
            '  m0["propose-only<br/>(surface, $0)"]',
            '  m1["human-confirm<br/>(2-click)"]',
            '  m2["bounded-autonomous<br/>(auto, within caps)"]',
            '  pm["Polymarket CLOB adapter<br/>(real USDC — OFF until keys+opt-in)"]',
            "  prompt --> agent",
            "  data --> agent",
            "  agent -->|proposals| gate",
            "  gate --> m0",
            "  gate --> m1",
            "  gate --> m2",
            "  m1 -->|operator confirms| pm",
            "  m2 -->|within caps| pm",
            "  style agent fill:#4a2c10,stroke:#e67e22,color:#fdf0e3",
            "  style gate fill:#0f3d22,stroke:#2ecc71,color:#e7fbef",
            "  style pm fill:#3b1313,stroke:#e74c3c,color:#fbeaea",
        ]
    )


def viz_markdown() -> str:
    """A self-contained Markdown doc embedding both diagrams + a legend — the disposable artifact to drop in
    `.claude/scratch/` (Claude Code renders Mermaid) or feed the front."""
    return "\n".join(
        [
            "# Snipe lane — agent & pipeline",
            "",
            "**Invariant:** the LLM (amber) only *estimates*; the deterministic `ConvictionGate` (green) is the "
            "only thing that authorizes money, and real USDC (red) stays OFF until keys + caps + opt-in.",
            "",
            "## Agent node graph",
            "```mermaid",
            agent_mermaid(),
            "```",
            "",
            "## End-to-end pipeline",
            "```mermaid",
            pipeline_mermaid(),
            "```",
            "",
            "### Legend",
            "- 🟧 **LLM** — the single node where a model reasons (estimates fair probability + rationale).",
            "- 🟩 **Gate** — deterministic caps + kill-switch; disposes every money decision.",
            "- 🟥 **Adapter** — real Polymarket execution; off until the operator wires keys + opts in.",
        ]
    )


def write_viz(path: str | Path) -> Path:
    """Write the Markdown viz to `path` (creating parents). Returns the path."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(viz_markdown(), encoding="utf-8")
    return p
