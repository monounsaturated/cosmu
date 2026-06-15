# Snipe lane — agent & pipeline

**Invariant:** the LLM (amber) only *estimates*; the deterministic `ConvictionGate` (green) is the only thing that authorizes money, and real USDC (red) stays OFF until keys + caps + opt-in.

## Agent node graph
```mermaid
flowchart TD
  markets["Load candidate markets (Polymarket odds + depth)"]
  memory["Recall prior proposals + outcomes"]
  estimate["Estimate fair probability + rationale (LLM)"]
  edges["Compute edge vs market price"]
  propose["Emit ConvictionProposal (bounded, rationale+disconfirmer)"]
  gate["ConvictionGate — deterministic money envelope"]
  route["Route by mode: surface / human-confirm / auto-fire"]
  markets --> estimate
  memory --> estimate
  estimate --> edges
  edges --> propose
  propose --> gate
  gate --> route
  style markets fill:#13243b,stroke:#4a90d9,color:#eaf2fb
  style memory fill:#2a1840,stroke:#9b59b6,color:#f3eafb
  style estimate fill:#4a2c10,stroke:#e67e22,color:#fdf0e3
  style edges fill:#1f1f1f,stroke:#7a7a7a,color:#eee
  style propose fill:#1f1f1f,stroke:#7a7a7a,color:#eee
  style gate fill:#0f3d22,stroke:#2ecc71,color:#e7fbef
  style route fill:#0f3d3d,stroke:#1abc9c,color:#e7fbf8
```

## End-to-end pipeline
```mermaid
flowchart LR
  prompt["Operator prompt + caps"]
  data["Data sources<br/>(Polymarket odds, news, memory)"]
  agent["Snipe agent<br/>(LLM estimates fair prob)"]
  gate["ConvictionGate<br/>(deterministic caps + kill-switch)"]
  m0["propose-only<br/>(surface, $0)"]
  m1["human-confirm<br/>(2-click)"]
  m2["bounded-autonomous<br/>(auto, within caps)"]
  pm["Polymarket CLOB adapter<br/>(real USDC — OFF until keys+opt-in)"]
  prompt --> agent
  data --> agent
  agent -->|proposals| gate
  gate --> m0
  gate --> m1
  gate --> m2
  m1 -->|operator confirms| pm
  m2 -->|within caps| pm
  style agent fill:#4a2c10,stroke:#e67e22,color:#fdf0e3
  style gate fill:#0f3d22,stroke:#2ecc71,color:#e7fbef
  style pm fill:#3b1313,stroke:#e74c3c,color:#fbeaea
```

### Legend
- 🟧 **LLM** — the single node where a model reasons (estimates fair probability + rationale).
- 🟩 **Gate** — deterministic caps + kill-switch; disposes every money decision.
- 🟥 **Adapter** — real Polymarket execution; off until the operator wires keys + opts in.