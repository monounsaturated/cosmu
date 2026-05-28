import { sql } from "../db.js";
import { llmSpendEstimateSchema, llmSpendOverviewSchema } from "@cosmu/shared";

export type PricingEntry = {
  provider: string;
  model: string;
  inputUsdPerMillion: number;
  outputUsdPerMillion: number;
  sourceUrl: string;
  fetchedAt: string | null;
  note: string | null;
};

export type PricingCatalog = {
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
export const PRICING_REFRESH_INTERVAL_MS = 60 * 60 * 1000;
const XAI_PRICING_URL = "https://docs.x.ai/docs/models/grok-4.3";
const PRICING_SOURCE_CHECK_TIMEOUT_MS = 3000;

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

const PRICING_SOURCE_URLS = Array.from(
  new Map(FALLBACK_PRICING.map((entry) => [`${entry.provider}:${entry.sourceUrl}`, {
    provider: entry.provider,
    sourceUrl: entry.sourceUrl
  }])).values()
);

const priceFromXaiTokenUnits = (value: number) => value / 10000;

const fetchWithTimeout = async (url: string, timeoutMs: number) => {
  const controller = new AbortController();
  let timeout: NodeJS.Timeout | null = null;
  try {
    const request = fetch(url, {
      signal: controller.signal,
      headers: { Accept: "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8" }
    });
    const timer = new Promise<Response>((_resolve, reject) => {
      timeout = setTimeout(() => {
        controller.abort();
        reject(new Error(`Fetch timed out after ${timeoutMs}ms for ${url}`));
      }, timeoutMs);
    });
    return await Promise.race([request, timer]);
  } finally {
    if (timeout) clearTimeout(timeout);
  }
};

const fetchXaiPricing = async (): Promise<PricingEntry[]> => {
  const response = await fetchWithTimeout(XAI_PRICING_URL, 2500);
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

const checkPricingSources = async () => {
  const checkedAtByProvider = new Map<string, string>();

  await Promise.allSettled(
    PRICING_SOURCE_URLS.map(async ({ provider, sourceUrl }) => {
      const response = await fetchWithTimeout(sourceUrl, PRICING_SOURCE_CHECK_TIMEOUT_MS);
      if (!response.ok) {
        throw new Error(`${provider} pricing source responded ${response.status}`);
      }
      await response.body?.cancel();
      checkedAtByProvider.set(provider, new Date().toISOString());
    })
  );

  return checkedAtByProvider;
};

export const refreshLlmPricingCatalog = async (force = false): Promise<PricingCatalog> => {
  const now = Date.now();
  if (!force && cachedPricingCatalog && now < pricingCacheExpiresAt) {
    return cachedPricingCatalog;
  }

  const checkedAtByProvider = await checkPricingSources();
  let entries = FALLBACK_PRICING.map((entry) => ({
    ...entry,
    fetchedAt: checkedAtByProvider.get(entry.provider) ?? entry.fetchedAt,
    note: checkedAtByProvider.has(entry.provider) && entry.provider !== "xai"
      ? `${entry.note} Pricing source page reachable at refresh time; list-rate parsing is kept conservative.`
      : entry.note
  }));
  let source = "static-fallback";

  try {
    const xaiPricing = await fetchXaiPricing();
    if (xaiPricing.length > 0) {
      entries = [
        ...xaiPricing,
        ...entries.filter((entry) => entry.provider !== "xai")
      ];
      source = "xai-live-plus-source-checked-fallbacks";
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

export const getLlmPricingCatalog = () => refreshLlmPricingCatalog(false);

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
  const activeBots = await sql<ActiveBotSpendRow[]>`
      select
        b.id as "botId",
        b.bot_number as "botNumber",
        b.name,
        brc.frequency_minutes::float8 as "frequencyMinutes"
      from bots b
      join bot_runtime_configs brc on brc.bot_id = b.id
      where brc.enabled = true
      order by b.bot_number asc
    `;
  const sampleRunCounts = await sql<SampleRunCountRow[]>`
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
    `;
  const usageRows = await sql<UsageRow[]>`
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
    `;
  const pricingCatalog = await getLlmPricingCatalog();

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

type SpendAggregateRow = {
  provider: string;
  model: string;
  inputTokens: number;
  outputTokens: number;
  callCount: number;
  last24hInputTokens: number;
  last24hOutputTokens: number;
  last24hCallCount: number;
  last7dInputTokens: number;
  last7dOutputTokens: number;
  last7dCallCount: number;
  last30dInputTokens: number;
  last30dOutputTokens: number;
  last30dCallCount: number;
};

type BotSpendAggregateRow = {
  botId: string;
  botNumber: number;
  name: string;
  enabled: boolean;
  frequencyMinutes: number | null;
  provider: string;
  model: string;
  inputTokens: number;
  outputTokens: number;
  callCount: number;
  last24hInputTokens: number;
  last24hOutputTokens: number;
  last24hCallCount: number;
  lastCallAt: Date | string | null;
};

type RecentRunSpendRow = {
  runId: string;
  botId: string;
  botNumber: number;
  botName: string;
  status: string;
  startedAt: Date | string;
  finishedAt: Date | string | null;
  provider: string;
  model: string;
  inputTokens: number;
  outputTokens: number;
  callCount: number;
};

const estimateTokensCostUsd = (
  catalog: PricingCatalog,
  provider: string,
  model: string,
  inputTokens: number,
  outputTokens: number
) =>
  estimateCostUsd(
    { botId: "", provider, model, inputTokens, outputTokens, callCount: 0 },
    findPricing(catalog, provider, model)
  );

const toIsoString = (value: Date | string | null | undefined) => {
  if (!value) return null;
  if (value instanceof Date) return value.toISOString();
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString();
};

export const getLlmSpendOverview = async () => {
  const estimate = await getLlmSpendEstimate();
  const pricingCatalog = await getLlmPricingCatalog();
  const aggregateRows = await sql<SpendAggregateRow[]>`
      select
        provider,
        model,
        coalesce(sum(input_tokens), 0)::int as "inputTokens",
        coalesce(sum(output_tokens), 0)::int as "outputTokens",
        count(*)::int as "callCount",
        coalesce(sum(case when created_at >= now() - interval '24 hours' then coalesce(input_tokens, 0) else 0 end), 0)::int as "last24hInputTokens",
        coalesce(sum(case when created_at >= now() - interval '24 hours' then coalesce(output_tokens, 0) else 0 end), 0)::int as "last24hOutputTokens",
        count(*) filter (where created_at >= now() - interval '24 hours')::int as "last24hCallCount",
        coalesce(sum(case when created_at >= now() - interval '7 days' then coalesce(input_tokens, 0) else 0 end), 0)::int as "last7dInputTokens",
        coalesce(sum(case when created_at >= now() - interval '7 days' then coalesce(output_tokens, 0) else 0 end), 0)::int as "last7dOutputTokens",
        count(*) filter (where created_at >= now() - interval '7 days')::int as "last7dCallCount",
        coalesce(sum(case when created_at >= now() - interval '30 days' then coalesce(input_tokens, 0) else 0 end), 0)::int as "last30dInputTokens",
        coalesce(sum(case when created_at >= now() - interval '30 days' then coalesce(output_tokens, 0) else 0 end), 0)::int as "last30dOutputTokens",
        count(*) filter (where created_at >= now() - interval '30 days')::int as "last30dCallCount"
      from run_llm_calls
      group by provider, model
    `;
  const botAggregateRows = await sql<BotSpendAggregateRow[]>`
      select
        b.id as "botId",
        b.bot_number as "botNumber",
        b.name,
        coalesce(brc.enabled, false) as enabled,
        brc.frequency_minutes::float8 as "frequencyMinutes",
        c.provider,
        c.model,
        coalesce(sum(c.input_tokens), 0)::int as "inputTokens",
        coalesce(sum(c.output_tokens), 0)::int as "outputTokens",
        count(c.id)::int as "callCount",
        coalesce(sum(case when c.created_at >= now() - interval '24 hours' then coalesce(c.input_tokens, 0) else 0 end), 0)::int as "last24hInputTokens",
        coalesce(sum(case when c.created_at >= now() - interval '24 hours' then coalesce(c.output_tokens, 0) else 0 end), 0)::int as "last24hOutputTokens",
        count(c.id) filter (where c.created_at >= now() - interval '24 hours')::int as "last24hCallCount",
        max(c.created_at) as "lastCallAt"
      from run_llm_calls c
      join runs r on r.id = c.run_id
      join bots b on b.id = r.bot_id
      left join bot_runtime_configs brc on brc.bot_id = b.id
      group by b.id, b.bot_number, b.name, brc.enabled, brc.frequency_minutes, c.provider, c.model
    `;
  const recentRunRows = await sql<RecentRunSpendRow[]>`
      with recent_run_ids as (
        select r.id
        from runs r
        join run_llm_calls c on c.run_id = r.id
        group by r.id
        order by max(c.created_at) desc
        limit 25
      )
      select
        r.id as "runId",
        b.id as "botId",
        b.bot_number as "botNumber",
        b.name as "botName",
        r.status,
        r.started_at as "startedAt",
        r.finished_at as "finishedAt",
        c.provider,
        c.model,
        coalesce(sum(c.input_tokens), 0)::int as "inputTokens",
        coalesce(sum(c.output_tokens), 0)::int as "outputTokens",
        count(c.id)::int as "callCount"
      from recent_run_ids recent
      join runs r on r.id = recent.id
      join bots b on b.id = r.bot_id
      join run_llm_calls c on c.run_id = r.id
      group by r.id, b.id, b.bot_number, b.name, r.status, r.started_at, r.finished_at, c.provider, c.model
      order by r.started_at desc
    `;

  const assumptions = new Map<string, PricingEntry>();
  const sumCost = (
    rows: Array<{ provider: string; model: string; inputTokens: number; outputTokens: number; callCount: number }>,
    keyPrefix = ""
  ) => {
    let usd = 0;
    let unknownCalls = 0;
    let inputTokens = 0;
    let outputTokens = 0;
    let callCount = 0;

    for (const row of rows) {
      const pricing = findPricing(pricingCatalog, row.provider, row.model);
      const cost = estimateCostUsd(
        {
          botId: "",
          provider: row.provider,
          model: row.model,
          inputTokens: Number(row.inputTokens ?? 0),
          outputTokens: Number(row.outputTokens ?? 0),
          callCount: Number(row.callCount ?? 0)
        },
        pricing
      );
      if (pricing) {
        assumptions.set(`${keyPrefix}${pricing.provider}:${pricing.model}`, pricing);
      } else {
        unknownCalls += Number(row.callCount ?? 0);
      }
      if (cost !== null) usd += cost;
      inputTokens += Number(row.inputTokens ?? 0);
      outputTokens += Number(row.outputTokens ?? 0);
      callCount += Number(row.callCount ?? 0);
    }

    return { usd, unknownCalls, inputTokens, outputTokens, callCount };
  };

  const allTime = sumCost(aggregateRows);
  const last24h = sumCost(aggregateRows.map((row) => ({
    provider: row.provider,
    model: row.model,
    inputTokens: row.last24hInputTokens,
    outputTokens: row.last24hOutputTokens,
    callCount: row.last24hCallCount
  })));
  const last7d = sumCost(aggregateRows.map((row) => ({
    provider: row.provider,
    model: row.model,
    inputTokens: row.last7dInputTokens,
    outputTokens: row.last7dOutputTokens,
    callCount: row.last7dCallCount
  })));
  const last30d = sumCost(aggregateRows.map((row) => ({
    provider: row.provider,
    model: row.model,
    inputTokens: row.last30dInputTokens,
    outputTokens: row.last30dOutputTokens,
    callCount: row.last30dCallCount
  })));

  const estimatedByBotId = new Map(estimate.bots.map((bot) => [bot.botId, bot]));
  const botSpend = new Map<string, {
    botId: string;
    botNumber: number;
    name: string;
    enabled: boolean;
    frequencyMinutes: number | null;
    totalUsd: number;
    totalKnown: boolean;
    last24hUsd: number;
    last24hKnown: boolean;
    callCount: number;
    inputTokens: number;
    outputTokens: number;
    lastCallAt: string | null;
  }>();

  for (const row of botAggregateRows) {
    const current = botSpend.get(row.botId) ?? {
      botId: row.botId,
      botNumber: Number(row.botNumber),
      name: row.name,
      enabled: row.enabled,
      frequencyMinutes: row.frequencyMinutes === null ? null : Number(row.frequencyMinutes),
      totalUsd: 0,
      totalKnown: true,
      last24hUsd: 0,
      last24hKnown: true,
      callCount: 0,
      inputTokens: 0,
      outputTokens: 0,
      lastCallAt: null
    };

    const totalCost = estimateTokensCostUsd(
      pricingCatalog,
      row.provider,
      row.model,
      Number(row.inputTokens ?? 0),
      Number(row.outputTokens ?? 0)
    );
    const last24hCost = estimateTokensCostUsd(
      pricingCatalog,
      row.provider,
      row.model,
      Number(row.last24hInputTokens ?? 0),
      Number(row.last24hOutputTokens ?? 0)
    );

    if (totalCost === null) current.totalKnown = false;
    else current.totalUsd += totalCost;
    if (last24hCost === null) current.last24hKnown = false;
    else current.last24hUsd += last24hCost;

    current.callCount += Number(row.callCount ?? 0);
    current.inputTokens += Number(row.inputTokens ?? 0);
    current.outputTokens += Number(row.outputTokens ?? 0);
    const lastCallAt = toIsoString(row.lastCallAt);
    if (lastCallAt && (!current.lastCallAt || lastCallAt > current.lastCallAt)) current.lastCallAt = lastCallAt;

    botSpend.set(row.botId, current);
  }

  const recentRuns = new Map<string, {
    runId: string;
    botId: string;
    botNumber: number;
    botName: string;
    status: string;
    startedAt: string;
    finishedAt: string | null;
    totalUsd: number;
    totalKnown: boolean;
    callCount: number;
    inputTokens: number;
    outputTokens: number;
  }>();

  for (const row of recentRunRows) {
    const current = recentRuns.get(row.runId) ?? {
      runId: row.runId,
      botId: row.botId,
      botNumber: Number(row.botNumber),
      botName: row.botName,
      status: row.status,
      startedAt: toIsoString(row.startedAt) ?? new Date().toISOString(),
      finishedAt: toIsoString(row.finishedAt),
      totalUsd: 0,
      totalKnown: true,
      callCount: 0,
      inputTokens: 0,
      outputTokens: 0
    };
    const cost = estimateTokensCostUsd(
      pricingCatalog,
      row.provider,
      row.model,
      Number(row.inputTokens ?? 0),
      Number(row.outputTokens ?? 0)
    );
    if (cost === null) current.totalKnown = false;
    else current.totalUsd += cost;
    current.callCount += Number(row.callCount ?? 0);
    current.inputTokens += Number(row.inputTokens ?? 0);
    current.outputTokens += Number(row.outputTokens ?? 0);
    recentRuns.set(row.runId, current);
  }

  const parsed = llmSpendOverviewSchema.parse({
    generatedAt: new Date().toISOString(),
    currency: "USD",
    estimate,
    totals: {
      allTimeUsd: allTime.usd,
      last24hUsd: last24h.usd,
      last7dUsd: last7d.usd,
      last30dUsd: last30d.usd,
      callCount: allTime.callCount,
      inputTokens: allTime.inputTokens,
      outputTokens: allTime.outputTokens,
      unknownCostCallCount: allTime.unknownCalls
    },
    topBots: Array.from(botSpend.values())
      .sort((a, b) => b.totalUsd - a.totalUsd)
      .slice(0, 25)
      .map((bot) => ({
        botId: bot.botId,
        botNumber: bot.botNumber,
        name: bot.name,
        enabled: bot.enabled,
        frequencyMinutes: bot.frequencyMinutes,
        totalUsd: bot.totalKnown ? bot.totalUsd : null,
        last24hUsd: bot.last24hKnown ? bot.last24hUsd : null,
        callCount: bot.callCount,
        inputTokens: bot.inputTokens,
        outputTokens: bot.outputTokens,
        lastCallAt: bot.lastCallAt,
        estimatedCostPerRunUsd: estimatedByBotId.get(bot.botId)?.estimatedCostPerRunUsd ?? null,
        estimatedHourlyUsd: estimatedByBotId.get(bot.botId)?.estimatedHourlyUsd ?? null
      })),
    recentRuns: Array.from(recentRuns.values()).map((run) => ({
      runId: run.runId,
      botId: run.botId,
      botNumber: run.botNumber,
      botName: run.botName,
      status: run.status,
      startedAt: run.startedAt,
      finishedAt: run.finishedAt,
      totalUsd: run.totalKnown ? run.totalUsd : null,
      callCount: run.callCount,
      inputTokens: run.inputTokens,
      outputTokens: run.outputTokens
    })),
    pricing: {
      updatedAt: pricingCatalog.generatedAt,
      source: pricingCatalog.source,
      assumptions: Array.from(assumptions.values())
    }
  });
  return parsed;
};
