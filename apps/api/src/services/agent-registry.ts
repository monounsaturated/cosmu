// module: Declarative agent registry — prompts, tools, and schemas per agent role.
export type AgentDefinition = {
  key: string;
  label: string;
  purpose: string;
  scopeType: "bot_run" | "research";
  allowedTools: string[];
  outputContract: string;
  tracePolicy: "always";
};

export const AGENT_REGISTRY: AgentDefinition[] = [
  {
    key: "research_agent",
    label: "Research Agent",
    purpose: "Gather current evidence, form broad theses, and name specific assets without deciding orders.",
    scopeType: "bot_run",
    allowedTools: ["tradability_resolve"],
    outputContract: "Free-form evidence report with named assets/tickers and uncertainty labels.",
    tracePolicy: "always"
  },
  {
    key: "trader_agent",
    label: "Trader Agent",
    purpose: "Convert research into a TradingDecision after resolving exact tradable instruments.",
    scopeType: "bot_run",
    allowedTools: ["tradability_resolve", "binance_symbol_lookup", "get_exchange_info", "get_prices"],
    outputContract: "TradingDecision JSON accepted by @cosmu/shared tradingDecisionSchema.",
    tracePolicy: "always"
  },
  {
    key: "signal_formatter_agent",
    label: "Signal Formatter",
    purpose: "Turn raw observations into standardized qualitative/quantitative signals.",
    scopeType: "research",
    allowedTools: ["sources_fetch"],
    outputContract: "StandardizedSignal JSON accepted by @cosmu/shared standardizedSignalSchema.",
    tracePolicy: "always"
  },
  {
    key: "index_agent",
    label: "Index Agent",
    purpose: "Aggregate signals into scheduled index snapshots with evidence and numeric values.",
    scopeType: "research",
    allowedTools: ["signals_query", "sources_fetch"],
    outputContract: "IndexSnapshot JSON accepted by @cosmu/shared indexSnapshotSchema.",
    tracePolicy: "always"
  }
];

export const listAgentDefinitions = () => AGENT_REGISTRY;
