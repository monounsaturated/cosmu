// module: Data-source registry — add sources here, keep adapters isolated.
import { sourceFetchRequestSchema } from "@cosmu/shared";
import { createRawObservation } from "../lib/store.js";
import type { SourcePort } from "./types.js";
import { yahooFinanceSource } from "./yahoo-finance.js";

const sourcePorts = [yahooFinanceSource] satisfies SourcePort[];
const sourceMap = new Map(sourcePorts.map((source) => [source.definition.key, source]));

export const listSourceDefinitions = () => sourcePorts.map((source) => source.definition);

export const getSourceDefinition = (key: string) => sourceMap.get(key)?.definition ?? null;

export const fetchSourceToObservations = async (key: string, rawRequest: unknown) => {
  const source = sourceMap.get(key);
  if (!source) {
    throw new Error(`Source ${key} is not registered`);
  }
  const request = sourceFetchRequestSchema.parse(rawRequest);
  const result = await source.fetch(request);
  const observations = [];
  for (const draft of result.observations) {
    observations.push(await createRawObservation(draft));
  }
  return {
    source: source.definition,
    warning: result.warning ?? null,
    observations
  };
};
