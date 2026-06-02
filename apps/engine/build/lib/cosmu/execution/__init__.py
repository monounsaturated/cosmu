# intent: execution-plane helpers (cost optimization, reconciliation) that turn intended trades into the
# cheapest viable fills; invariants: every choice is measured in net-of-cost bps so the gate's profit ranking
# stays honest, and nothing here moves money outside the live toggle + caps.
