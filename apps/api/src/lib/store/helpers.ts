// module: Shared store helpers (symbol tokens, row mappers).
import {
  ALL_SYMBOLS_TOKEN,
  prePromptConfigSchema,
  runtimeConfigSchema,
  traderConfigSchema,
  type PrePromptConfig,
  type RuntimeConfig,
  type TraderConfig
} from "@cosmu/shared";

type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };

export type { JsonValue };

export const parseJson = <T>(value: unknown): T => {
  if (typeof value === "string") {
    return JSON.parse(value) as T;
  }
  return value as T;
};

export const toIsoString = (value: Date | string | null | undefined) => {
  if (!value) return null;
  if (value instanceof Date) return value.toISOString();
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toISOString();
};

export const parseStoredContextSymbols = (value: unknown) => {
  const rawSymbols = parseJson<string[]>(value);
  const symbolScope = rawSymbols.includes(ALL_SYMBOLS_TOKEN) ? "all" : "selected";
  return {
    symbolScope,
    contextSymbols: rawSymbols.filter((symbol) => symbol !== ALL_SYMBOLS_TOKEN)
  } as const;
};

export const parsePromptConfig = (value: unknown): PrePromptConfig =>
  prePromptConfigSchema.parse(parseJson(value));

export const parseTraderConfig = (value: unknown): TraderConfig =>
  traderConfigSchema.parse(parseJson(value));

export const buildRuntimeConfig = (row: {
  enabled: boolean;
  venue: string;
  frequency_minutes?: number;
  frequencyMinutes?: number;
  asset_class?: "spot" | "equity";
  assetClass?: "spot";
  budget_usdt?: number;
  budgetUsdt?: number;
  execution_config?: unknown;
  executionConfig?: unknown;
  context_symbols?: unknown;
  contextSymbols?: unknown;
}): RuntimeConfig => {
  const contextSymbols = row.context_symbols ?? row.contextSymbols ?? [];
  const contextConfig = parseStoredContextSymbols(contextSymbols);
  const frequencyMinutes = row.frequency_minutes ?? row.frequencyMinutes;

  return runtimeConfigSchema.parse({
    enabled: row.enabled,
    venue: row.venue,
    frequencyMinutes,
    assetClass: row.asset_class ?? row.assetClass ?? "spot",
    budgetUsdt: row.budget_usdt ?? row.budgetUsdt ?? 1000,
    symbolScope: contextConfig.symbolScope,
    execution: parseJson<Record<string, JsonValue>>(row.execution_config ?? row.executionConfig ?? {}),
    contextSymbols: contextConfig.contextSymbols
  });
};
