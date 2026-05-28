import { sql } from "../db.js";
import { llmSpendEstimateSchema } from "@cosmu/shared";

type PricingEntry = {
  provider: string;
  model: string;
  inputUsdPerMillion: number;
  outputUsdPerMillion: number;
  sourceUrl: string;
  fetchedAt: string | null;
  note: string | null;
};

type PricingCatalog = {
  entries: PricingEntry[];
  generatedAt: string;
  source: string;
};

type ActiveBotSpendRow = {
  botId: string;
  botNumber: number;
  name: string;
  frequencyMinutes: number;
};

type SampleRunCountRow = {
  botId: string;
  sampleRunCount: number;
};

type UsageRow = {
  botId: string;
  provider: string;
  model: string;
  inputTokens: number;
  outputTokens: number;
  callCount: number;
};

const SAMPLE_WINDOW_RUNS = 5;
const PRICING_REFRESH_INTERVAL_MS = 6 * 60 * 60 * 1000;
const XAI_PRICING_URL = "https://docs.x.ai/docs/models/grok-4.3";

const FALLBACK_PRICING: PricingEntry[] = [
  {
    provider: "xai",
    model: "grok-4.3",
    inputUsdPerMillion: 1.25,
    outputUsdPerMillion: 2.5,
    sourceUrl: XAI_PRICING_URL,
    fetchedAt: null,
    note: "Static fallback; refreshed from xAI docs when available."
  },
  {
    provider: "xai",
    model: "grok-4.20*",
    inputUsdPerMillion: 1.25,
    outputUsdPerMillion: 2.5,
    sourceUrl: XAI_PRICING_URL,
    fetchedAt: null,
    note: "Static fallback; refreshed from xAI docs when available."
  },
  {
    provider: "openai",
    model: "gpt-5*",
    inputUsdPerMillion: 1.25,
    outputUsdPerMillion: 10,
    sourceUrl: "https://openai.com/api/pricing/",
    fetchedAt: null,
    note: "Static public list-rate fallback. OpenAI invoices may differ by model, cache tier, and batch tier."
  },
  {
    provider: "openai",
    model: "gpt-4o",
    inputUsdPerMillion: 2.5,
    outputUsdPerMillion: 10,
    sourceUrl: "https://openai.com/api/pricing/",
    fetchedAt: null,
    note: "Static public list-rate fallback. OpenAI invoices may differ by model, cache tier, and batch tier."
  },
  {
    provider: "openai",
    model: "gpt-4o-mini",
    inputUsdPerMillion: 0.15,
    outputUsdPerMillion: 0.6,
    sourceUrl: "https://openai.com/api/pricing/",
    fetchedAt: null,
    note: "Static public list-rate fallback. OpenAI invoices may differ by model, cache tier, and batch tier."
  },
  {
    provider: "anthropic",
    model: "claude-opus*",
    inputUsdPerMillion: 15,
    outputUsdPerMillion: 75,
    sourceUrl: "https://platform.claude.com/docs/en/about-claude/pricing",
    fetchedAt: null,
    note: "Static public list-rate fallback. Cache and batch discounts are not applied."
  },
  {
    provider: "anthropic",
    model: "claude-sonnet*",
    inputUsdPerMillion: 3,
    outputUsdPerMillion: 15,
    sourceUrl: "https://platform.claude.com/docs/en/about-claude/pricing",
    fetchedAt: null,
    note: "Static public list-rate fallback. Cache and batch discounts are not applied."
  },
  {
    provider: "anthropic",
    model: "claude-haiku*",
    inputUsdPerMillion: 0.5,
    outputUsdPerMillion: 2.5,
    sourceUrl: "https://platform.claude.com/docs/en/about-claude/pricing",
    fetchedAt: null,
    note: "Static public list-rate fallback. Cache and batch discounts are not applied."
  },
  {
    provider: "google",
    model: "gemini-3-pro*",
    inputUsdPerMillion: 2,
    outputUsdPerMillion: 12,
    sourceUrl: "https://ai.google.dev/gemini-api/docs/pricing",
    fetchedAt: null,
    note: "Static public list-rate fallback for standard context. Tool fees are not included."
  },
  {
    provider: "google",
    model: "gemini-3-flash*",
    inputUsdPerMillion: 0.5,
    outputUsdPerMillion: 3,
    sourceUrl: "https://ai.google.dev/gemini-api/docs/pricing",
    fetchedAt: null,
    note: "Static public list-rate fallback. Tool fees are not included."
  },
  {
    provider: "mistral",
    model: "mistral-large*",
    inputUsdPerMillion: 2,
    outputUsdPerMillion: 6,
    sourceUrl: "https://mistral.ai/pricing",
    fetchedAt: null,
    note: "Static public list-rate fallback. Batch and regional discounts are not applied."
  },
  {
    provider: "mistral",
    model: "mistral-small*",
    inputUsdPerMillion: 0.1,
    outputUsdPerMillion: 0.3,
    sourceUrl: "https://mistral.ai/pricing",
    fetchedAt: null,
    note: "Static public list-rate fallback. Batch and regional discounts are not applied."
  }
];

