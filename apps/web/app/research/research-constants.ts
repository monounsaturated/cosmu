// module: Research console types and pure helpers. No React — imported by research-console.tsx.
import type {
  Dataset,
  ResearchCandidate,
  ResearchDataSource,
  ResearchSession
} from "@cosmu/shared";

export type Props = {
  initialCommand?: string;
  initialDataSources: ResearchDataSource[];
  initialCandidates: ResearchCandidate[];
  initialDatasets: Dataset[];
  initialSessions: ResearchSession[];
};

export type CandidateAction = "create-bot";

export type ModelProfile = {
  id: string;
  name: string;
  provider: string;
  model: string;
};

export const DATA_SOURCE_KINDS: ResearchDataSource["kind"][] = [
  "market",
  "news",
  "web",
  "social",
  "weather",
  "astro",
  "tradingview",
  "csv",
  "custom_api",
  "ibkr",
  "polymarket"
];

export const RESEARCH_TOOL_OPTIONS = [
  { id: "web_search", label: "Web search" },
  { id: "x_search", label: "X search" },
  { id: "market_data", label: "Market data" },
  { id: "backtest", label: "Backtest" }
];

export const statusBadge = (status: string) => {
  if (status.includes("candidate") || status.includes("ready") || status.includes("success")) return "badge-success";
  if (status.includes("rejected") || status.includes("failure")) return "badge-failure";
  if (status.includes("running") || status.includes("queued")) return "badge-running";
  return "badge-neutral";
};

export const candidateStatusLabel = (status: ResearchCandidate["status"]) => {
  if (status === "paper_ready") return "ready";
  if (status === "paper_running") return "bot created";
  if (status === "paper_rejected") return "rejected";
  if (status === "live_candidate") return "promoted";
  return status;
};

const formatMetricValue = (value: unknown): string => {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return Number.isFinite(value) ? value.toFixed(2) : "—";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
};

const HIDDEN_METRIC_KEYS = new Set(["paperBotId", "paperBotStatus", "venueBotId", "venueBotStatus"]);

export const candidateMetrics = (candidate: ResearchCandidate): Array<[string, string]> => {
  if (!candidate.metrics || typeof candidate.metrics !== "object") return [];
  return Object.entries(candidate.metrics as Record<string, unknown>)
    .filter(([key]) => !HIDDEN_METRIC_KEYS.has(key))
    .map(([key, value]) => [key, formatMetricValue(value)]);
};
