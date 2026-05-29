// module: SourcePort contract — every data source returns auditable raw observations.
import type { SourceDefinition, SourceFetchRequest } from "@cosmu/shared";

export type RawObservationDraft = {
  sourceKind: "x" | "web" | "news" | "market" | "manual";
  sourceName: string;
  sourceUrl?: string | null;
  observedAt?: string | null;
  title: string;
  content: string;
  rawJson?: unknown;
  contentHash?: string | null;
};

export type SourceFetchResult = {
  observations: RawObservationDraft[];
  warning?: string | null;
};

export type SourcePort = {
  definition: SourceDefinition;
  fetch: (request: SourceFetchRequest) => Promise<SourceFetchResult>;
};