let cachedPricingCatalog: PricingCatalog | null = null;
let pricingCacheExpiresAt = 0;

const priceFromXaiTokenUnits = (value: number) => value / 10000;

const fetchXaiPricing = async (): Promise<PricingEntry[]> => {
  const response = await fetch(XAI_PRICING_URL, {
    signal: AbortSignal.timeout(2500)
  });
  if (!response.ok) {
    throw new Error(`xAI pricing fetch failed with ${response.status}`);
  }

  const fetchedAt = new Date().toISOString();
  const html = (await response.text()).replace(/\\"/g, "\"");
  const regex =
    /"name":"([^"]+)".{0,3500}?"promptTextTokenPrice":"\$n(\d+)".{0,3500}?"completionTextTokenPrice":"\$n(\d+)"/gs;
  const entries: PricingEntry[] = [];
  const seen = new Set<string>();

  for (const match of html.matchAll(regex)) {
    const model = match[1];
    if (!model.startsWith("grok-") || model.includes("imagine")) continue;
    if (seen.has(model)) continue;
    seen.add(model);
    entries.push({
      provider: "xai",
      model,
      inputUsdPerMillion: priceFromXaiTokenUnits(Number(match[2])),
      outputUsdPerMillion: priceFromXaiTokenUnits(Number(match[3])),
      sourceUrl: XAI_PRICING_URL,
      fetchedAt,
      note: "Fetched from xAI model metadata embedded in the public docs page."
    });
  }

  return entries;
};

const getPricingCatalog = async (): Promise<PricingCatalog> => {
  const now = Date.now();
  if (cachedPricingCatalog && now < pricingCacheExpiresAt) {
    return cachedPricingCatalog;
  }

  let entries = FALLBACK_PRICING;
  let source = "static-fallback";

  try {
    const xaiPricing = await fetchXaiPricing();
    if (xaiPricing.length > 0) {
      entries = [
        ...xaiPricing,
        ...FALLBACK_PRICING.filter((entry) => entry.provider !== "xai")
      ];
      source = "xai-live-plus-static-fallbacks";
    }
  } catch (error) {
    console.warn("[llm-spend] using fallback pricing:", error instanceof Error ? error.message : String(error));
  }

  cachedPricingCatalog = {
    entries,
    generatedAt: new Date().toISOString(),
    source
  };
  pricingCacheExpiresAt = now + PRICING_REFRESH_INTERVAL_MS;
  return cachedPricingCatalog;
};

const modelMatches = (pattern: string, model: string) => {
  const normalizedPattern = pattern.toLowerCase();
  const normalizedModel = model.toLowerCase();
  if (normalizedPattern.endsWith("*")) {
    return normalizedModel.startsWith(normalizedPattern.slice(0, -1));
  }
  return normalizedModel === normalizedPattern || normalizedModel.includes(normalizedPattern);
};

const findPricing = (catalog: PricingCatalog, provider: string, model: string) =>
  catalog.entries.find((entry) => entry.provider === provider && modelMatches(entry.model, model)) ?? null;

const estimateCostUsd = (usage: UsageRow, pricing: PricingEntry | null) => {
  if (!pricing) return null;
  return (
    (usage.inputTokens / 1_000_000) * pricing.inputUsdPerMillion +
    (usage.outputTokens / 1_000_000) * pricing.outputUsdPerMillion
  );
};

