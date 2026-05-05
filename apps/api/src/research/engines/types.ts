import type { ResearchEngine, ResearchSession } from "@cosmu/shared";

export type EngineRunInput = {
  session: ResearchSession;
  objective: string;
  hypothesis: string;
  spec: Record<string, unknown>;
  datasetVersionIds: string[];
  allowedTools: string[];
};

export type EngineRunResult = {
  summary: string;
  proposedSpec: Record<string, unknown>;
  memoryNotes: Array<{ title: string; text: string; confidence?: number }>;
  candidateProposal?: {
    name: string;
    thesis: string;
    riskNotes?: string;
  } | null;
  logs?: string;
};

export type ResearchEngineAdapter = {
  key: ResearchEngine;
  run: (input: EngineRunInput) => Promise<EngineRunResult>;
};