export const getLlmSpendEstimate = async () => {
  const [activeBots, sampleRunCounts, usageRows, pricingCatalog] = await Promise.all([
    sql<ActiveBotSpendRow[]>`
      select
        b.id as "botId",
        b.bot_number as "botNumber",
        b.name,
        brc.frequency_minutes::float8 as "frequencyMinutes"
      from bots b
      join bot_runtime_configs brc on brc.bot_id = b.id
      where brc.enabled = true
      order by b.bot_number asc
    `,
    sql<SampleRunCountRow[]>`
      with recent_runs as (
        select
          r.bot_id,
          row_number() over (partition by r.bot_id order by r.created_at desc) as rn
        from runs r
        join bot_runtime_configs brc on brc.bot_id = r.bot_id
        where brc.enabled = true
          and coalesce(r.compact_context->>'source', '') <> 'guardian'
          and r.finished_at is not null
      )
      select
        bot_id as "botId",
        count(*)::int as "sampleRunCount"
      from recent_runs
      where rn <= ${SAMPLE_WINDOW_RUNS}
      group by bot_id
    `,
    sql<UsageRow[]>`
      with recent_runs as (
        select
          r.id,
          r.bot_id,
          row_number() over (partition by r.bot_id order by r.created_at desc) as rn
        from runs r
        join bot_runtime_configs brc on brc.bot_id = r.bot_id
        where brc.enabled = true
          and coalesce(r.compact_context->>'source', '') <> 'guardian'
          and r.finished_at is not null
      )
      select
        rr.bot_id as "botId",
        c.provider,
        c.model,
        coalesce(sum(c.input_tokens), 0)::int as "inputTokens",
        coalesce(sum(c.output_tokens), 0)::int as "outputTokens",
        count(c.id)::int as "callCount"
      from recent_runs rr
      join run_llm_calls c on c.run_id = rr.id
      where rr.rn <= ${SAMPLE_WINDOW_RUNS}
      group by rr.bot_id, c.provider, c.model
    `,
    getPricingCatalog()
  ]);

  const runCountByBot = new Map(sampleRunCounts.map((row) => [row.botId, Number(row.sampleRunCount ?? 0)]));
  const usageByBot = new Map<string, UsageRow[]>();
  for (const row of usageRows) {
    const usage = {
      ...row,
      inputTokens: Number(row.inputTokens ?? 0),
      outputTokens: Number(row.outputTokens ?? 0),
      callCount: Number(row.callCount ?? 0)
    };
    usageByBot.set(row.botId, [...(usageByBot.get(row.botId) ?? []), usage]);
  }

  const usedAssumptions = new Map<string, PricingEntry>();
  let estimatedHourlyUsd = 0;
  let observedSampleUsd = 0;
  let pricedBotCount = 0;
  let unknownBotCount = 0;

  const bots = activeBots.map((bot) => {
    const botUsage = usageByBot.get(bot.botId) ?? [];
    const sampleRunCount = runCountByBot.get(bot.botId) ?? 0;
    const runsPerHour = 60 / Math.max(Number(bot.frequencyMinutes), 1);
    let sampleCostUsd = 0;
    let hasUnknownPricing = false;

    const providers = botUsage.map((usage) => {
      const pricing = findPricing(pricingCatalog, usage.provider, usage.model);
      const estimatedUsd = estimateCostUsd(usage, pricing);
      if (pricing) {
        usedAssumptions.set(`${pricing.provider}:${pricing.model}`, pricing);
      } else {
        hasUnknownPricing = true;
      }
      if (estimatedUsd !== null) {
        sampleCostUsd += estimatedUsd;
        observedSampleUsd += estimatedUsd;
      }

      return {
        provider: usage.provider,
        model: usage.model,
        inputTokens: usage.inputTokens,
        outputTokens: usage.outputTokens,
        callCount: usage.callCount,
        estimatedUsd,
        pricingKnown: Boolean(pricing)
      };
    });

    const sampleInputTokens = providers.reduce((sum, provider) => sum + provider.inputTokens, 0);
    const sampleOutputTokens = providers.reduce((sum, provider) => sum + provider.outputTokens, 0);
    const sampleCallCount = providers.reduce((sum, provider) => sum + provider.callCount, 0);
    const pricingKnown = botUsage.length > 0 && sampleRunCount > 0 && !hasUnknownPricing;
    const estimatedCostPerRunUsd = pricingKnown ? sampleCostUsd / sampleRunCount : null;
    const botEstimatedHourlyUsd = estimatedCostPerRunUsd === null ? null : estimatedCostPerRunUsd * runsPerHour;
    const estimatedDailyUsd = botEstimatedHourlyUsd === null ? null : botEstimatedHourlyUsd * 24;

    if (botEstimatedHourlyUsd === null) {
      unknownBotCount += 1;
    } else {
      pricedBotCount += 1;
      estimatedHourlyUsd += botEstimatedHourlyUsd;
    }

    return {
      botId: bot.botId,
      botNumber: bot.botNumber,
      name: bot.name,
      frequencyMinutes: Number(bot.frequencyMinutes),
      runsPerHour,
      sampleRunCount,
      sampleCallCount,
      sampleInputTokens,
      sampleOutputTokens,
      estimatedCostPerRunUsd,
      estimatedHourlyUsd: botEstimatedHourlyUsd,
      estimatedDailyUsd,
      pricingKnown,
      warning:
        botUsage.length === 0 || sampleRunCount === 0
          ? "No completed token sample yet."
          : hasUnknownPricing
            ? "Missing pricing for at least one provider/model."
            : null,
      providers
    };
  });

  const generatedAt = new Date().toISOString();

  return llmSpendEstimateSchema.parse({
    generatedAt,
    currency: "USD",
    activeBotCount: activeBots.length,
    pricedBotCount,
    unknownBotCount,
    sampleWindowRuns: SAMPLE_WINDOW_RUNS,
    estimatedHourlyUsd,
    estimatedDailyUsd: estimatedHourlyUsd * 24,
    estimatedMonthlyUsd: estimatedHourlyUsd * 24 * 30,
    observedSampleUsd,
    pricingUpdatedAt: pricingCatalog.generatedAt,
    pricingSource: pricingCatalog.source,
    note: "Estimate uses recent stored token counts for active bots and current/list token rates. Provider invoices may differ because cache discounts, batch discounts, search/tool fees, taxes, and billing credits are not included.",
    assumptions: Array.from(usedAssumptions.values()),
    bots
  });
};
